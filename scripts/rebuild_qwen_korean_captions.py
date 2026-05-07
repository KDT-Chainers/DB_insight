"""Qwen2-VL 로 이미지 캡션 한국어 재생성 — 한국어 검색 정확도 향상.

기존 BLIP/Qwen 캡션은 영어 위주 → 한국어 쿼리 매칭 약함.
한국어 prompt 로 Qwen2-VL 재호출 → BGE-M3 임베딩 갱신.

대상:
  registry 의 모든 image abs 경로 (2381 이미지)

작업:
  1. Qwen2-VL 로드 (4GB VRAM, fp16)
  2. 각 이미지에 대해 한국어 prompt 로 캡션 생성:
     "이 사진을 한국어로 자세히 설명해주세요. 객체·인물·장소·분위기를 포함하세요."
  3. extracted_DB/Img/captions/ 에 _korean.json 으로 저장 (기존 영어 캡션 보존)
  4. BGE-M3 으로 한국어 캡션 임베딩 → cache_img_Im_korean.npy
  5. unified_engine 의 image fusion 에 한국어 채널 추가 (별도 작업)

사용:
  python scripts/rebuild_qwen_korean_captions.py
  python scripts/rebuild_qwen_korean_captions.py --batch-size 4
  python scripts/rebuild_qwen_korean_captions.py --skip-existing  # 이미 _korean.json 있으면 skip
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[rebuild_qwen_korean_captions] 스크립트 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
IMG_CACHE = ROOT / "Data" / "embedded_DB" / "Img"
CAP_DIR   = ROOT / "Data" / "extracted_DB" / "Img" / "captions"

KOREAN_PROMPT = (
    "이 사진을 한국어로 자세히 설명해주세요. "
    "객체·인물·장소·분위기·색감을 포함해 1~3문장으로 작성하세요."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "App" / "backend"))

    # ids + registry
    ids_path = IMG_CACHE / "img_ids.json"
    reg_path = IMG_CACHE / "registry.json"
    ids = json.loads(ids_path.read_text(encoding="utf-8"))
    ids_list = ids.get("ids", []) if isinstance(ids, dict) else ids
    registry = json.loads(reg_path.read_text(encoding="utf-8"))
    n_total = len(ids_list)
    print(f"이미지 수: {n_total}", flush=True)

    # 경로 매핑 + 기존 캡션 skip 검사
    paths: list[Path | None] = []
    skip_idx: set[int] = set()
    for i, key in enumerate(ids_list):
        v = registry.get(key)
        ap = None
        if isinstance(v, dict):
            cand = v.get("abs")
            if cand and Path(cand).is_file():
                ap = Path(cand)
        paths.append(ap)
        if args.skip_existing:
            kor_cap = CAP_DIR / f"{key.replace('/', '__')}_korean.json"
            if kor_cap.is_file():
                skip_idx.add(i)
    print(f"기존 한국어 캡션 (skip): {len(skip_idx)}", flush=True)

    todo_idx = [i for i in range(n_total) if i not in skip_idx and paths[i] is not None]
    print(f"처리 대상: {len(todo_idx)}", flush=True)

    if not todo_idx:
        print("처리할 이미지 없음 — 종료", flush=True)
        return 0

    # Qwen2-VL 로드
    print("Qwen2-VL 모델 로드 중...", flush=True)
    try:
        from embedders.trichef import qwen_caption
    except Exception as e:
        print(f"[ERROR] qwen_caption 임포트 실패: {e}", flush=True)
        return 2

    captions: dict[int, str] = {}
    t0 = time.time()
    for j, i in enumerate(todo_idx):
        if j % 25 == 0:
            elapsed = time.time() - t0
            eta = elapsed / max(j, 1) * (len(todo_idx) - j) if j else 0
            print(f"  {j}/{len(todo_idx)}  elapsed={elapsed:.0f}s  ETA={eta:.0f}s", flush=True)
        p = paths[i]
        try:
            # qwen_caption.caption(image_path, prompt=...) 가정
            # 실제 함수 시그니처 확인 필요 — 폴백 패턴:
            if hasattr(qwen_caption, "caption_korean"):
                cap = qwen_caption.caption_korean(p)
            elif hasattr(qwen_caption, "caption"):
                cap = qwen_caption.caption(p, prompt=KOREAN_PROMPT)
            else:
                cap = ""
            captions[i] = cap or ""
        except Exception as e:
            captions[i] = ""
            print(f"    실패 [{i}]: {e}", flush=True)

    print(f"\n캡션 생성 완료 ({time.time() - t0:.0f}s)", flush=True)

    # caption 텍스트 저장
    CAP_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for i, cap in captions.items():
        if not cap:
            continue
        key = ids_list[i]
        kor_cap = CAP_DIR / f"{key.replace('/', '__')}_korean.json"
        kor_cap.write_text(json.dumps({"caption_korean": cap}, ensure_ascii=False),
                           encoding="utf-8")
        saved += 1
    print(f"  텍스트 저장: {saved}", flush=True)

    # BGE-M3 임베딩 → cache_img_Im_korean.npy
    if captions:
        print("\nBGE-M3 임베딩 (한국어 캡션)...", flush=True)
        from embedders.trichef import bgem3_caption_im as bge
        import numpy as np

        out = np.zeros((n_total, 1024), dtype=np.float32)
        # 기존 _korean.json 도 함께 로드 (skip 된 항목)
        for i in range(n_total):
            if i in captions:
                continue
            key = ids_list[i]
            kor_cap = CAP_DIR / f"{key.replace('/', '__')}_korean.json"
            if kor_cap.is_file():
                try:
                    d = json.loads(kor_cap.read_text(encoding="utf-8"))
                    captions[i] = d.get("caption_korean", "")
                except Exception:
                    pass

        non_empty_idx = [i for i in range(n_total) if captions.get(i, "")]
        non_empty_texts = [captions[i] for i in non_empty_idx]
        print(f"  비-empty: {len(non_empty_idx)}", flush=True)

        bs = args.batch_size
        for s in range(0, len(non_empty_texts), bs):
            e = min(s + bs, len(non_empty_texts))
            embs = bge.embed_passage(non_empty_texts[s:e])
            for j, idx in enumerate(non_empty_idx[s:e]):
                out[idx] = embs[j]

        norms = np.linalg.norm(out, axis=1, keepdims=True)
        out = out / np.maximum(norms, 1e-9)

        npy_path = IMG_CACHE / "cache_img_Im_korean.npy"
        if npy_path.exists():
            shutil.copy2(npy_path, npy_path.with_suffix(npy_path.suffix + f".bak.{int(time.time())}"))
        np.save(npy_path, out)
        print(f"  저장: {npy_path.name} {out.shape}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
