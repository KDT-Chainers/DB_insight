"""scripts/run_phase_f1_e3_pipeline.py — Phase F-1 + E-3 통합 자동 실행.

자동 진행:
  1. Flask 재시작 (audio n=3.5σ 적용)
  2. F-1: audio relevant 재학습 (threshold 완화 → n≥30 확보)
  3. bgm 캘리브레이션 (E-3) — CLAP 임베딩 noise 분포
  4. bgm_check 활성 후 Flask 재시작
  5. 회귀 검증 (보이저호 음성/BGM/이미지/동영상/문서)
  6. 리포트 저장

사용:
  cd App/backend
  python scripts/run_phase_f1_e3_pipeline.py
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


def kill_flask() -> None:
    try:
        subprocess.run(["powershell", "-Command",
                        "Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | "
                        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                       check=False, capture_output=True)
        time.sleep(2)
    except Exception:
        pass


def start_flask_bg() -> None:
    env = os.environ.copy()
    env["TRICHEF_USE_RERANKER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
    subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(_BACKEND_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def wait_flask_ready(timeout: int = 120) -> bool:
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


def search(query: str, top_k: int = 50, file_type: str = "image",
           timeout: int = 60) -> list[dict]:
    q = urllib.parse.quote(query)
    url = f"{API}?q={q}&top_k={top_k}&type={file_type}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


# ─── audio relevant 재학습 (F-1) ──────────────────────────────────────────────
AUDIO_QUERIES = [
    "고양이 모시고 이사", "박춘봉 초밥 먹튀",
    "AI 인공지능", "자율주행", "노이즈 캔슬링",
    "바이브 코딩", "유튜브 영상", "에너지 음료",
    "환자 의료", "코스피 부동산",
    "음악 노래", "다스뵈이다 정치",
    "자동차 비행기", "야구 축구",
    "박은빈 연예", "손담비",
    # English
    "music news", "AI development",
    "podcast Korea", "interview", "story",
    # 자연어
    "고양이 데려오는 방법",
    "주식 투자 전략",
    "AI 기술 발전",
]


def fit_audio_relevant() -> dict | None:
    """audio relevant 재학습 — threshold 완화로 n≥30 확보."""
    logger.info("[F-1] audio relevant 재학습 (threshold 완화)")
    cosines: list[float] = []
    # 더 관대한 threshold: rerank ≥ -1.0, audio_match ≥ 0.30
    for i, q in enumerate(AUDIO_QUERIES, 1):
        try:
            results = search(q, top_k=50, file_type="audio")
        except Exception as e:
            logger.warning(f"  '{q}' 실패: {e}")
            continue
        n_rel = 0
        for r in results:
            rs = r.get("rerank_score")
            am = r.get("audio_match")
            if rs is None or am is None:
                continue
            if float(rs) >= -1.0 and float(am) >= 0.30:
                cosines.append(float(am))
                n_rel += 1
        logger.info(f"  [{i:2d}/{len(AUDIO_QUERIES)}] '{q[:25]:25s}' rel={n_rel}")

    logger.info(f"  → 총 relevant 샘플: {len(cosines)}")
    if len(cosines) < 20:
        logger.warning("  ⚠ 샘플 매우 부족 — Bayesian fit 신뢰도 낮음")
    return _fit_beta(cosines) if cosines else None


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


# ─── bgm 캘리브레이션 (E-3) ───────────────────────────────────────────────────
def calibrate_bgm() -> dict | None:
    """BGM noise 분포 학습 — CLAP text encoder 사용."""
    logger.info("[E-3] BGM 캘리브레이션 시작")
    try:
        from config import PATHS
        import numpy as np

        bgm_cache = PATHS.get("BGM_CACHE") or (Path(PATHS["RAW_DB"]).parent / "embedded_DB" / "Bgm")
        bdir = Path(bgm_cache)
        clap_path = bdir / "clap_emb.npy"
        text_path = bdir / "text_emb.npy"
        if not clap_path.exists():
            logger.warning(f"  CLAP 임베딩 없음: {clap_path}")
            return None

        clap_emb = np.load(str(clap_path))
        norms = np.linalg.norm(clap_emb, axis=1, keepdims=True)
        clap_emb = (clap_emb / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)
        logger.info(f"  CLAP 임베딩: shape={clap_emb.shape}")

        # CLAP text encoder 로 무작위 쿼리 임베딩
        try:
            from services.bgm.clap_encoder import encode_text
        except Exception as e:
            logger.warning(f"  CLAP text encoder 로드 실패: {e}")
            return None

        random_queries = [
            "잔잔한 음악", "신나는 비트", "슬픈 발라드", "록 음악", "재즈",
            "고양이", "강아지", "햄버거", "자동차", "비행기",
            "행복", "슬픔", "평화", "전쟁",
            "사람 목소리", "기타 솔로", "피아노 연주",
            "happy music", "sad piano", "rock guitar", "soft jazz",
            "fast tempo", "slow ballad",
            # 자연어
            "여름 해변에서 듣는 음악",
            "비 오는 날 카페에서 듣는 음악",
        ]
        logger.info(f"  무작위 쿼리: {len(random_queries)}")
        try:
            txt_emb = encode_text(random_queries)
        except Exception as e:
            logger.warning(f"  CLAP encode_text 실패: {e}")
            return None
        txt_emb = np.asarray(txt_emb, dtype=np.float32)
        norms = np.linalg.norm(txt_emb, axis=1, keepdims=True)
        txt_emb = txt_emb / np.maximum(norms, 1e-8)
        logger.info(f"  쿼리 임베딩: shape={txt_emb.shape}")

        # cosine matrix
        cos_mat = txt_emb @ clap_emb.T
        samples = cos_mat.flatten()
        logger.info(f"  총 cosine 샘플: {len(samples):,}")
        logger.info(f"    min={samples.min():.4f}, max={samples.max():.4f}, "
                    f"mean={samples.mean():.4f}, std={samples.std():.4f}")
        return _fit_beta(samples.tolist())
    except Exception as e:
        logger.exception(f"  BGM 캘리브레이션 실패: {e}")
        return None


# ─── 회귀 검증 ───────────────────────────────────────────────────────────────
TEST_QUERIES = [
    ("audio", "보이저호", "음성"),
    ("audio", "고양이", "음성"),
    ("audio", "팝송", "음성"),
    ("bgm",   "보이저호", "BGM"),
    ("bgm",   "팝송",     "BGM"),
    ("video", "보이저호", "동영상"),
    ("doc",   "보이저호", "문서"),
    ("image", "고양이",   "이미지"),
]


def regression_test() -> dict:
    report = {}
    for ft, q, name in TEST_QUERIES:
        try:
            results = search(q, top_k=10, file_type=ft)
            top1 = results[0] if results else None
            report[f"{name}-{q}"] = {
                "n": len(results),
                "top1": top1.get("file_name") if top1 else None,
                "top1_conf": round((top1.get("confidence") or 0) * 100, 1) if top1 else None,
                "top1_audio_match": round(top1.get("audio_match"), 3) if top1 and top1.get("audio_match") is not None else None,
                "top1_visual_match": round(top1.get("visual_match"), 3) if top1 and top1.get("visual_match") is not None else None,
                "top1_dense": round(top1.get("dense") * 100, 1) if top1 and top1.get("dense") is not None else None,
            }
        except Exception as e:
            report[f"{name}-{q}"] = {"error": str(e)}
    return report


# ─── 메인 파이프라인 ──────────────────────────────────────────────────────────
def update_calibration(domain: str, key: str, dist: dict) -> None:
    cal_path = _BACKEND_DIR / "services" / "calibration.json"
    cal = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.exists() else {}
    cal.setdefault(domain, {})
    cal[domain][key] = dist
    cal["version"] = "v4"
    cal_path.write_text(json.dumps(cal, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"  → calibration.json 갱신: {domain}.{key}")


def main() -> None:
    logger.info("═" * 60)
    logger.info("Phase F-1 + E-3 통합 파이프라인 시작")
    logger.info("═" * 60)

    logger.info("[1/5] Flask 재시작 (audio n=3.5σ 적용)")
    kill_flask()
    start_flask_bg()
    if not wait_flask_ready():
        logger.error("Flask 미준비 — 종료")
        sys.exit(1)

    logger.info("[2/5] F-1: audio relevant 재학습")
    audio_rel = fit_audio_relevant()
    if audio_rel:
        logger.info(f"  audio relevant: μ={audio_rel['gaussian']['mu']}, "
                    f"σ={audio_rel['gaussian']['sigma']}, n={audio_rel['n_samples']}")
        update_calibration("audio", "relevant", audio_rel)
    else:
        logger.warning("  audio relevant 학습 skip")

    logger.info("[3/5] E-3: BGM 캘리브레이션")
    bgm_irr = calibrate_bgm()
    if bgm_irr:
        logger.info(f"  bgm noise: μ={bgm_irr['gaussian']['mu']}, "
                    f"σ={bgm_irr['gaussian']['sigma']}, n={bgm_irr['n_samples']:,}")
        update_calibration("bgm", "irrelevant", bgm_irr)
    else:
        logger.warning("  BGM 캘리브레이션 skip (CLAP 모듈 / 캐시 이슈)")

    logger.info("[4/5] Flask 재시작 (새 calibration 로드)")
    kill_flask()
    start_flask_bg()
    if not wait_flask_ready():
        logger.error("Flask 재시작 실패 — 종료")
        sys.exit(1)

    logger.info("[5/5] 회귀 검증")
    report = regression_test()

    logger.info("\n═══ 회귀 결과 ═══")
    for k, v in report.items():
        if "error" in v:
            logger.info(f"  [{k}] ERROR: {v['error']}")
            continue
        logger.info(f"  [{k}] n={v['n']}, top1={v.get('top1')}, "
                    f"conf={v.get('top1_conf')}%, dense={v.get('top1_dense')}%, "
                    f"audio={v.get('top1_audio_match')}, visual={v.get('top1_visual_match')}")

    out_path = _BACKEND_DIR / "scripts" / "phase_f1_e3_report.json"
    out_path.write_text(
        json.dumps({"audio_relevant": audio_rel, "bgm_irrelevant": bgm_irr, "regression": report},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"\n리포트 저장: {out_path}")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
