"""bgm_calibrate.py — BGM CLAP text→audio null 분포 측정 + calibration.json 갱신.

목적:
  CLAP 텍스트 인코더로 쿼리를 인코딩 후 오디오 인덱스에서 얻는 cosine 점수의
  null distribution (μ_null, σ_null)을 측정.
  → z-score CDF 기반 confidence 계산의 기준선.

방법:
  1. 음악과 무관한 다양한 텍스트 쿼리 N개 → CLAP text encode
  2. 각 쿼리 × 전체 BGM 트랙 cosine 점수 분포 → all_scores 집합
  3. mean, std, p95 계산 → calibration.json 저장

사용:
  cd App/backend
  python bin/bgm_calibrate.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.bgm import bgm_config
from services.bgm.clap_encoder import encode_text, _ensure_loaded as clap_load
from services.bgm import index_store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── 보정 쿼리 목록 ────────────────────────────────────────────────────────────
# 음악/BGM 과 무관한 쿼리 → null 분포 (낮게 유지되어야 함)
_NULL_QUERIES = [
    # 일반 뉴스·보도
    "breaking news tonight live coverage",
    "election results presidential vote",
    "stock market crash financial crisis",
    "weather forecast rain tomorrow",
    "traffic accident highway blocked",
    "government policy announcement press conference",
    "sports game final score basketball",
    "technology product launch new phone",
    "celebrity interview movie premiere",
    "cooking recipe pasta instructions",
    # 한국어 비음악 쿼리
    "오늘 날씨 맑음 최고기온",
    "국회의원 선거 개표 결과",
    "주식시장 코스피 하락 장세",
    "교통사고 고속도로 통제",
    "대통령 기자회견 정책 발표",
    "축구 경기 골 득점 결과",
    "신제품 스마트폰 출시 발표",
    "요리 레시피 파스타 만들기",
    "과학 연구 논문 발표 결과",
    "부동산 아파트 가격 상승",
    # 랜덤 잡다한 쿼리
    "dog barking in the morning",
    "car engine noise repair shop",
    "children playing in the park",
    "office meeting conference call",
    "airport announcement gate boarding",
    "restaurant noise crowd talking",
    "rain sound thunder storm",
    "bird chirping morning nature",
    "crowd chanting stadium",
    "keyboard typing computer office",
    # 중간: 약간 음악 관련이지만 너무 구체적
    "live concert performance audience",
    "music video shooting behind the scenes",
    "radio DJ talking between songs",
    "podcast interview conversation",
    "karaoke singing off-key party",
]

# ── 음악 관련 쿼리 (positive reference — null 위에 있어야 함) ──────────────
_POS_QUERIES = [
    "calm relaxing piano background music",
    "upbeat energetic dance pop music",
    "dark cinematic dramatic orchestral",
    "soft soothing ambient background",
    "jazz swing smooth background music",
    "fast tempo action intense music",
    "slow romantic emotional ballad",
    "bright cheerful happy background",
    "mysterious dark ambient mood",
    "rhythmic percussive driving beat",
    "잔잔한 피아노 배경음악",
    "신나는 업비트 댄스 음악",
    "어두운 영화적 배경음악",
    "부드럽고 편안한 배경음",
    "빠르고 강렬한 액션 음악",
]


def run_calibration() -> None:
    t0 = time.time()

    # 인덱스 로드
    audio_index = index_store.load_index(bgm_config.CLAP_INDEX_PATH)
    if audio_index is None:
        logger.error("CLAP audio index not found. Run bgm_ingest.py first.")
        sys.exit(1)

    n_tracks = audio_index.ntotal
    logger.info(f"audio index: {n_tracks} tracks")

    # CLAP 로드
    logger.info("CLAP 로드 중...")
    clap_load()

    # ── null 분포 측정 ─────────────────────────────────────────────────────
    logger.info(f"null 쿼리 인코딩 ({len(_NULL_QUERIES)}개)...")
    null_vecs = encode_text(_NULL_QUERIES)  # (N, 512)

    # 각 쿼리 × 전체 트랙 cosine 점수
    null_scores: list[float] = []
    for i, q_vec in enumerate(null_vecs):
        s_arr, i_arr = index_store.search(audio_index, q_vec, n_tracks)
        null_scores.extend(s_arr.tolist())

    arr_null = np.array(null_scores, dtype=np.float32)
    mu_null    = float(np.mean(arr_null))
    sigma_null = float(np.std(arr_null))
    p95_null   = float(np.percentile(arr_null, 95))
    logger.info(f"null 분포: μ={mu_null:.4f}  σ={sigma_null:.4f}  p95={p95_null:.4f}")

    # ── positive reference 측정 ────────────────────────────────────────────
    logger.info(f"positive 쿼리 인코딩 ({len(_POS_QUERIES)}개)...")
    pos_vecs = encode_text(_POS_QUERIES)
    pos_top1: list[float] = []
    for q_vec in pos_vecs:
        s_arr, _ = index_store.search(audio_index, q_vec, 1)
        if len(s_arr) > 0:
            pos_top1.append(float(s_arr[0]))

    arr_pos = np.array(pos_top1, dtype=np.float32)
    mu_pos    = float(np.mean(arr_pos))
    sigma_pos = float(np.std(arr_pos))
    logger.info(f"positive top-1 분포: μ={mu_pos:.4f}  σ={sigma_pos:.4f}")

    # separation check
    sep = (mu_pos - mu_null) / max(sigma_null, 1e-6)
    logger.info(f"분리도 (Cohen's d 근사): {sep:.2f}σ  (>2.0 권장)")

    # abs_threshold = null p95 (95th percentile of null → conf ~87%)
    abs_threshold = p95_null

    cal = {
        "mu_null":        mu_null,
        "sigma_null":     sigma_null,
        "abs_threshold":  abs_threshold,
        "mu_pos":         mu_pos,
        "sigma_pos":      sigma_pos,
        "separation_d":   float(sep),
        "n_null_queries": len(_NULL_QUERIES),
        "n_null_scores":  len(null_scores),
        "method":         "clap_text_query_x_audio_track",
    }

    cal_path = bgm_config.INDEX_DIR / "calibration.json"
    cal_path.write_text(json.dumps(cal, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"calibration.json 저장: {cal_path}")
    logger.info(f"총 소요: {time.time()-t0:.1f}s")

    # 예시 confidence 출력
    import math
    def phi(z: float) -> float:
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    logger.info("\n=== 점수 → confidence 매핑 ===")
    for score in [mu_null, p95_null, mu_pos - sigma_pos, mu_pos, mu_pos + sigma_pos]:
        z    = (score - mu_null) / max(sigma_null, 1e-6)
        conf = phi(z)
        logger.info(f"  score={score:.4f}  z={z:+.2f}  conf={conf:.3f}")


if __name__ == "__main__":
    run_calibration()
