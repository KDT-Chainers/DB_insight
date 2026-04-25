"""fuse_img_caption_triple.py — L1/L2/L3 캡션 임베딩 stand-alone fusion 산출물.

[NOTE] 실제 검색 경로에서는 이 스크립트 산출물을 사용하지 않습니다.
`App/backend/services/trichef/unified_engine.py:108-132` 가 L1/L2/L3 .npy 가
모두 존재할 때 동일한 가중치 합산을 자동 수행합니다(런타임 fusion).
이 스크립트는 다음 보조 용도로만 유지됩니다:
  • 분석/디버깅: 정적 fusion 결과를 numpy 로 직접 검사
  • 외부 도구 연동: backend 의존 없이 cache_img_Im.npy 산출물 필요 시
  • α 가중치 sweep 실험: 다른 α 조합의 결과를 빠르게 비교

build_img_caption_triple.py 가 저장한 세 개의 level별 .npy 파일을 불러와
가중치 합산(fusion) 후 L2 정규화하여 cache_img_Im.npy 로 덮어씁니다.

가중치 (App/backend/config.py TRICHEF_CFG):
  L1(짧은 주제): IMG_IM_L1_ALPHA = 0.15
  L2(키워드):   IMG_IM_L2_ALPHA = 0.25
  L3(상세 묘사): IMG_IM_L3_ALPHA = 0.60  (합 = 1.00)

출력:
  Data/embedded_DB/Img/cache_img_Im.npy  (N, 1024) float32, L2 정규화

실행:
  python DI_TriCHEF/scripts/build_img_caption_triple.py
  python DI_TriCHEF/scripts/fuse_img_caption_triple.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "App" / "backend"))

IMG_CACHE_DIR = _root / "Data" / "embedded_DB" / "Img"

L1_PATH  = IMG_CACHE_DIR / "cache_img_Im_L1.npy"
L2_PATH  = IMG_CACHE_DIR / "cache_img_Im_L2.npy"
L3_PATH  = IMG_CACHE_DIR / "cache_img_Im_L3.npy"
OUT_PATH = IMG_CACHE_DIR / "cache_img_Im.npy"


def fuse(
    alpha1: float | None = None,
    alpha2: float | None = None,
    alpha3: float | None = None,
) -> None:
    """L1/L2/L3 .npy 파일을 가중치 합산하여 cache_img_Im.npy 덮어쓰기.

    alpha 미지정 시 App/backend/config.py 의 TRICHEF_CFG 값 사용.
    """
    # ── 가중치 로드 ──────────────────────────────────────────────────────────
    if alpha1 is None or alpha2 is None or alpha3 is None:
        try:
            from config import TRICHEF_CFG
            alpha1 = float(TRICHEF_CFG["IMG_IM_L1_ALPHA"])
            alpha2 = float(TRICHEF_CFG["IMG_IM_L2_ALPHA"])
            alpha3 = float(TRICHEF_CFG["IMG_IM_L3_ALPHA"])
        except Exception as e:
            raise RuntimeError(
                f"[fuse_img] App/backend/config.py 에서 알파값 로드 실패: {e}"
            ) from e

    total = alpha1 + alpha2 + alpha3
    assert abs(total - 1.0) < 1e-6, (
        f"가중치 합이 1.0 이 아닙니다: {alpha1}+{alpha2}+{alpha3}={total:.8f}"
    )

    # ── .npy 로드 ────────────────────────────────────────────────────────────
    for p in (L1_PATH, L2_PATH, L3_PATH):
        if not p.exists():
            raise FileNotFoundError(
                f"[fuse_img] {p} 없음 — build_img_caption_triple.py 를 먼저 실행하세요."
            )

    L1 = np.load(L1_PATH)
    L2 = np.load(L2_PATH)
    L3 = np.load(L3_PATH)

    # ── shape / N 일치 검증 ──────────────────────────────────────────────────
    if not (L1.shape == L2.shape == L3.shape):
        raise ValueError(
            f"[fuse_img] shape 불일치: L1={L1.shape}, L2={L2.shape}, L3={L3.shape}"
        )
    N, dim = L1.shape
    print(f"[fuse_img] 로드 완료 — N={N}, dim={dim}")
    print(f"[fuse_img] 가중치: L1={alpha1}, L2={alpha2}, L3={alpha3}")

    # ── 가중치 합산 + L2 정규화 ──────────────────────────────────────────────
    fused = (
        alpha1 * L1.astype(np.float64)
        + alpha2 * L2.astype(np.float64)
        + alpha3 * L3.astype(np.float64)
    )
    norms = np.linalg.norm(fused, axis=1, keepdims=True)
    near_zero = norms < 1e-12
    if near_zero.any():
        print(f"[fuse_img] WARNING: {near_zero.sum()} 행의 norm≈0 — 원점 벡터 유지")
        norms = np.where(near_zero, 1.0, norms)
    fused = (fused / norms).astype(np.float32)

    # ── 결과 저장 (덮어쓰기) ─────────────────────────────────────────────────
    np.save(OUT_PATH, fused)
    size_mb = OUT_PATH.stat().st_size / 1024 ** 2
    print(f"[fuse_img] 저장 완료: {OUT_PATH}")
    print(f"  shape={fused.shape}  ({size_mb:.1f} MB)")
    print(f"  unified_engine.py 의 cache_img_Im.npy 인터페이스와 동일 — backend 수정 불필요")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="L1/L2/L3 BGE-M3 임베딩 → 가중치 fusion → cache_img_Im.npy"
    )
    ap.add_argument("--alpha1", type=float, default=None, help="L1 가중치 (기본: config 값)")
    ap.add_argument("--alpha2", type=float, default=None, help="L2 가중치 (기본: config 값)")
    ap.add_argument("--alpha3", type=float, default=None, help="L3 가중치 (기본: config 값)")
    args = ap.parse_args()

    fuse(alpha1=args.alpha1, alpha2=args.alpha2, alpha3=args.alpha3)


if __name__ == "__main__":
    main()
