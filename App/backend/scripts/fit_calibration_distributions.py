"""scripts/fit_calibration_distributions.py — 도메인별 noise 분포 캘리브레이션.

가우시안 + Beta 하이브리드 confidence 계산을 위한 noise 분포 사전 학습.

목적:
  무작위 쿼리 × 무작위 이미지 pair 의 SigLIP2 cosine 분포를 학습하여
  "관련 없을 때 어떤 점수가 나오는가" 의 분포 (noise distribution) 를 얻는다.
  이 분포의 mu, sigma 또는 Beta(alpha, beta) 로 적응형 임계값 도출:
    threshold(n) = mu + n * sigma  (n ∈ {1, 1.5, 2, 2.5, 3})
  또는 Beta CDF percentile.

출력:
  App/backend/services/calibration.json

방법:
  1. 무작위 한국어 쿼리 N개 (diverse 단어/구문) 생성
  2. SigLIP2 text encoder 로 각 쿼리 임베딩
  3. 각 쿼리 vs 모든 이미지 임베딩 cosine 계산 → 행렬
  4. 모든 cosine 값 수집 → noise 분포
  5. Gaussian (mean, std) + Beta (alpha, beta, loc, scale) fit
  6. JSON 저장

사용:
  python scripts/fit_calibration_distributions.py [--n-queries 100]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

# 패키지 path 설정 — backend 디렉터리에서 실행
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from config import PATHS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ── 무작위 쿼리 풀 (한국어 다양 주제, ~120개) ─────────────────────────────────
# diversified queries: 동물 / 음식 / 사물 / 자연 / 사람 / 기술 / 추상 / 영문 등.
# 데이터셋과의 일치 가능성을 줄이기 위해 의도적으로 다양화.
_RANDOM_QUERIES = [
    # 동물 (이미지 데이터셋과 겹칠 수 있어 일부만)
    "사자", "강아지", "토끼", "기린", "코끼리", "물고기", "독수리", "거북이",
    # 음식
    "라면", "피자", "스파게티", "샌드위치", "초콜릿", "커피", "오렌지 주스",
    "아이스크림", "샐러드", "스테이크",
    # 사물/도구
    "자동차", "비행기", "기차", "자전거", "선박", "로봇", "드론", "헬리콥터",
    "망원경", "현미경", "카메라", "노트북", "키보드", "마우스",
    # 장소/풍경
    "산", "바다", "강", "호수", "숲", "사막", "도시", "공항", "지하철역",
    "학교", "병원", "박물관", "미술관", "공원",
    # 자연/날씨
    "구름", "비", "눈", "안개", "무지개", "번개", "별", "달", "태양",
    "꽃밭", "단풍", "벚꽃",
    # 사람/활동
    "달리기 선수", "축구 경기", "춤추는 사람", "그림 그리는 학생",
    "요리하는 셰프", "노래 부르는 가수", "발표하는 강사",
    # 기술/추상
    "인공지능", "블록체인", "양자컴퓨터", "DNA", "수학 공식", "프로그래밍 코드",
    "회로기판", "그래프 차트", "지도",
    # 의류/패션
    "정장", "운동화", "모자", "안경", "시계", "가방",
    # 가구/실내
    "소파", "책상", "의자", "침대", "주방", "욕실",
    # 영문 (cross-lingual)
    "vintage car", "modern building", "abstract painting", "neon lights",
    "circuit board", "ocean wave", "mountain sunset",
    # 추상 개념
    "행복", "슬픔", "평화", "혁신", "성장",
    # 액션/상황
    "회의 중인 사람들", "운동하는 모습", "독서하는 장면", "여행 가방",
    # 도형/색
    "빨간색 원", "파란색 사각형", "노란색 삼각형",
    # 길게 자연어
    "노을 지는 해변에서 책을 읽는 사람",
    "눈 내리는 도시의 밤거리",
    "정원에서 차를 마시는 가족",
]

logger.info(f"무작위 쿼리 풀 크기: {len(_RANDOM_QUERIES)}")


def _load_image_embeddings() -> tuple[np.ndarray, list[str]]:
    """이미지 SigLIP2 임베딩 + id 목록 로드 + L2 정규화."""
    idir = Path(PATHS["TRICHEF_IMG_CACHE"])
    emb_path = idir / "cache_img_Re_siglip2.npy"
    ids_path = idir / "img_ids.json"
    if not emb_path.exists() or not ids_path.exists():
        raise FileNotFoundError(f"이미지 캐시 없음: {emb_path}")

    emb = np.load(str(emb_path))
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    emb = (emb / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)

    ids_data = json.loads(ids_path.read_text(encoding="utf-8"))
    ids = ids_data.get("ids") if isinstance(ids_data, dict) else ids_data
    if not isinstance(ids, list) or len(ids) != emb.shape[0]:
        raise RuntimeError("img_ids.json 형식 또는 길이 불일치")

    logger.info(f"이미지 임베딩: shape={emb.shape}, ids={len(ids)}")
    return emb, list(ids)


def _embed_query_texts(queries: list[str]) -> np.ndarray:
    """SigLIP2 text encoder 로 다수 쿼리 임베딩 (L2 정규화)."""
    from embedders.trichef import siglip2_re
    logger.info(f"쿼리 텍스트 임베딩 중... ({len(queries)}개)")
    t0 = time.time()
    emb = siglip2_re.embed_texts(queries)
    emb = np.asarray(emb, dtype=np.float32)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    emb = emb / np.maximum(norms, 1e-8)
    logger.info(f"  ↳ shape={emb.shape}, 소요 {time.time()-t0:.1f}s")
    return emb


def _compute_cosine_matrix(query_emb: np.ndarray, img_emb: np.ndarray) -> np.ndarray:
    """(Q, D) cosine matrix — 둘 다 이미 L2 정규화 가정."""
    return query_emb @ img_emb.T  # (Q, N)


def _fit_distributions(samples: np.ndarray) -> dict:
    """샘플 vector 에 가우시안 + Beta 분포 fit."""
    from scipy.stats import beta as beta_dist

    samples = np.asarray(samples, dtype=np.float64)
    samples = samples[~np.isnan(samples)]
    n = len(samples)
    if n < 100:
        raise ValueError(f"샘플 부족 ({n}). 100개 이상 필요.")

    # Gaussian
    mu_g = float(np.mean(samples))
    sigma_g = float(np.std(samples))

    # 분위수 통계
    p = np.percentile(samples, [50, 75, 90, 95, 97.5, 99, 99.5])
    quantiles = {
        "p50": float(p[0]), "p75": float(p[1]), "p90": float(p[2]),
        "p95": float(p[3]), "p975": float(p[4]), "p99": float(p[5]), "p995": float(p[6]),
    }

    # Beta — cosine 은 [-1, 1] 이지만 실측은 보통 [-0.2, 0.4] 좁은 범위.
    # loc/scale 을 데이터 min/max 로 fix 하여 [0, 1] 로 매핑.
    s_min, s_max = float(np.min(samples)), float(np.max(samples))
    span = s_max - s_min
    if span < 1e-6:
        beta_params = None
    else:
        normalized = (samples - s_min) / span      # [0, 1]
        # 양 끝점 0/1 회피 (Beta MLE 발산 방지)
        normalized = np.clip(normalized, 1e-4, 1 - 1e-4)
        try:
            a, b, _, _ = beta_dist.fit(normalized, floc=0, fscale=1)
            beta_params = {"a": float(a), "b": float(b), "loc": s_min, "scale": span}
        except Exception as e:
            logger.warning(f"Beta fit 실패: {e}")
            beta_params = None

    # 적응형 임계값 — n × sigma 시뮬레이션
    n_sweep = [1.0, 1.5, 2.0, 2.5, 3.0]
    thresholds = {f"n_{n:.1f}": round(mu_g + n * sigma_g, 4) for n in n_sweep}

    return {
        "n_samples": n,
        "gaussian": {"mu": round(mu_g, 4), "sigma": round(sigma_g, 4)},
        "beta": beta_params,
        "quantiles": {k: round(v, 4) for k, v in quantiles.items()},
        "n_sigma_thresholds": thresholds,
        "raw_min": round(s_min, 4),
        "raw_max": round(s_max, 4),
    }


def calibrate_image_domain(n_queries: Optional[int] = None) -> dict:
    """이미지 도메인 noise 분포 캘리브레이션."""
    img_emb, ids = _load_image_embeddings()

    queries = _RANDOM_QUERIES[:n_queries] if n_queries else _RANDOM_QUERIES
    q_emb = _embed_query_texts(queries)

    logger.info("Cosine 행렬 계산 중...")
    t0 = time.time()
    cos_mat = _compute_cosine_matrix(q_emb, img_emb)  # (Q, N)
    logger.info(f"  ↳ shape={cos_mat.shape}, 소요 {time.time()-t0:.2f}s")

    # 모든 cosine 값을 noise 분포로 사용.
    # 무작위 쿼리이므로 대부분은 무관 — 일부 우연 매칭만 우측 꼬리 형성.
    # Beta 가 이 비대칭 분포를 가우시안보다 잘 모델링.
    samples = cos_mat.flatten()
    logger.info(f"총 cosine 샘플: {len(samples):,}")
    logger.info(f"  min={samples.min():.4f}, max={samples.max():.4f}, "
                f"mean={samples.mean():.4f}, std={samples.std():.4f}")

    return _fit_distributions(samples)


# ─── BGE-M3 기반 도메인 (doc / audio) ──────────────────────────────────────────
def _load_npy_with_ids(emb_path: Path, ids_path: Path) -> tuple[np.ndarray, list[str]]:
    """일반 npy + ids.json 로드 + L2 정규화."""
    if not emb_path.exists() or not ids_path.exists():
        raise FileNotFoundError(f"캐시 없음: {emb_path}")
    emb = np.load(str(emb_path))
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    emb = (emb / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)
    ids_data = json.loads(ids_path.read_text(encoding="utf-8"))
    ids = ids_data.get("ids") if isinstance(ids_data, dict) else ids_data
    if not isinstance(ids, list) or len(ids) != emb.shape[0]:
        raise RuntimeError(f"ids 형식/길이 불일치: emb={emb.shape[0]}, ids={len(ids) if isinstance(ids, list) else 'N/A'}")
    return emb, list(ids)


def _embed_query_texts_bge(queries: list[str]) -> np.ndarray:
    """BGE-M3 (e5_caption_im) text encoder 로 임베딩 (L2 정규화)."""
    from embedders.trichef import e5_caption_im
    logger.info(f"BGE-M3 쿼리 임베딩 중... ({len(queries)}개)")
    t0 = time.time()
    emb = e5_caption_im.embed_query(queries)
    emb = np.asarray(emb, dtype=np.float32)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    emb = emb / np.maximum(norms, 1e-8)
    logger.info(f"  ↳ shape={emb.shape}, 소요 {time.time()-t0:.1f}s")
    return emb


def calibrate_doc_domain(n_queries: Optional[int] = None) -> dict:
    """doc 도메인 noise 분포 — BGE-M3 (caption + body) 기준."""
    ddir = Path(PATHS["TRICHEF_DOC_CACHE"])
    # cache_doc_page_Im.npy 는 caption Im, fusion 후 alpha=0.35*caption + 0.65*body 로
    # 엔진 내부에서 결합되지만 noise 캘리브레이션은 caption Im 단독으로 충분 (둘 다 BGE-M3 공간).
    emb, ids = _load_npy_with_ids(ddir / "cache_doc_page_Im.npy",
                                   ddir / "doc_page_ids.json")
    logger.info(f"doc 임베딩: shape={emb.shape}, ids={len(ids)}")

    queries = _RANDOM_QUERIES[:n_queries] if n_queries else _RANDOM_QUERIES
    q_emb = _embed_query_texts_bge(queries)

    logger.info("Cosine 행렬 계산 중...")
    t0 = time.time()
    cos_mat = _compute_cosine_matrix(q_emb, emb)
    logger.info(f"  ↳ shape={cos_mat.shape}, 소요 {time.time()-t0:.2f}s")

    samples = cos_mat.flatten()
    logger.info(f"총 cosine 샘플: {len(samples):,}")
    logger.info(f"  min={samples.min():.4f}, max={samples.max():.4f}, "
                f"mean={samples.mean():.4f}, std={samples.std():.4f}")
    return _fit_distributions(samples)


def calibrate_audio_domain(n_queries: Optional[int] = None) -> dict:
    """audio (Rec) 도메인 noise 분포 — BGE-M3 STT segment 기준."""
    mu_path = PATHS.get("TRICHEF_MUSIC_CACHE")
    if not mu_path:
        raise FileNotFoundError("TRICHEF_MUSIC_CACHE 미설정")
    adir = Path(mu_path)
    emb, ids = _load_npy_with_ids(adir / "cache_music_Im.npy",
                                   adir / "music_ids.json")
    logger.info(f"audio 임베딩: shape={emb.shape}, ids={len(ids)}")

    queries = _RANDOM_QUERIES[:n_queries] if n_queries else _RANDOM_QUERIES
    q_emb = _embed_query_texts_bge(queries)

    logger.info("Cosine 행렬 계산 중...")
    t0 = time.time()
    cos_mat = _compute_cosine_matrix(q_emb, emb)
    logger.info(f"  ↳ shape={cos_mat.shape}, 소요 {time.time()-t0:.2f}s")

    samples = cos_mat.flatten()
    logger.info(f"총 cosine 샘플: {len(samples):,}")
    logger.info(f"  min={samples.min():.4f}, max={samples.max():.4f}, "
                f"mean={samples.mean():.4f}, std={samples.std():.4f}")
    return _fit_distributions(samples)


def _run_domain(label: str, fn, *args, **kwargs) -> Optional[dict]:
    """도메인 캘리브레이션 실행 wrapper — 실패해도 다른 도메인 계속."""
    logger.info("=" * 60)
    logger.info(f"{label} 도메인 캘리브레이션 시작")
    logger.info("=" * 60)
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.error(f"{label} 도메인 실패: {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-queries", type=int, default=None,
                        help="사용할 쿼리 수 (default: 전체)")
    parser.add_argument("--output", type=str, default=None,
                        help="출력 JSON 경로 (default: services/calibration.json)")
    parser.add_argument("--domains", type=str, default="image,doc,audio",
                        help="콤마 구분 도메인 (default: image,doc,audio)")
    args = parser.parse_args()

    out_path = Path(args.output) if args.output else (
        _BACKEND_DIR / "services" / "calibration.json"
    )
    domains = [d.strip() for d in args.domains.split(",") if d.strip()]

    # 기존 calibration.json 유지 (relevant 등 이미 학습된 데이터 보존)
    if out_path.exists():
        result = json.loads(out_path.read_text(encoding="utf-8"))
        result["version"] = "v3"
    else:
        result = {"version": "v3", "method": "random_pairs_per_domain"}

    domain_fns = {
        "image": calibrate_image_domain,
        "doc": calibrate_doc_domain,
        "audio": calibrate_audio_domain,
    }
    for dom in domains:
        if dom not in domain_fns:
            logger.warning(f"미지원 도메인 skip: {dom}")
            continue
        calib = _run_domain(dom, domain_fns[dom], n_queries=args.n_queries)
        if calib is None:
            continue
        result.setdefault(dom, {})
        # 새 noise 분포로 irrelevant 갱신 (기존 relevant 보존)
        existing_rel = result[dom].get("relevant")
        result[dom] = calib            # noise 분포 (image: 기존 위치)
        result[dom]["irrelevant"] = {
            k: v for k, v in calib.items()
            if k in ("n_samples", "gaussian", "beta", "quantiles", "raw_min", "raw_max",
                     "n_sigma_thresholds")
        }
        if existing_rel:
            result[dom]["relevant"] = existing_rel

    logger.info("=" * 60)
    logger.info("결과 요약:")
    for dom in domains:
        d = result.get(dom)
        if d and "gaussian" in d:
            logger.info(f"  [{dom}] mu={d['gaussian']['mu']}, sigma={d['gaussian']['sigma']}, "
                        f"n={d['n_samples']:,}")
    logger.info("=" * 60)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"저장: {out_path}")


def _legacy_main() -> None:
    """이전 v1 main — image 도메인만 (호환용)."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-queries", type=int, default=None)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    out_path = Path(args.output) if args.output else (
        _BACKEND_DIR / "services" / "calibration.json"
    )

    result: dict = {"version": "v1", "method": "siglip2_random_pairs"}

    logger.info("=" * 60)
    logger.info("이미지 도메인 캘리브레이션 시작")
    logger.info("=" * 60)
    img_calib = calibrate_image_domain(n_queries=args.n_queries)
    result["image"] = img_calib

    logger.info("=" * 60)
    logger.info("결과 요약 (image domain):")
    logger.info(f"  n_samples: {img_calib['n_samples']:,}")
    logger.info(f"  Gaussian: mu={img_calib['gaussian']['mu']}, "
                f"sigma={img_calib['gaussian']['sigma']}")
    if img_calib['beta']:
        logger.info(f"  Beta: a={img_calib['beta']['a']:.3f}, "
                    f"b={img_calib['beta']['b']:.3f}, "
                    f"loc={img_calib['beta']['loc']:.4f}, "
                    f"scale={img_calib['beta']['scale']:.4f}")
    logger.info("  분위수: " + str(img_calib["quantiles"]))
    logger.info("  n×σ 임계값:")
    for k, v in img_calib["n_sigma_thresholds"].items():
        logger.info(f"    {k} → {v}")
    logger.info("=" * 60)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()
