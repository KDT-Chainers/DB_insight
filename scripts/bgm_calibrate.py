"""BGM null distribution 생성 — 다른 도메인과 동일한 통계 normalize 위함.

방법:
  무관 쿼리 30개 × 102 트랙 + 939 segment = 3060+9390 cosine 쌍의
  μ, σ 계산. 도메인 무관 percentile (Φ) 매핑 가능.

산출:
  Data/embedded_DB/Bgm/calibration.json
    {
      "mu_null":      <float>,
      "sigma_null":   <float>,
      "abs_threshold": <float>,    # μ + 3σ (강한 매칭 임계)
      "n_pairs":      <int>,
      "method":       "clap_random_query_x_track",
    }
"""
from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ["FORCE_CPU"] = "1"
os.environ["OMC_DISABLE_QWEN_PREWARM"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# 다양한 무관 쿼리 — 음원 도메인과 직접 매칭 안 되는 임의 텍스트
RANDOM_QUERIES = [
    "abc 123 xyz random",
    "the quick brown fox jumps over",
    "lorem ipsum dolor sit amet",
    "랜덤 한국어 문장 테스트",
    "오늘 날씨가 어떻습니까",
    "@@@ ### $$$ %%%",
    "hello world",
    "blah blah blah",
    "this is a sentence",
    "테스트 문장 입니다",
    "computer keyboard mouse monitor",
    "1234567890 0987654321",
    "very long unrelated query text that should not match anything specific in the music database",
    "단순한 테스트 텍스트",
    "음원과 무관한 일상 표현",
    "office printer document",
    "철수와 영희가 학교에 갔다",
    "today tomorrow yesterday",
    "코딩 개발 프로그래밍",
    "vegetable fruit dinner",
    "주말 약속 영화관 카페",
    "API server database",
    "기차역 지하철 버스 정류장",
    "alpha beta gamma delta",
    "도서관 대출 반납 책",
    "weather forecast tomorrow",
    "감사합니다 안녕히 가세요",
    "system error log debug",
    "겨울 봄 여름 가을",
    "scrolling up and down",
]


def main():
    print("[bgm_calibrate] 시작", flush=True)
    t0 = time.time()

    import numpy as np
    from services.bgm import bgm_config, clap_encoder, segments as bgm_seg

    # 인덱스 로드
    if not bgm_config.CLAP_EMB_PATH.is_file():
        print(f"[ERROR] clap_emb.npy 없음 — 먼저 ingest 필요", flush=True)
        return 2
    clap_emb = np.load(bgm_config.CLAP_EMB_PATH)
    seg_emb_path = bgm_seg.SEG_EMB_PATH
    seg_emb = np.load(seg_emb_path) if seg_emb_path.is_file() else None
    print(f"  file-level: {clap_emb.shape}", flush=True)
    print(f"  segment   : {seg_emb.shape if seg_emb is not None else '(없음)'}", flush=True)

    # 쿼리 임베딩
    print(f"\n  무관 쿼리 {len(RANDOM_QUERIES)}개 → CLAP text 임베딩...", flush=True)
    q_emb = clap_encoder.encode_text(RANDOM_QUERIES)  # (N, 512)
    print(f"  쿼리 벡터 shape: {q_emb.shape}", flush=True)

    # cosine = inner product (이미 L2-normalized)
    print(f"\n  cosine 매트릭스 계산...", flush=True)
    sims_file = (q_emb @ clap_emb.T).flatten()  # (N * 102,)
    print(f"  file-level: {sims_file.shape[0]} 쌍, "
          f"min={sims_file.min():.4f} max={sims_file.max():.4f}", flush=True)

    sims_seg = None
    if seg_emb is not None:
        sims_seg = (q_emb @ seg_emb.T).flatten()
        print(f"  segment   : {sims_seg.shape[0]} 쌍, "
              f"min={sims_seg.min():.4f} max={sims_seg.max():.4f}", flush=True)

    # μ, σ 계산 (file + segment 통합 — 두 쌍 모두 동일 매핑 사용)
    if sims_seg is not None:
        all_sims = np.concatenate([sims_file, sims_seg])
    else:
        all_sims = sims_file

    mu = float(np.mean(all_sims))
    sigma = float(np.std(all_sims))
    abs_thr = mu + 3 * sigma

    print(f"\n=== Null distribution ===", flush=True)
    print(f"  μ_null:        {mu:.4f}", flush=True)
    print(f"  σ_null:        {sigma:.4f}", flush=True)
    print(f"  abs_threshold: {abs_thr:.4f}  (μ + 3σ — 강한 매칭 컷오프)", flush=True)
    print(f"  n_pairs:       {len(all_sims)}", flush=True)

    # 저장
    out = {
        "mu_null":         round(mu, 6),
        "sigma_null":      round(sigma, 6),
        "abs_threshold":   round(abs_thr, 6),
        "n_pairs":         int(len(all_sims)),
        "n_queries":       len(RANDOM_QUERIES),
        "method":          "clap_random_query_x_track_segment",
        "calibrated_at":   datetime.now(timezone.utc).isoformat(),
        "elapsed_sec":     round(time.time() - t0, 2),
    }
    cal_path = bgm_config.INDEX_DIR / "calibration.json"
    cal_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  저장: {cal_path}", flush=True)

    # 동작 시연 — 강한 매칭 (현재 잘 동작하는 쿼리) 점수 변환
    print(f"\n=== 통합 매핑 시연 ===", flush=True)
    test_queries = ["잔잔한 피아노", "신나는 댄스 음악", "classical orchestra"]
    for q in test_queries:
        qv = clap_encoder.encode_text([q])[0]
        # 모든 트랙과 매칭
        s = (clap_emb @ qv)
        top_score = float(s.max())
        old_pct = (0.5 + 0.5 * top_score) * 100  # 기존
        z = (top_score - mu) / max(sigma, 1e-6)
        from math import erf, sqrt
        new_pct = (0.5 * (1 + erf(z / sqrt(2)))) * 100
        print(f"  '{q}'", flush=True)
        print(f"    top cosine: {top_score:.4f}", flush=True)
        print(f"    Before (단순):     {old_pct:.1f}%", flush=True)
        print(f"    After  (z-score):  {new_pct:.1f}%   z={z:.2f}σ", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
