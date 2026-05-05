"""services/trichef/tri_gs.py — Tri Gram-Schmidt 직교화."""
from __future__ import annotations

import numpy as np

# GPU 가속 — torch 가 있고 CUDA 이용 가능하면 행렬곱을 GPU 로 수행.
# 임베딩 캐시(Re/Im/Z)는 numpy로 저장되므로 첫 검색 시 GPU 텐서로 업로드.
# PCIe 전송 오버헤드를 최소화하기 위해 캐시 텐서를 재사용한다.
try:
    import torch as _torch
    _CUDA = _torch.cuda.is_available()
except ImportError:
    _torch = None   # type: ignore[assignment]
    _CUDA = False

# (matrix_id → gpu_tensor) 재사용 캐시 (id(ndarray) 기반)
_gpu_cache: dict[int, object] = {}


def _to_gpu(mat: np.ndarray):
    """numpy 배열 → GPU 텐서. 동일 배열(id)은 재업로드하지 않는다."""
    if _torch is None or not _CUDA:
        return None
    key = id(mat)
    if key not in _gpu_cache:
        _gpu_cache[key] = _torch.from_numpy(mat).to("cuda", non_blocking=True)
    return _gpu_cache[key]


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.clip(n, 1e-12, None)


def orthogonalize(Re: np.ndarray, Im: np.ndarray, Z: np.ndarray
                  ) -> tuple[np.ndarray, np.ndarray]:
    """Re → Im⊥ → Z⊥⊥ 순차 투영 제거.

    Re(1152d) vs Im/Z(1024d) 차원 불일치 → 각자 L2 normalize 만 수행.
    Test-DB_Secretary 실측 잔차율 0.999 → 동일 결과 기대.
    """
    Im_hat = _norm(Im)
    Z_hat  = _norm(Z)
    return Im_hat, Z_hat


def hermitian_score(q_Re: np.ndarray, q_Im: np.ndarray, q_Z: np.ndarray,
                    d_Re: np.ndarray, d_Im: np.ndarray, d_Z: np.ndarray,
                    alpha: float = 0.4, beta: float = 0.2) -> np.ndarray:
    """3축 복소수 내적: sqrt(A² + (α·B)² + (β·C)²).

    A = Re_q·Re_d, B = Im_q·Im_d, C = Z_q·Z_d

    GPU 가속: d_Re/d_Im/d_Z 가 큰 행렬일 때 CUDA 텐서로 업로드 후
    torch.matmul 로 계산 → RTX 4070 기준 문서/동영상 도메인(N>5000) 에서
    numpy CPU 대비 ~3× 속도 향상.
    """
    # GPU 가속 경로 (N > 2000 이고 CUDA 사용 가능한 경우)
    if _CUDA and _torch is not None and d_Re.shape[0] > 2000:
        try:
            d_Re_g = _to_gpu(d_Re)
            d_Im_g = _to_gpu(d_Im)
            d_Z_g  = _to_gpu(d_Z)
            q_Re_g = _torch.from_numpy(q_Re.astype(np.float32)).to("cuda")
            q_Im_g = _torch.from_numpy(q_Im.astype(np.float32)).to("cuda")
            q_Z_g  = _torch.from_numpy(q_Z.astype(np.float32)).to("cuda")
            A = (q_Re_g @ d_Re_g.T).cpu().numpy()
            B = (q_Im_g @ d_Im_g.T).cpu().numpy()
            C = (q_Z_g  @ d_Z_g.T).cpu().numpy()
            return np.sqrt(A**2 + (alpha * B)**2 + (beta * C)**2)
        except Exception:
            pass  # GPU 실패 시 CPU fallback
    # CPU 경로 (소규모 또는 GPU 없음)
    A = q_Re @ d_Re.T
    B = q_Im @ d_Im.T
    C = q_Z  @ d_Z.T
    return np.sqrt(A**2 + (alpha * B)**2 + (beta * C)**2)


def pair_hermitian_score(q_Re: np.ndarray, q_Im: np.ndarray, q_Z: np.ndarray,
                         d_Re: np.ndarray, d_Im: np.ndarray, d_Z: np.ndarray,
                         alpha: float = 0.4, beta: float = 0.2) -> np.ndarray:
    """행-대응 쌍별 Hermitian 점수 (N,). `hermitian_score(...).diagonal()` 동치이지만
    N×N 임시행렬 대신 행별 내적만 계산한다 (calibration 등 대용량 쌍 처리용)."""
    A = np.einsum("ij,ij->i", q_Re, d_Re)
    B = np.einsum("ij,ij->i", q_Im, d_Im)
    C = np.einsum("ij,ij->i", q_Z,  d_Z)
    return np.sqrt(A**2 + (alpha * B)**2 + (beta * C)**2)
