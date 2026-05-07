"""scripts/run_phase_e_pipeline.py — Phase E-2/E-3/E-4 통합 자동 실행 파이프라인.

VS Code 터미널 한 번 실행으로 끝까지 자동 진행:
  1. 현재 Flask 종료
  2. 새 Flask spawn (TRICHEF_USE_RERANKER=1) — 백그라운드
  3. ready 대기 (~30~60s)
  4. audio relevant 분포 학습 (rerank ≥ 0 페어)
  5. doc relevant 분포 학습 (옵션)
  6. calibration.json 갱신
  7. Flask 재시작 (새 calibration 로드)
  8. 30 쿼리 sweep 실행
  9. "보이저호" 음성/문서/동영상 회귀 검증
 10. 결과 리포트 생성

사용:
  cd App/backend
  python scripts/run_phase_e_pipeline.py

참고:
  - 자동 커밋 안 함. 사용자 승인 후 수동 커밋.
  - 진행 단계마다 stdout 으로 상황 표시.
  - 중간 실패해도 가능한 부분까지 진행 후 리포트.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

API = "http://127.0.0.1:5001/api/search"
HEALTH = "http://127.0.0.1:5001/api/health"


def kill_python() -> None:
    """5001 포트 listening 프로세스만 종료 (자기 자신은 보호)."""
    try:
        subprocess.run(["powershell", "-Command",
                        "Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | "
                        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                       check=False, capture_output=True)
        time.sleep(2)
    except Exception:
        pass


def start_flask_bg() -> None:
    """Flask 를 백그라운드 spawn (env TRICHEF_USE_RERANKER=1)."""
    env = os.environ.copy()
    env["TRICHEF_USE_RERANKER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    cwd = str(_BACKEND_DIR)
    # Windows: subprocess.Popen with DETACHED_PROCESS-like behavior
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=cwd, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def wait_flask_ready(timeout: int = 120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(HEALTH, timeout=3) as r:
                if r.status == 200:
                    elapsed = time.time() - t0
                    logger.info(f"  ↳ Flask ready: {elapsed:.1f}s")
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def search(query: str, top_k: int = 50, file_type: str = "image",
           timeout: int = 60) -> list[dict]:
    q = urllib.parse.quote(query)
    url = f"{API}?q={q}&top_k={top_k}&type={file_type}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data.get("results", [])


# ─── audio relevant 분포 학습 ────────────────────────────────────────────────
AUDIO_TRAIN_QUERIES = [
    "고양이", "강아지", "햄버거", "자동차", "비행기",
    "음악", "노래", "방송", "뉴스", "라디오",
    "다스뵈이다", "정치", "경제", "요리", "여행",
    "스포츠", "축구", "야구", "건강", "교육",
    "박스 안 고양이", "햄버거 먹는 사람", "노을 지는 해변",
    "공원에서 뛰어노는 어린이", "벚꽃이 핀 거리",
    "cat", "dog", "music", "news", "sports",
    "고양이 모시고 이사", "박춘봉 초밥",
    "AI 인공지능", "주식 부동산", "의료 환자",
]


def fit_relevant_distribution(domain: str, file_type: str,
                               match_field: str,
                               rerank_threshold: float = 0.0,
                               match_floor: float = 0.25) -> dict | None:
    """rerank_score ≥ threshold 인 페어를 relevant 로 수집 + Beta fit."""
    cosines: list[float] = []
    for i, q in enumerate(AUDIO_TRAIN_QUERIES, 1):
        try:
            results = search(q, top_k=50, file_type=file_type)
        except Exception as e:
            logger.warning(f"  쿼리 '{q}' 실패: {e}")
            continue
        n_rel = 0
        for r in results:
            rs = r.get("rerank_score")
            mv = r.get(match_field)
            if rs is None or mv is None:
                continue
            if float(rs) >= rerank_threshold and float(mv) >= match_floor:
                cosines.append(float(mv))
                n_rel += 1
        logger.info(f"  [{i:2d}/{len(AUDIO_TRAIN_QUERIES)}] '{q[:25]:25s}' "
                    f"results={len(results):3d} relevant={n_rel:2d}")

    if len(cosines) < 30:
        logger.warning(f"  → relevant 샘플 부족 ({len(cosines)}). threshold 더 낮춰야 할 수 있음.")
        if not cosines:
            return None
    return _fit_beta(cosines)


def _fit_beta(samples: list[float]) -> dict | None:
    import numpy as np
    from scipy.stats import beta as beta_dist
    arr = np.asarray(samples, dtype=np.float64)
    s_min = float(arr.min())
    s_max = float(arr.max())
    span = s_max - s_min
    if span < 1e-6:
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
        }
    except Exception as e:
        logger.warning(f"  Beta fit 실패: {e}")
        return None


def update_calibration(domain: str, relevant: dict) -> None:
    cal_path = _BACKEND_DIR / "services" / "calibration.json"
    cal = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.exists() else {}
    cal.setdefault(domain, {})
    cal[domain]["relevant"] = relevant
    cal["version"] = "v3"
    cal_path.write_text(json.dumps(cal, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"  → calibration.json 갱신: {domain}.relevant")


# ─── 회귀 검증 ───────────────────────────────────────────────────────────────
TEST_QUERIES = [
    ("audio", "보이저호", "음성"),
    ("audio", "고양이", "음성"),
    ("audio", "팝송", "음성"),
    ("video", "보이저호", "동영상"),
    ("doc",   "보이저호", "문서"),
    ("image", "고양이",   "이미지"),
    ("image", "햄버거",   "이미지"),
    ("image", "박스 속에 들어있는 고양이", "이미지"),
]


def regression_test() -> dict:
    report = {}
    for ftype, q, name in TEST_QUERIES:
        try:
            results = search(q, top_k=10, file_type=ftype)
            top1 = results[0] if results else None
            report[f"{name}-{q}"] = {
                "n": len(results),
                "top1": top1.get("file_name") if top1 else None,
                "top1_conf": round((top1.get("confidence") or 0) * 100, 1) if top1 else None,
                "top1_rerank": round(top1.get("rerank_score") or 0, 2) if top1 and top1.get("rerank_score") is not None else None,
                "top1_audio_match": round(top1.get("audio_match") or 0, 3) if top1 and top1.get("audio_match") is not None else None,
                "top1_visual_match": round(top1.get("visual_match") or 0, 3) if top1 and top1.get("visual_match") is not None else None,
            }
        except Exception as e:
            report[f"{name}-{q}"] = {"error": str(e)}
    return report


# ─── 메인 파이프라인 ──────────────────────────────────────────────────────────
def main() -> None:
    logger.info("═" * 60)
    logger.info("Phase E 통합 파이프라인 시작")
    logger.info("═" * 60)

    # Step 1: Flask 종료 + 새로 spawn (audio_check 통합 search.py 로드)
    logger.info("[1/6] Flask 재시작 (audio_check 통합 search.py 로드)")
    kill_python()
    start_flask_bg()
    if not wait_flask_ready():
        logger.error("Flask 미준비 — 종료")
        sys.exit(1)

    # Step 2: audio relevant 분포 학습
    logger.info("[2/6] audio domain relevant 분포 학습 시작")
    audio_rel = fit_relevant_distribution(
        domain="audio", file_type="audio", match_field="audio_match",
        rerank_threshold=0.0, match_floor=0.25,
    )
    if audio_rel:
        logger.info(f"  audio relevant: μ={audio_rel['gaussian']['mu']}, "
                    f"σ={audio_rel['gaussian']['sigma']}, n={audio_rel['n_samples']}")
        update_calibration("audio", audio_rel)
    else:
        logger.warning("  audio relevant 학습 실패 (샘플 부족 가능) — Bayesian 비활성")

    # Step 3: Flask 재시작 (새 calibration 로드)
    logger.info("[3/6] Flask 재시작 (새 calibration 로드)")
    kill_python()
    start_flask_bg()
    if not wait_flask_ready():
        logger.error("Flask 재시작 실패 — 종료")
        sys.exit(1)

    # Step 4: 회귀 검증
    logger.info("[4/6] 회귀 검증 (8 쿼리)")
    report = regression_test()

    logger.info("\n═══ 회귀 결과 ═══")
    for k, v in report.items():
        logger.info(f"  [{k}] n={v.get('n', '?')}, top1={v.get('top1', '(none)')}, "
                    f"conf={v.get('top1_conf')}%, audio_vm={v.get('top1_audio_match')}, "
                    f"visual_vm={v.get('top1_visual_match')}, rerank={v.get('top1_rerank')}")

    # Step 5: 리포트 저장
    out_path = _BACKEND_DIR / "scripts" / "phase_e_report.json"
    out_path.write_text(
        json.dumps({"audio_relevant": audio_rel, "regression": report},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"\n[5/6] 리포트 저장: {out_path}")

    # Step 6: 요약
    logger.info("\n[6/6] 완료")
    logger.info("═" * 60)
    logger.info("주요 검증 사항:")
    voiyer_audio = report.get("음성-보이저호", {})
    logger.info(f"  - '보이저호' 음성: n={voiyer_audio.get('n')}건, "
                f"top1 conf={voiyer_audio.get('top1_conf')}%, "
                f"audio_match={voiyer_audio.get('top1_audio_match')}")
    if voiyer_audio.get("n", 0) <= 2:
        logger.info("  ✓ 음성 부풀림 차단 성공")
    else:
        logger.info("  ⚠ 음성 부풀림 잔존 — 임계치 조정 필요할 수 있음")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
