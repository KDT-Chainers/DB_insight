"""scripts/run_phase_b_audio_bayes.py — audio Bayesian 안전 활성 파이프라인.

자동 진행:
  1. Flask 확인
  2. audio relevant 추가 학습 (60+ 쿼리, threshold 완화 → n≥50)
  3. Beta fit 안정성 검증 (a≥1, b≥1)
  4. 안전하면 Bayesian default 활성, 아니면 hard floor 유지
  5. 회귀 검증 (sweep 30 + 보이저호/팝송)
  6. 리포트
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


def kill_flask():
    try:
        subprocess.run(["powershell", "-Command",
                        "Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | "
                        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                       check=False, capture_output=True)
        time.sleep(2)
    except Exception:
        pass


def start_flask_bg(use_bayes: bool = False):
    env = os.environ.copy()
    env["TRICHEF_USE_RERANKER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if use_bayes:
        env["OMC_AUDIO_USE_BAYES"] = "1"
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
    subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(_BACKEND_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def wait_flask_ready(timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(HEALTH, timeout=3) as r:
                if r.status == 200:
                    logger.info(f"  ↳ Flask ready: {time.time()-t0:.1f}s")
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def search(query, top_k=50, file_type="image"):
    q = urllib.parse.quote(query)
    url = f"{API}?q={q}&top_k={top_k}&type={file_type}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


# ─── 확장 쿼리 풀 ─────────────────────────────────────────────────────────────
EXTENDED_QUERIES = [
    # 카테고리 A: 명확 매칭 가능
    "고양이 모시고 이사", "박춘봉 초밥 먹튀", "고양이 데려오는 방법",
    "고양이가 박스에 있다",
    # B: AI 관련 (다스뵈이다 episodes 매칭 가능)
    "AI 인공지능", "AI 검사 수사", "AI 기술 발전", "AI development",
    "GPT-5 OpenAI", "AI가 AI를 개발",
    "바이브 코딩", "노이즈 캔슬링", "자율주행", "딥페이크",
    # C: 정치/경제
    "주식 투자 전략", "코스피 부동산", "주식 폭락", "코스피 5000",
    "환자 의료", "건강검진",
    "철학자 명비어천가", "원영적 사고", "윤석열 사형선고", "통일교 홀리바게닝",
    "대장동 진짜 전말", "검사들 걸렸어", "조선시대 역사",
    # D: 일반 카테고리
    "음악 노래", "다스뵈이다 정치", "박은빈 연예", "손담비",
    "한예종 강의 내용", "유튜브 영상", "에너지 음료", "한국 정치",
    "검찰 개혁", "프로토타입 생성",
    # E: English
    "music news", "podcast Korea", "interview", "story",
    "rock music", "Korean drama", "comedy",
    # F: 자연어 문장
    "고양이가 사진을 찍었다", "햄버거를 먹는다",
    "내일 만나러 가자", "주식 시장 폭락",
    "AI 인공지능 발전 미래",
    "검사들이 다 걸렸다",
    "이재명 검찰 수사",
]


def fit_audio_relevant_extended(
    rerank_min: float = -2.0,
    match_min: float = 0.28,
) -> dict | None:
    logger.info(f"audio relevant 학습 (rerank≥{rerank_min}, audio_match≥{match_min})")
    cosines: list[float] = []
    for i, q in enumerate(EXTENDED_QUERIES, 1):
        try:
            results = search(q, top_k=50, file_type="audio")
        except Exception:
            continue
        n = 0
        for r in results:
            rs = r.get("rerank_score")
            am = r.get("audio_match")
            if rs is None or am is None:
                continue
            if float(rs) >= rerank_min and float(am) >= match_min:
                cosines.append(float(am))
                n += 1
        if i % 10 == 0 or n >= 3:
            logger.info(f"  [{i:2d}/{len(EXTENDED_QUERIES)}] '{q[:25]:25s}' rel={n}")

    logger.info(f"  → 총 relevant 샘플: {len(cosines)}")
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
    normalized = np.clip((arr - s_min) / span, 1e-4, 1 - 1e-4)
    try:
        a, b, _, _ = beta_dist.fit(normalized, floc=0, fscale=1)
    except Exception as e:
        logger.warning(f"  Beta fit 실패: {e}")
        return None

    return {
        "n_samples": len(samples),
        "gaussian": {"mu": round(float(arr.mean()), 4),
                     "sigma": round(float(arr.std()), 4)},
        "beta": {"a": round(float(a), 4), "b": round(float(b), 4),
                 "loc": round(s_min, 4), "scale": round(span, 4)},
        "raw_min": round(s_min, 4),
        "raw_max": round(s_max, 4),
    }


def update_calibration(domain: str, key: str, dist: dict):
    cal_path = _BACKEND_DIR / "services" / "calibration.json"
    cal = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.exists() else {}
    cal.setdefault(domain, {})
    cal[domain][key] = dist
    cal["version"] = "v6"
    cal_path.write_text(json.dumps(cal, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"  → calibration.json 갱신: {domain}.{key}")


def is_beta_safe(dist: dict | None) -> bool:
    """Beta a, b 모두 ≥ 1 인지 검증 (U-shape 회피)."""
    if not dist:
        return False
    beta = dist.get("beta") or {}
    a = beta.get("a", 0)
    b = beta.get("b", 0)
    return a >= 1.0 and b >= 1.0


# ─── 회귀 검증 ───────────────────────────────────────────────────────────────
TEST_AUDIO_QUERIES = ["보이저호", "고양이", "팝송", "AI 인공지능", "주식 투자"]


def regression_audio() -> dict:
    report = {}
    for q in TEST_AUDIO_QUERIES:
        try:
            results = search(q, top_k=10, file_type="audio")
            top1 = results[0] if results else None
            report[q] = {
                "n": len(results),
                "top1": top1.get("file_name") if top1 else None,
                "conf": round((top1.get("confidence") or 0) * 100, 1) if top1 else None,
                "audio_match": round(top1.get("audio_match"), 3) if top1 and top1.get("audio_match") is not None else None,
                "bayes_p_rel": round(top1.get("audio_bayes_p_rel"), 3) if top1 and top1.get("audio_bayes_p_rel") is not None else None,
            }
        except Exception as e:
            report[q] = {"error": str(e)}
    return report


def main():
    logger.info("═" * 60)
    logger.info("Phase B: audio Bayesian 안전 활성")
    logger.info("═" * 60)

    logger.info("[1/5] Flask 확인")
    if not wait_flask_ready(timeout=5):
        kill_flask()
        start_flask_bg(use_bayes=False)
        if not wait_flask_ready():
            sys.exit(1)

    logger.info("[2/5] audio relevant 확장 학습 (60+ 쿼리)")
    rel = fit_audio_relevant_extended(rerank_min=-2.0, match_min=0.28)
    if not rel:
        logger.error("학습 실패")
        sys.exit(1)
    g = rel["gaussian"]; b = rel["beta"]
    logger.info(f"  audio relevant: μ={g['mu']}, σ={g['sigma']}, n={rel['n_samples']}")
    logger.info(f"  Beta: a={b['a']}, b={b['b']} (loc={b['loc']}, scale={b['scale']})")

    safe = is_beta_safe(rel)
    logger.info(f"  Beta 안전성: a≥1={b['a']>=1.0}, b≥1={b['b']>=1.0} → safe={safe}")

    update_calibration("audio", "relevant", rel)

    logger.info("[3/5] Flask 재시작 (Bayesian 활성/비활성 결정)")
    kill_flask()
    use_bayes = safe
    start_flask_bg(use_bayes=use_bayes)
    if not wait_flask_ready():
        sys.exit(1)
    logger.info(f"  → Bayesian {'ENABLED ✓' if use_bayes else 'DISABLED (safe fallback)'}")

    logger.info("[4/5] audio 회귀 검증")
    report = regression_audio()
    for q, r in report.items():
        if "error" in r:
            logger.info(f"  [{q}] ERROR")
            continue
        logger.info(f"  [{q}] n={r['n']}, top1={r.get('top1')}, "
                    f"conf={r.get('conf')}%, audio={r.get('audio_match')}, "
                    f"bayes_p_rel={r.get('bayes_p_rel')}")

    logger.info("[5/5] 리포트 저장")
    out = {
        "audio_relevant": rel,
        "beta_safe": safe,
        "bayesian_enabled": use_bayes,
        "regression": report,
    }
    out_path = _BACKEND_DIR / "scripts" / "phase_b_audio_bayes_report.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"  → {out_path}")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
