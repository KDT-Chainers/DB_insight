"""scripts/fit_relevant_distribution.py — relevant Beta 분포 학습.

Phase B: Bayesian dual-Beta confidence 를 위해 정상 매칭 페어의 분포를 학습.

전략:
  cross-encoder rerank 활성 상태에서 다양한 쿼리 검색 → rerank_score ≥ +1.0 인
  쌍을 "relevant" 로 정의 (cross-encoder 가 강한 의미 매칭 판정).
  이 페어들의 SigLIP2 raw cosine 분포를 Beta(α_rel, β_rel) 로 fit.

비교 대상:
  irrelevant 분포: 이미 calibration.json 에 학습됨 (μ=0.014, σ=0.033)
  relevant 분포:   본 스크립트가 학습 → calibration.json 에 추가

사용:
  Flask 가 활성 상태에서 실행 (rerank=on).
  python scripts/fit_relevant_distribution.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from config import PATHS  # noqa

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

API = "http://127.0.0.1:5001/api/search"

# 학습용 쿼리 — 다양 카테고리 커버. mplc_validity_sweep 보다 더 많이.
TRAINING_QUERIES = [
    # 동물
    "고양이", "강아지", "토끼", "사자", "호랑이", "코끼리", "기린", "원숭이",
    "고양이 인형", "강아지 인형", "박스 안 고양이", "잠자는 고양이",
    # 음식
    "햄버거", "피자", "초밥", "샐러드", "케이크", "샌드위치", "스테이크",
    "라면", "김치찌개", "비빔밥",
    # 사물/탈것
    "자동차", "비행기", "기차", "자전거", "오토바이", "선박", "배",
    "로봇", "드론",
    # 풍경/자연
    "바다", "산", "강", "호수", "숲", "사막", "꽃", "벚꽃",
    "노을", "일출", "구름", "비", "눈",
    # 사람/장면
    "운동하는 사람", "공부하는 학생", "요리하는 셰프", "발표하는 사람",
    "어린이", "아기", "가족",
    # 도시/장소
    "도시 야경", "공원", "카페", "박물관", "공항", "지하철역", "도서관",
    # 영문
    "cat", "dog", "hamburger", "vintage car", "modern building",
    "ocean wave", "mountain peak", "city night",
    # 자연어 문장
    "박스 속에 들어있는 고양이",
    "햄버거를 먹는 사람",
    "노을 지는 해변",
    "벚꽃이 핀 거리",
    "공원에서 뛰어노는 어린이",
    "잠자는 회색 고양이",
]


def search(query: str, top_k: int = 50, file_type: str = "image",
           timeout: int = 60) -> list[dict]:
    q = urllib.parse.quote(query)
    url = f"{API}?q={q}&top_k={top_k}&type={file_type}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data.get("results", [])


def collect_relevant_cosines(
    domain: str = "image",
    rerank_threshold: float = 0.0,
    visual_floor: float = 0.08,
    file_type: str = "image",
    match_field: str = "visual_match",
) -> tuple[list[float], list[float]]:
    """rerank_score ≥ threshold 인 페어를 relevant 로 수집.

    Args:
        rerank_threshold: rerank_score 가 이 값 이상이면 relevant 로 간주.
        visual_floor: visual_match 가 이 값 이상이면 relevant 페어에 추가.
                      (visual_check 페널티된 항목 제외)

    Returns:
        (rel_cosines, all_rerank_scores)
    """
    rel_cosines: list[float] = []
    all_reranks: list[float] = []

    for i, q in enumerate(TRAINING_QUERIES, 1):
        try:
            results = search(q, top_k=50, file_type="image")
        except Exception as e:
            logger.warning(f"  쿼리 '{q}' 실패: {e}")
            continue

        rel_for_query = 0
        for r in results:
            rs = r.get("rerank_score")
            vm = r.get("visual_match")
            if rs is None or vm is None:
                continue
            all_reranks.append(float(rs))
            # relevant 판정: rerank ≥ threshold AND visual_match ≥ floor
            if float(rs) >= rerank_threshold and float(vm) >= visual_floor:
                rel_cosines.append(float(vm))   # visual_match = SigLIP2 raw cosine
                rel_for_query += 1
        logger.info(f"  [{i:2d}/{len(TRAINING_QUERIES)}] '{q[:25]:25s}' "
                    f"results={len(results):3d}, relevant={rel_for_query:2d}")

    return rel_cosines, all_reranks


def fit_beta_distribution(samples: list[float]) -> Optional[dict]:
    """Beta(α, β) fit + 통계량 산출."""
    from scipy.stats import beta as beta_dist
    if len(samples) < 50:
        logger.warning(f"샘플 부족 ({len(samples)}). Beta fit 불가.")
        return None
    arr = np.asarray(samples, dtype=np.float64)
    s_min = float(arr.min())
    s_max = float(arr.max())
    span = s_max - s_min
    if span < 1e-6:
        logger.warning(f"샘플 범위 너무 좁음 ({s_min:.4f} ~ {s_max:.4f})")
        return None

    normalized = (arr - s_min) / span
    normalized = np.clip(normalized, 1e-4, 1 - 1e-4)
    try:
        a, b, _, _ = beta_dist.fit(normalized, floc=0, fscale=1)
        return {
            "n_samples": len(samples),
            "gaussian": {"mu": round(float(arr.mean()), 4),
                         "sigma": round(float(arr.std()), 4)},
            "beta": {"a": round(float(a), 4), "b": round(float(b), 4),
                     "loc": round(s_min, 4), "scale": round(span, 4)},
            "raw_min": round(s_min, 4),
            "raw_max": round(s_max, 4),
            "quantiles": {
                "p25": round(float(np.percentile(arr, 25)), 4),
                "p50": round(float(np.percentile(arr, 50)), 4),
                "p75": round(float(np.percentile(arr, 75)), 4),
                "p95": round(float(np.percentile(arr, 95)), 4),
            },
        }
    except Exception as e:
        logger.warning(f"Beta fit 실패: {e}")
        return None


def main() -> None:
    # API 가용성 체크
    try:
        with urllib.request.urlopen("http://127.0.0.1:5001/api/health", timeout=5) as r:
            if r.status != 200:
                raise RuntimeError("Flask not ready")
    except Exception as e:
        logger.error(f"Flask API 응답 없음: {e}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"relevant 페어 수집 시작 ({len(TRAINING_QUERIES)} 쿼리)")
    logger.info("=" * 60)

    t0 = time.time()
    rel_cosines, all_reranks = collect_relevant_cosines()
    logger.info(f"\n수집 완료 — {time.time()-t0:.1f}s")
    logger.info(f"  relevant 페어: {len(rel_cosines)}")
    logger.info(f"  전체 rerank score 범위: "
                f"min={min(all_reranks):.2f}, max={max(all_reranks):.2f}, "
                f"≥1.0: {sum(1 for r in all_reranks if r >= 1.0)}")

    if len(rel_cosines) < 50:
        logger.error(f"relevant 샘플 부족 ({len(rel_cosines)}). threshold 완화 필요.")
        sys.exit(1)

    rel_dist = fit_beta_distribution(rel_cosines)
    if not rel_dist:
        logger.error("Beta fit 실패")
        sys.exit(1)

    logger.info("\n=== relevant 분포 결과 ===")
    logger.info(f"  n_samples: {rel_dist['n_samples']}")
    logger.info(f"  Gaussian: mu={rel_dist['gaussian']['mu']}, sigma={rel_dist['gaussian']['sigma']}")
    logger.info(f"  Beta: a={rel_dist['beta']['a']}, b={rel_dist['beta']['b']}, "
                f"loc={rel_dist['beta']['loc']}, scale={rel_dist['beta']['scale']}")
    logger.info(f"  Quantiles: {rel_dist['quantiles']}")

    # calibration.json 에 추가
    cal_path = Path(__file__).parent.parent / "services" / "calibration.json"
    if cal_path.exists():
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
    else:
        cal = {"version": "v2"}
    cal.setdefault("image", {})
    cal["image"]["relevant"] = rel_dist
    # 기존 noise 분포는 image[gaussian/beta/...] 에 저장됨 → "irrelevant" 키로 명시 이동
    if "irrelevant" not in cal["image"] and "gaussian" in cal["image"]:
        cal["image"]["irrelevant"] = {
            k: v for k, v in cal["image"].items()
            if k in ("n_samples", "gaussian", "beta", "quantiles", "raw_min", "raw_max",
                     "n_sigma_thresholds")
        }
    cal["version"] = "v2"
    cal_path.write_text(json.dumps(cal, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"\n저장: {cal_path}")


if __name__ == "__main__":
    main()
