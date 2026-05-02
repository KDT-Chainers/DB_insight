"""Qwen2.5-VL-3B 한국어 풍부 캡션 — 5-stage 영화 메타데이터 형식.

각 이미지에 대해 5단계 캡션 생성:
  Stage 1: title    — 1줄 핵심 (~10단어)
  Stage 2: tagline  — 1~2줄 분위기·감정 (~30단어)
  Stage 3: synopsis — 3~5문장 객관 묘사 (~100단어)
  Stage 4: tags_kr  — 한국어 키워드 10~20개
  Stage 5: tags_en  — 영어 키워드 10~20개

저장: extracted_DB/Img/captions/<key>_<stage>.txt
  → Resume 가능 (절전 후 이어서) — skip-existing 자동.

사용:
  python scripts/rebuild_img_qwen_full_caption.py --stage all
  python scripts/rebuild_img_qwen_full_caption.py --stage title,tagline,synopsis  # Day 1
  python scripts/rebuild_img_qwen_full_caption.py --stage tags_kr,tags_en          # Day 2
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[rebuild_img_qwen_full_caption] 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
IMG_CACHE = ROOT / "Data" / "embedded_DB" / "Img"
CAP_DIR   = ROOT / "Data" / "extracted_DB" / "Img" / "captions"

# 5-stage prompts
PROMPTS = {
    "title":
        "이 사진의 핵심을 1줄로 한국어로 표현하세요. 객체와 핵심 행동만 간결하게. "
        "예: '사람 손에 만져지는 회색 고양이'",
    "tagline":
        "이 사진의 분위기, 감정, 시각적 인상을 한국어로 1~2문장으로 묘사하세요. "
        "예: '따뜻한 손길에 편안하게 누운 고양이의 안도감이 느껴지는 친밀한 순간'",
    "synopsis":
        "이 사진을 한국어로 자세히 묘사하세요. 다음을 모두 포함하여 3~5문장으로: "
        "주요 객체, 인물 유무, 행동·동작, 위치·배경, 색감, 분위기. "
        "예: '회색 줄무늬 고양이가 침대 위에 누워있고, 사람의 오른손이 고양이의 머리를 부드럽게 쓰다듬고 있다. "
        "고양이는 눈을 감고 편안한 표정을 짓고 있으며, 배경은 흰색 침구로 따뜻한 빛이 비추고 있다.'",
    "tags_kr":
        "이 사진을 표현하는 한국어 키워드를 10~20개 쉼표로 구분하여 출력하세요. "
        "객체, 행동, 색깔, 분위기, 장소를 모두 포함하세요. "
        "예: '고양이, 회색, 줄무늬, 손, 만지기, 쓰다듬기, 침대, 누워있음, 편안함, 교감, 친밀, 실내, 부드러움'",
    "tags_en":
        "Output 10~20 English keywords separated by commas describing this image. "
        "Include objects, actions, colors, mood, location. "
        "Example: 'cat, gray, tabby, hand, petting, touching, bed, lying, comfortable, bond, intimate, indoor'",
}

MAX_NEW_TOKENS = {
    "title": 30,
    "tagline": 60,
    "synopsis": 150,
    "tags_kr": 80,
    "tags_en": 80,
}


def load_qwen():
    """Qwen2.5-VL-3B-Instruct 로드."""
    sys.path.insert(0, str(ROOT / "DI_TriCHEF"))
    from captioner.qwen_vl_ko import QwenKoCaptioner
    print("Qwen2.5-VL-3B 로드 중...", flush=True)
    cap = QwenKoCaptioner(dtype="float16")
    cap._load()  # 명시적 GPU 로드
    print("로드 완료", flush=True)
    return cap


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="all",
                        help="all | title | tagline | synopsis | tags_kr | tags_en (콤마 구분 가능)")
    parser.add_argument("--max-image-side", type=int, default=672,
                        help="이미지 최대 변 (작을수록 빠름)")
    args = parser.parse_args()

    # stage 결정
    if args.stage == "all":
        stages = list(PROMPTS.keys())
    else:
        stages = [s.strip() for s in args.stage.split(",")]
        for s in stages:
            if s not in PROMPTS:
                print(f"[ERROR] unknown stage: {s}", flush=True)
                return 2

    print(f"실행 stages: {stages}", flush=True)

    # ids 로드
    ids = json.loads((IMG_CACHE / "img_ids.json").read_text(encoding="utf-8"))
    ids_list = ids.get("ids", []) if isinstance(ids, dict) else ids
    n = len(ids_list)
    print(f"이미지 수: {n}", flush=True)

    # registry — abs 경로
    reg = json.loads((IMG_CACHE / "registry.json").read_text(encoding="utf-8"))

    # 경로 매핑
    paths = []
    for key in ids_list:
        ap = None
        v = reg.get(key)
        if isinstance(v, dict):
            cand = v.get("abs")
            if cand and Path(cand).is_file():
                ap = Path(cand)
        if ap is None:
            # alias 시도
            if isinstance(v, dict):
                for a in v.get("abs_aliases") or []:
                    if Path(a).is_file():
                        ap = Path(a)
                        break
        paths.append(ap)
    n_valid = sum(1 for p in paths if p)
    print(f"디스크 매핑: {n_valid}/{n}", flush=True)

    CAP_DIR.mkdir(parents=True, exist_ok=True)

    # Qwen 로드 (모든 stage 공유)
    cap = load_qwen()
    from PIL import Image

    for stage in stages:
        prompt = PROMPTS[stage]
        max_new = MAX_NEW_TOKENS[stage]
        print(f"\n=== Stage: {stage} (max_new={max_new}) ===", flush=True)

        # skip 체크
        skip_idx = set()
        for i, key in enumerate(ids_list):
            out_path = CAP_DIR / f"{key.replace('/', '__')}_{stage}.txt"
            if out_path.is_file():
                skip_idx.add(i)
        todo_idx = [i for i in range(n) if i not in skip_idx and paths[i] is not None]
        print(f"  skip (이미 처리): {len(skip_idx)}", flush=True)
        print(f"  처리 대상: {len(todo_idx)}", flush=True)

        if not todo_idx:
            continue

        t0 = time.time()
        n_done = 0
        n_fail = 0
        for j, i in enumerate(todo_idx):
            if j % 50 == 0 and j > 0:
                elapsed = time.time() - t0
                eta = elapsed / j * (len(todo_idx) - j)
                print(f"  {j}/{len(todo_idx)} done={n_done} fail={n_fail} "
                      f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)
            p = paths[i]
            key = ids_list[i]
            out_path = CAP_DIR / f"{key.replace('/', '__')}_{stage}.txt"
            try:
                img = Image.open(p).convert("RGB")
                txt = cap.caption(img, max_new_tokens=max_new,
                                  max_image_side=args.max_image_side,
                                  prompt=prompt)
                txt = (txt or "").strip()
                if txt:
                    out_path.write_text(txt, encoding="utf-8")
                    n_done += 1
                else:
                    n_fail += 1
            except Exception as e:
                n_fail += 1
                if n_fail < 5:
                    print(f"    실패 [{i}]: {type(e).__name__}: {str(e)[:100]}", flush=True)

        elapsed = time.time() - t0
        print(f"  {stage} 완료: done={n_done} fail={n_fail} elapsed={elapsed:.0f}s", flush=True)

    print("\n전체 stages 완료.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
