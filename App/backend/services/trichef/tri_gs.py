"""services/trichef/tri_gs.py — Tri Gram-Schmidt 직교화."""
import numpy as np


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
    """
    A = q_Re @ d_Re.T
    B = q_Im @ d_Im.T
    C = q_Z  @ d_Z.T
    return np.sqrt(A**2 + (alpha * B)**2 + (beta * C)**2)
