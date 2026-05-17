"""[Phase C 대체] 정제된 캡션으로 Img Im 축 재임베딩.

배경:
  refine_captions_sentence_filter.py 로 한국어 문장만 추출한
  captions_triple.refined.jsonl 을 입력으로 BGE-M3 임베딩을 재계산.
  Re/Z 시각 축은 유지 — Im 축(텍스트 임베딩) 만 교체.

장점:
  - Phase C (Qwen-VL 재호출) 14시간 → 약 15분 (BGE-M3 만)
  - 한국어 정보 보존, 중국어/영어 노이즈 제거
  - 시각 정보 무변경 (Re·Z 유지)

동작:
  1) refined jsonl 로드 → key → L3 매핑
  2) img_ids.json 의 각 id 에 대해 L3 가져옴 (없으면 빈 문자열)
  3) BGE-M3 passage 임베딩 (batch)
  4) cache_img_Im_e5cap.npy 백업 후 교체
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "App" / "backend"))
from config import PATHS  # noqa: E402

CACHE = Path(PATHS["TRICHEF_IMG_CACHE"])


def main():
    ts = int(time.time())
    print(f"=== Img Im 축 재임베딩 (정제 캡션 기반, ts={ts}) ===")

    # 1) 정제된 캡션 로드
    refined_path = CACHE / "captions_triple.refined.jsonl"
    if not refined_path.exists():
        print(f"[error] {refined_path} 없음. refine_captions_sentence_filter.py 먼저 실행.")
        sys.exit(1)

    key_to_l3: dict[str, str] = {}
    with refined_path.open("r", encoding="utf-8") as f:
        for ln in f:
            try:
                d = json.loads(ln)
                key_to_l3[d.get("key", "")] = (d.get("L3") or "").strip()
            except Exception:
                pass
    print(f"  정제된 캡션: {len(key_to_l3)}건")

    # 2) ids 로드
    ids_path = CACHE / "img_ids.json"
    raw = json.loads(ids_path.read_text(encoding="utf-8"))
    ids = raw.get("ids", []) if isinstance(raw, dict) else list(raw)
    print(f"  img_ids.json: {len(ids)}건")

    # 3) 각 id 에 대해 L3 매핑
    texts = []
    missing = 0
    empty = 0
    for rid in ids:
        l3 = key_to_l3.get(rid, "")
        if not l3:
            missing += 1
            l3 = ""  # 빈 텍스트도 임베딩 (zero-like vector)
        if len(l3) < 4:
            empty += 1
        texts.append(l3 or " ")  # BGE-M3 빈 입력 회피 위해 공백 1자
    print(f"  매칭: {len(ids) - missing}건 / 누락: {missing}건 / 빈: {empty}건")

    # 4) BGE-M3 임베딩
    print(f"  BGE-M3 로드 중...")
    from embedders.trichef import bgem3_caption_im as im_embedder
    print(f"  배치 임베딩 시작 ({len(texts)}건)...")
    t0 = time.time()
    BATCH = 64
    vecs_all = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i+BATCH]
        vecs = im_embedder.embed_passage(batch)  # (B, 1024)
        if vecs is None or vecs.size == 0:
            # 폴백: 영벡터
            vecs = np.zeros((len(batch), 1024), dtype=np.float32)
        vecs_all.append(vecs)
        if (i // BATCH) % 5 == 0:
            elapsed = time.time() - t0
            done = i + len(batch)
            avg = elapsed / max(done, 1)
            eta = avg * (len(texts) - done) / 60
            print(f"    [{done:>5d}/{len(texts)}]  avg={avg:.2f}s/건  ETA={eta:.1f}분")
    Im_new = np.vstack(vecs_all).astype(np.float32)
    print(f"  완료: Im shape={Im_new.shape} ({(time.time()-t0):.0f}초)")

    # 5) 백업 + 교체
    npy = CACHE / "cache_img_Im_e5cap.npy"
    if npy.exists():
        bk = npy.with_suffix(npy.suffix + f".pre_refined_{ts}")
        shutil.copy2(npy, bk)
        print(f"  백업: {bk.name}")

    tmp = npy.with_suffix(npy.suffix + f".tmp.{ts}")
    np.save(tmp, Im_new)
    if not tmp.exists() and tmp.with_suffix(tmp.suffix + ".npy").exists():
        tmp.with_suffix(tmp.suffix + ".npy").rename(tmp)
    if npy.exists():
        npy.unlink()
    shutil.move(tmp, npy)
    print(f"  ✓ 저장: {npy.name} shape={Im_new.shape}")

    # 6) captions_triple.jsonl 원본을 refined 로 교체 (선택)
    orig = CACHE / "captions_triple.jsonl"
    if orig.exists():
        bk = orig.with_suffix(orig.suffix + f".pre_refined_{ts}")
        shutil.copy2(orig, bk)
        print(f"  captions_triple.jsonl 백업: {bk.name}")
        shutil.copy2(refined_path, orig)
        print(f"  captions_triple.jsonl ← refined 적용")

    print(f"\n=== 완료 ({(time.time()-t0)/60:.1f}분) ===")
    print("후속: 앱 재시작 또는 reload_engine()")


if __name__ == "__main__":
    main()
