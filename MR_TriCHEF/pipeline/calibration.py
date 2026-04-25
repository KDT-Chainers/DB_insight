"""도메인별 null 분포 calibration.

무관한 쿼리 코퍼스로 각 도메인 캐시의 스코어 분포 (μ, σ, p95) 측정.
검색 시 z-score 정규화하여 도메인 간 공정 비교.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .paths import MOVIE_CACHE_DIR, MUSIC_CACHE_DIR

# 의도적으로 저장 콘텐츠와 무관한 쿼리 (null 분포 추정용)
NULL_QUERIES = [
    "날씨가 맑다",
    "자동차 엔진 수리",
    "요리 레시피 김치찌개",
    "강아지 산책",
    "주식 시장 분석",
    "커피 원두 로스팅",
    "바다 서핑 파도",
    "컴퓨터 하드웨어 조립",
    "정원 가꾸기 식물",
    "비행기 공항 출국",
    "의사 병원 진료",
    "축구 경기 결과",
    "사진 촬영 카메라",
    "책 읽기 독서",
    "휴가 여행 계획",
    "화장품 메이크업",
    "게임 콘솔 플레이",
    "건강 운동 피트니스",
    "패션 옷 쇼핑",
    "영화 관람 후기",
]

CAL_PATH = Path(__file__).resolve().parent / "_calibration.json"


def measure_domain(cache_dir: Path, kind: str, encoders: dict) -> dict:
    """도메인 캐시 전체에 null 쿼리를 던져 스코어 분포 측정."""
    import json as _json

    Re_path = cache_dir / f"cache_{kind}_Re.npy"
    Im_path = cache_dir / f"cache_{kind}_Im.npy"
    if not Re_path.exists():
        return {"status": "no_cache"}

    Re = np.load(Re_path)
    Im = np.load(Im_path) if Im_path.exists() else None
    ids_path = cache_dir / f"{kind}_ids.json"
    ids = _json.loads(ids_path.read_text(encoding="utf-8")).get("ids", []) if ids_path.exists() else []

    bge = encoders["bge"]
    sig = encoders.get("sig")

    all_scores: list[float] = []

    for q in NULL_QUERIES:
        q_bge = bge.embed([q])[0]
        if kind == "movie" and sig is not None:
            q_sig = sig.embed_texts([q])[0]
            A = Re @ q_sig
            B = Im @ q_bge if Im is not None else np.zeros_like(A)
            per_seg = np.sqrt(A**2 + (0.4 * B)**2).astype(np.float32)
        elif kind == "music" and sig is not None:
            # Music Re 축이 BGE-M3(1024) → SigLIP2-text(1152)로 전환됨.
            # Movie와 동일한 크로스모달 공식 사용.
            q_sig = sig.embed_texts([q])[0]
            A = Re @ q_sig
            B = Im @ q_bge if Im is not None else np.zeros_like(A)
            per_seg = np.sqrt(A**2 + (0.4 * B)**2).astype(np.float32)
        else:
            per_seg = (Re @ q_bge).astype(np.float32)

        # 파일별 top-3 평균 집계 (search._aggregate 와 동일 구조)
        per_file: dict[str, list[float]] = {}
        for i, rel in enumerate(ids):
            per_file.setdefault(rel, []).append(float(per_seg[i]))
        for rel, scores in per_file.items():
            top = sorted(scores, reverse=True)[:3]
            all_scores.append(float(np.mean(top)))

    arr = np.array(all_scores, dtype=np.float32)
    return {
        "status":   "ok",
        "n":        int(arr.size),
        "mu_null":  float(arr.mean()),
        "sigma_null": float(arr.std() + 1e-6),
        "p95":      float(np.percentile(arr, 95)),
        "p99":      float(np.percentile(arr, 99)),
        "max":      float(arr.max()),
    }


def calibrate_crossmodal_movie(cache_dir: Path, encoders: dict,
                                sample_q: int = 30, pairs_per_q: int = 10) -> dict:
    """Movie 전용 crossmodal calibration.

    텍스트 쿼리 → 영상 프레임 벡터 경로로 null 분포 측정.
    (calibrate_null 은 frame↔frame = 이미지끼리 비교 → mu=0.85 과도 추정)
    여기서는 NULL_QUERIES 를 SigLIP2 text encoder 로 임베딩해
    실제 검색과 동일한 텍스트→이미지 cross-modal 분포를 측정한다.
    """
    Re_path = cache_dir / "cache_movie_Re.npy"
    Im_path = cache_dir / "cache_movie_Im.npy"
    if not Re_path.exists():
        return {"status": "no_cache"}

    Re = np.load(Re_path)   # (N, 1152) SigLIP2 이미지
    Im = np.load(Im_path)   # (N, 1024) BGE-M3 STT 텍스트

    bge = encoders["bge"]
    sig = encoders["sig"]

    rng = np.random.default_rng(42)
    queries = NULL_QUERIES[:sample_q]

    all_scores: list[float] = []
    for q in queries:
        q_Re = sig.embed_texts([q])[0]   # SigLIP2 text (1152d)
        q_Im = bge.embed([q])[0]          # BGE-M3 (1024d)
        N = Re.shape[0]
        j_idx = rng.integers(0, N, pairs_per_q)
        A = Re[j_idx] @ q_Re              # (pairs_per_q,)
        B = Im[j_idx] @ q_Im
        scores = np.sqrt(A**2 + (0.4 * B)**2)
        all_scores.extend(float(s) for s in scores)

    arr = np.array(all_scores, dtype=np.float32)
    mu  = float(arr.mean())
    sig_val = float(arr.std()) + 1e-6
    # FAR=0.05 → Φ⁻¹(0.95) ≈ 1.645
    thr = mu + 1.645 * sig_val

    return {
        "status":     "ok",
        "method":     "crossmodal_v1",
        "n":          int(arr.size),
        "mu_null":    mu,
        "sigma_null": sig_val,
        "p95":        float(np.percentile(arr, 95)),
        "p99":        float(np.percentile(arr, 99)),
        "abs_threshold": thr,
        "max":        float(arr.max()),
    }


def _apply_safety_guard(new_result: dict, prev: dict) -> dict:
    """[P2A.1] App 쪽 W5-SAFETY 와 동등한 2배 드리프트 거부 장치.

    App/backend/services/trichef/calibration.py 의 가드를 MR 에 포팅.
    μ_null 또는 abs_threshold (p95 대체) 가 이전 값의 2배 이상/0.5배 이하로
    튀면 새 값을 버리고 이전 값 유지. 원인: query/reference shuffle 혹은
    캐시 부분 손상 시 분포가 극단적으로 왜곡되는 경우 자동 차단.
    """
    import logging
    log = logging.getLogger("mr.calibration")
    for dom, nd in list(new_result.items()):
        if nd.get("status") != "ok":
            continue
        od = prev.get(dom) or {}
        if od.get("status") != "ok":
            continue  # 비교 기준 없음 → 그대로 통과
        old_mu  = float(od.get("mu_null") or 0.0)
        new_mu  = float(nd.get("mu_null") or 0.0)
        old_thr = float(od.get("abs_threshold") or od.get("p95") or 0.0)
        new_thr = float(nd.get("abs_threshold") or nd.get("p95") or 0.0)

        mu_drift  = (old_mu > 0 and (new_mu > 2.0 * old_mu or new_mu < 0.5 * old_mu))
        thr_drift = (old_thr > 0 and (new_thr > 2.0 * old_thr or new_thr < 0.5 * old_thr))
        if mu_drift or thr_drift:
            log.warning(
                f"[calibration:{dom}] REJECTED — drift >2×. "
                f"old_mu={old_mu:.4f} new_mu={new_mu:.4f}  "
                f"old_thr={old_thr:.4f} new_thr={new_thr:.4f}. 이전 값 유지."
            )
            # 거부: 이전 값 유지 + 사유 기록
            new_result[dom] = {
                **od,
                "status": "ok",
                "last_rejected": {
                    "mu_null":    new_mu,
                    "abs_threshold": new_thr,
                    "reason":     "drift_>2x",
                },
            }
    return new_result


def _sync_to_shared(result: dict) -> None:
    """[P2A.2] MR → App 역방향 자동 동기화.

    MR 이 `MR_TriCHEF/pipeline/_calibration.json` 에 쓰지만, App 의
    unified_engine 은 `Data/embedded_DB/trichef_calibration.json` 에서 읽는다.
    직접 MR 경로로 recalibrate() 가 호출된 경우에도 두 파일이 일관되도록 병합.
    """
    shared = Path(__file__).resolve().parents[2] / "Data" / "embedded_DB" / "trichef_calibration.json"
    try:
        cur = json.loads(shared.read_text(encoding="utf-8")) if shared.exists() else {}
    except Exception:
        cur = {}
    for dom in ("movie", "music"):
        r = result.get(dom, {})
        if r.get("status") != "ok":
            continue
        entry = {
            "mu_null":       r.get("mu_null"),
            "sigma_null":    r.get("sigma_null"),
            "abs_threshold": r.get("abs_threshold", r.get("p95", 0.0)),
            "p95":           r.get("p95", 0.0),
            "p99":           r.get("p99", 0.0),
            "N":             r.get("n", 0),
            "method":        r.get("method",
                                    "text_text_siglip2_null_v1" if dom == "music"
                                    else "crossmodal_v1"),
        }
        if dom == "music":
            entry["note"] = ("Music Re=SigLIP2-text, same-encoder baseline high. "
                              "Do not cross-compare with cross-modal domains.")
        # 거부된 항목도 이전 값이 유지된 채로 들어오므로 안전하게 merge
        if "last_rejected" in r:
            entry["last_rejected"] = r["last_rejected"]
        cur[dom] = entry
    try:
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        import logging
        logging.getLogger("mr.calibration").warning(
            f"[calibration] shared sync 실패: {type(e).__name__}: {e}"
        )


def recalibrate() -> dict:
    """Movie + Music 모두 재측정 → json 저장.

    Movie: crossmodal_v1 (텍스트쿼리→프레임 분포)
    Music: 기존 null 분포 측정 (Re=Im=BGE-M3 이므로 동일 공간)

    [P2A.1] 2배 드리프트 거부 가드 적용.
    [P2A.2] 완료 후 App 의 trichef_calibration.json 과 자동 동기화.
    """
    from .text import BGEM3Encoder
    from .vision import SigLIP2Encoder

    prev = load()  # 비교 기준 (이전 _calibration.json)

    encoders = {"bge": BGEM3Encoder(), "sig": SigLIP2Encoder()}
    try:
        result = {
            "movie": calibrate_crossmodal_movie(MOVIE_CACHE_DIR, encoders),
            "music": measure_domain(MUSIC_CACHE_DIR, "music", encoders),
        }
    finally:
        encoders["bge"].unload()
        encoders["sig"].unload()

    # safety guard 적용
    result = _apply_safety_guard(result, prev)

    CAL_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # App trichef_calibration.json 자동 sync
    _sync_to_shared(result)

    return result


def load() -> dict:
    if CAL_PATH.exists():
        try:
            return json.loads(CAL_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def normalize(raw_score: float, domain: str, cal: dict | None = None) -> tuple[float, float]:
    """raw cos → (z_score, confidence).

    z = (raw - μ_null) / σ_null
    confidence = sigmoid(z / 2)   # z=0 → 0.5, z=2 → 0.88, z=4 → 0.98
    """
    import math
    cal = cal or load()
    d = cal.get(domain, {}) if cal else {}
    if d.get("status") != "ok":
        # fallback — 초기 상태: 원시 스코어 그대로, confidence는 sigmoid((raw-0.25)/0.08)
        return raw_score, 1.0 / (1.0 + math.exp(-(raw_score - 0.25) / 0.08))
    mu    = d["mu_null"]
    sigma = d["sigma_null"]
    z = (raw_score - mu) / sigma
    conf = 1.0 / (1.0 + math.exp(-z / 2.0))
    return z, conf
