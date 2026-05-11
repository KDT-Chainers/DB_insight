"""scripts/repair_image_chinese_captions.py — 이미지 5-stage 캡션 중 중국어로 작성된 항목을 한국어로 재생성.

배경:
  Qwen 캡셔닝 시 한국어 prompt 무시하고 중국어로 응답한 케이스가 약 1,075/2,381건 (45%).
  location_resolver._clean_caption_text 가 CJK 5% 초과 라인을 제거 → 표시 시 "상세" 누락.
  v2 cleaner(줄 단위) 로 일부 복구되지만, raw 자체가 거의 다 중국어인 항목은 재생성 필요.

전략:
  1) extracted_DB/Img/captions/*_{title,tagline,synopsis}.txt 스캔
  2) 각 stage 별로 한자 비율 ≥ 30% 이면 "중국어 오염" 으로 분류
  3) Qwen2.5-VL-3B 로 stage별 한국어 강제 prompt 로 재생성
  4) 결과 파일 덮어쓰기 (원본은 .zh.bak 으로 백업)
  5) 50건마다 체크포인트 저장, resume 가능

실행: python scripts/repair_image_chinese_captions.py [--dry-run] [--max N]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = _BACKEND_DIR.parent.parent
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "DI_TriCHEF"))

# 한국어 강제 prompt (한국어 단독, 중국어 금지 명시)
PROMPTS = {
    "title":    "[한국어로만 답변. 중국어 금지.] 이 사진의 핵심을 한국어 1줄로 표현하세요. 객체와 핵심 행동만 간결하게.",
    "tagline":  "[한국어로만 답변. 중국어 금지.] 이 사진의 분위기, 감정, 시각적 인상을 한국어 1~2문장으로 묘사하세요.",
    "synopsis": "[한국어로만 답변. 중국어 금지.] 이 사진을 한국어로 자세히 묘사하세요. 주요 객체, 인물 유무, 행동, 위치, 색감, 분위기를 3~5문장으로.",
}
MAX_NEW = {"title": 30, "tagline": 80, "synopsis": 200}

CKPT_PATH = _BACKEND_DIR / "scripts" / "repair_image_chinese_captions_ckpt.json"


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    n_cjk = sum(1 for c in text if "一" <= c <= "鿿")
    return n_cjk / max(1, len(text))


def _scan_bad(cap_dir: Path) -> dict[str, set[str]]:
    """key → {bad stages}. CJK 비율 ≥ 30% 인 stage 만 표기."""
    bad: dict[str, set[str]] = {}
    for stage in ("title", "tagline", "synopsis"):
        for f in cap_dir.glob(f"*_{stage}.txt"):
            key = f.name[: -len(f"_{stage}.txt")]
            try:
                txt = f.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if _cjk_ratio(txt) >= 0.30:
                bad.setdefault(key, set()).add(stage)
    return bad


def _key_to_img_path(raw_img_dir: Path, key: str) -> Path | None:
    """ '__' 구분 key → raw_DB/Img/<...> 실제 경로 후보 탐색.
    예: 'YS_1차__20191028_115538_012.jpg' → raw_DB/Img/YS_1차/20191028_115538_012.jpg
    """
    parts = key.split("__")
    if len(parts) < 2:
        return None
    candidate = raw_img_dir.joinpath(*parts)
    if candidate.is_file():
        return candidate
    # 일부 key 는 폴더 한 단계 더 깊을 수 있음 — 평탄 검색 fallback
    name = parts[-1]
    for p in raw_img_dir.rglob(name):
        return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="스캔만 수행. 재캡션 X.")
    ap.add_argument("--max", type=int, default=0, help="처리 상한 (0 = 전체)")
    args = ap.parse_args()

    from config import PATHS
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    raw_img_dir = Path(PATHS["RAW_DB"]) / "Img"
    log.info(f"caption dir : {cap_dir}")
    log.info(f"raw image   : {raw_img_dir}")

    # 1) 스캔
    log.info("scanning...")
    bad = _scan_bad(cap_dir)
    n_keys = len(bad)
    n_stages = sum(len(v) for v in bad.values())
    log.info(f"bad images: {n_keys}건 (stages: {n_stages}개)")
    by_stage = {"title": 0, "tagline": 0, "synopsis": 0}
    for st in bad.values():
        for s in st:
            by_stage[s] += 1
    log.info(f"  by stage: {by_stage}")

    if args.dry_run:
        log.info("[dry-run] 종료")
        return

    if not bad:
        log.info("재캡션 대상 없음. 종료.")
        return

    # 2) 체크포인트
    done: dict[str, list[str]] = {}
    if CKPT_PATH.exists():
        try:
            done = json.loads(CKPT_PATH.read_text(encoding="utf-8"))
            log.info(f"체크포인트 로드: {len(done)}건 완료")
        except Exception:
            done = {}

    todo = [(k, sorted(s)) for k, s in bad.items() if set(s) - set(done.get(k, []))]
    if args.max > 0:
        todo = todo[: args.max]
    log.info(f"잔여: {len(todo)}건")

    # 3) Qwen 로드
    log.info("Qwen2.5-VL-3B 로드 중...")
    from captioner.qwen_vl_ko import QwenKoCaptioner
    from PIL import Image
    cap = QwenKoCaptioner(dtype="float16")
    cap._load()
    log.info("로드 완료")

    # 4) 처리 루프
    t0 = time.time()
    n_proc = 0
    save_every = 50
    for i, (key, stages) in enumerate(todo, 1):
        img_path = _key_to_img_path(raw_img_dir, key)
        if img_path is None:
            log.warning(f"  [{i}] {key}: 원본 이미지 없음 → skip")
            done[key] = list(set(done.get(key, [])) | set(stages))
            continue
        try:
            pil = Image.open(str(img_path)).convert("RGB")
        except Exception as e:
            log.warning(f"  [{i}] {key}: PIL 로드 실패 ({e})")
            continue

        prev_done = set(done.get(key, []))
        new_done = set(prev_done)
        for stage in stages:
            if stage in prev_done:
                continue
            try:
                txt = cap.caption(pil, prompt=PROMPTS[stage], max_new_tokens=MAX_NEW[stage])
                txt = (txt or "").strip()
            except Exception as e:
                log.warning(f"  [{i}] {key} {stage} 실패: {e}")
                continue
            # 결과가 여전히 중국어 위주면 skip (백업·덮어쓰기 안 함)
            if _cjk_ratio(txt) >= 0.30 or not txt:
                log.warning(f"  [{i}] {key} {stage}: 재생성 결과도 중국어/빈문자 → 보류")
                continue
            target = cap_dir / f"{key}_{stage}.txt"
            try:
                if target.exists():
                    bak = target.with_suffix(".txt.zh.bak")
                    if not bak.exists():
                        bak.write_bytes(target.read_bytes())
                target.write_text(txt, encoding="utf-8")
                new_done.add(stage)
            except Exception as e:
                log.warning(f"  [{i}] {key} {stage}: 저장 실패 {e}")

        done[key] = sorted(new_done)
        n_proc += 1

        if i % 10 == 0:
            elapsed = time.time() - t0
            remain = (len(todo) - i) * (elapsed / max(i, 1))
            log.info(f"  [{i}/{len(todo)}] {key[:50]} — 경과 {elapsed/60:.1f}분, 잔여 ~{remain/60:.1f}분")
        if i % save_every == 0:
            CKPT_PATH.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info(f"    체크포인트 저장 ({i}건)")

    CKPT_PATH.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"완료: {n_proc}건 처리 / 총 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
