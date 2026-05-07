"""scripts/run_overnight_pipeline.py — 오버나이트 종합 점검·개선 파이프라인.

자동 sequential 실행 (~7~9h):
  Phase 1 (~2h): calibration 강화 — image/audio/doc/bgm relevant 재학습
  Phase 2 (~2h): 캡션 거짓말 전수 검사 — 전체 이미지 SigLIP2 시각-캡션 일치도
  Phase 3 (~2h): n_sigma 도메인별 sweep — 최적 임계치 자동 탐색
  Phase 4 (~1h): latency baseline — 100 쿼리 × 5 도메인 응답 시간
  Phase 5 (~30m): 분포 시각화 — matplotlib Beta/Gaussian 그래프
  Phase 6 (~1~2h): audio segment 분석 — STT 매칭 정확도
  Phase BGM (~1h): BGM 도메인 전용 점검 — 카테고리별 매칭 평가

사용:
  cd App/backend
  python scripts/run_overnight_pipeline.py [--skip-phase N]

산출물:
  scripts/overnight_report.json — 전체 결과 통합
  scripts/caption_mismatch_suspects.json — 거짓 캡션 의심 파일
  scripts/latency_baseline.json — 응답 시간 baseline
  scripts/calibration_distributions.png — 분포 시각화
  scripts/bgm_evaluation.json — BGM 카테고리별 평가
"""
from __future__ import annotations

import argparse
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


# ─── Flask 관리 ──────────────────────────────────────────────────────────────
def kill_flask():
    try:
        subprocess.run(["powershell", "-Command",
                        "Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | "
                        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                       check=False, capture_output=True)
        time.sleep(2)
    except Exception:
        pass


def start_flask_bg():
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
    with urllib.request.urlopen(url, timeout=90) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


# ─── Phase 1: Calibration 강화 ───────────────────────────────────────────────
DIVERSE_QUERIES_BY_DOMAIN = {
    "image": [
        "고양이", "강아지", "토끼", "기린", "말", "닭",
        "햄버거", "피자", "초밥", "케이크",
        "자동차", "비행기", "자전거", "선박", "로봇",
        "산", "바다", "강", "꽃", "노을",
        "운동하는 사람", "공부하는 학생", "요리사",
        "도시 야경", "공원", "박물관",
        "박스 안 고양이", "노을 지는 해변", "벚꽃 거리",
        "cat", "dog", "modern building", "vintage car",
    ],
    "audio": [
        "고양이 모시고", "박춘봉 초밥",
        "AI 인공지능", "GPT OpenAI", "AI 검사 수사",
        "주식 투자", "코스피", "부동산",
        "음악", "다스뵈이다", "철학자", "윤석열",
        "자율주행", "딥페이크", "유튜브",
        "한예종", "정치 뉴스", "검찰 개혁",
    ],
    "doc": [
        "AI 인공지능", "주식 부동산", "환경 정책",
        "경제 정책", "교육 개혁", "범죄 데이터",
        "농촌 토지", "자전거길", "공간 데이터",
        "보고서", "기술 발전",
    ],
    "bgm": [
        # BGM 적합 — 음악적 표현
        "잔잔한 음악", "신나는 비트", "슬픈 발라드",
        "재즈 피아노", "록 기타", "클래식 음악",
        "빠른 템포", "느린 음악",
        "soft jazz", "fast rock", "ambient electronic",
        "upbeat pop", "chill lofi", "dramatic orchestral",
        "여름 해변 음악", "카페 음악", "운동 음악",
    ],
}


def fit_relevant_for_domain(domain: str, file_type: str, match_field: str,
                             rerank_min: float, match_min: float) -> dict | None:
    queries = DIVERSE_QUERIES_BY_DOMAIN.get(domain, [])
    cosines = []
    for q in queries:
        try:
            results = search(q, top_k=50, file_type=file_type)
        except Exception:
            continue
        for r in results:
            rs = r.get("rerank_score")
            mv = r.get(match_field) or r.get("dense")
            if rs is None or mv is None:
                continue
            if float(rs) >= rerank_min and float(mv) >= match_min:
                cosines.append(float(mv))
    logger.info(f"  [{domain}] relevant n={len(cosines)}")
    return _fit_beta(cosines) if len(cosines) >= 5 else None


def _fit_beta(samples):
    import numpy as np
    from scipy.stats import beta as beta_dist
    arr = np.asarray(samples, dtype=np.float64)
    s_min, s_max = float(arr.min()), float(arr.max())
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
        }
    except Exception:
        return None


def phase1_calibration_strengthen():
    logger.info("═ Phase 1: Calibration 강화 ═")
    results = {}
    # image — visual_match 기반, 더 엄격한 threshold
    results["image"] = fit_relevant_for_domain("image", "image", "visual_match",
                                                rerank_min=0.0, match_min=0.10)
    # audio — 더 엄격 (Phase B 학습 — outlier 회피)
    results["audio"] = fit_relevant_for_domain("audio", "audio", "audio_match",
                                                rerank_min=0.5, match_min=0.32)
    # doc — dense 기반
    results["doc"] = fit_relevant_for_domain("doc", "doc", "dense",
                                              rerank_min=0.0, match_min=0.65)
    return results


# ─── Phase 2: 캡션 거짓말 전수 검사 ──────────────────────────────────────────
def phase2_caption_mismatch():
    logger.info("═ Phase 2: 캡션 거짓말 전수 검사 ═")
    try:
        import numpy as np
        from config import PATHS
        from embedders.trichef import siglip2_re

        idir = Path(PATHS["TRICHEF_IMG_CACHE"])
        img_emb = np.load(str(idir / "cache_img_Re_siglip2.npy"))
        norms = np.linalg.norm(img_emb, axis=1, keepdims=True)
        img_emb = (img_emb / np.maximum(norms, 1e-8)).astype(np.float32, copy=False)
        ids_data = json.loads((idir / "img_ids.json").read_text(encoding="utf-8"))
        ids = ids_data.get("ids") if isinstance(ids_data, dict) else ids_data
        N = len(ids)
        logger.info(f"  이미지: {N}개")

        captions_path = idir / "caption_3stage.json"
        if not captions_path.exists():
            logger.warning(f"  caption_3stage.json 없음 — skip")
            return None
        captions = json.loads(captions_path.read_text(encoding="utf-8"))

        # caption_3stage.json 구조: {"ids": [...], "L1": [...], "L2": [...], "L3": [...]}
        # 평행 리스트 형식 — index 기반 매핑
        cap_ids = captions.get("ids", [])
        L1_list = captions.get("L1", [])
        L2_list = captions.get("L2", [])
        L3_list = captions.get("L3", [])
        cap_dict = {}
        for j, cid in enumerate(cap_ids):
            l1 = L1_list[j] if j < len(L1_list) else ""
            l2 = L2_list[j] if j < len(L2_list) else ""
            l3 = L3_list[j] if j < len(L3_list) else ""
            cap = (str(l1) + " " + str(l2) + " " + str(l3)).strip()
            cap_dict[cid] = cap if cap else "(no caption)"

        suspects = []
        batch = 64
        for batch_start in range(0, N, batch):
            batch_ids = ids[batch_start: batch_start + batch]
            batch_caps = [cap_dict.get(_id, "(no caption)") for _id in batch_ids]

            try:
                txt_emb = siglip2_re.embed_texts(batch_caps)
                txt_emb = np.asarray(txt_emb, dtype=np.float32)
                norms2 = np.linalg.norm(txt_emb, axis=1, keepdims=True)
                txt_emb = txt_emb / np.maximum(norms2, 1e-8)
            except Exception:
                continue

            img_batch = img_emb[batch_start: batch_start + batch]
            cos = np.einsum("ij,ij->i", img_batch, txt_emb)
            for k, (_id, cap, c) in enumerate(zip(batch_ids, batch_caps, cos)):
                if c < 0.05:
                    suspects.append({"id": _id, "caption": cap[:120], "cosine": float(c)})
            if batch_start % 320 == 0:
                logger.info(f"  진행: {batch_start}/{N}, 의심 {len(suspects)}건")

        suspects.sort(key=lambda x: x["cosine"])
        logger.info(f"  → 거짓 캡션 의심 {len(suspects)}건 (cosine < 0.05)")
        return {"n_total": N, "n_suspects": len(suspects), "suspects": suspects[:200]}
    except Exception as e:
        logger.exception(f"  실패: {e}")
        return None


# ─── Phase 3: n_sigma sweep ──────────────────────────────────────────────────
N_SIGMA_VALUES = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
TEST_QUERIES_PER_DOMAIN = {
    "image": ["고양이", "햄버거", "박스 속에 들어있는 고양이", "팝송", "보이저호"],
    "audio": ["보이저호", "고양이", "팝송", "AI 인공지능"],
    "doc":   ["AI 인공지능", "보이저호", "주식 부동산"],
    "bgm":   ["잔잔한 음악", "신나는 비트", "보이저호", "고양이"],
}


def phase3_n_sigma_sweep():
    logger.info("═ Phase 3: n_sigma 도메인별 sweep ═")
    results = {}
    for domain, queries in TEST_QUERIES_PER_DOMAIN.items():
        domain_results = {}
        for n in N_SIGMA_VALUES:
            env_var = f"OMC_{'VISUAL' if domain == 'image' else 'AUDIO'}_N_SIGMA"
            os.environ[env_var] = str(n)
            kill_flask()
            start_flask_bg()
            if not wait_flask_ready():
                continue
            n_results = {}
            for q in queries:
                try:
                    file_type = "image" if domain == "image" else domain
                    res = search(q, top_k=10, file_type=file_type)
                    n_results[q] = {
                        "n": len(res),
                        "top1_conf": round((res[0].get("confidence") or 0) * 100, 1) if res else None,
                    }
                except Exception:
                    pass
            domain_results[f"n_{n}"] = n_results
        results[domain] = domain_results
        logger.info(f"  [{domain}] {N_SIGMA_VALUES} sweep 완료")
    # cleanup env vars
    for v in ["OMC_VISUAL_N_SIGMA", "OMC_AUDIO_N_SIGMA"]:
        os.environ.pop(v, None)
    return results


# ─── Phase 4: Latency baseline ───────────────────────────────────────────────
LATENCY_QUERIES = [
    "고양이", "햄버거", "박스 속에 들어있는 고양이", "팝송", "보이저호",
    "AI 인공지능", "주식 투자", "다스뵈이다", "잔잔한 음악", "재즈 피아노",
    "vintage car", "modern building", "soft jazz", "rock guitar",
    "공원", "도시 야경", "벚꽃", "노을", "산",
]


def phase4_latency_baseline():
    logger.info("═ Phase 4: Latency baseline ═")
    kill_flask(); start_flask_bg(); wait_flask_ready()
    results = {}
    for ftype in ["image", "doc", "video", "audio", "bgm"]:
        elapsed = []
        for q in LATENCY_QUERIES:
            t0 = time.time()
            try:
                _ = search(q, top_k=20, file_type=ftype)
                elapsed.append(time.time() - t0)
            except Exception:
                pass
        if elapsed:
            import numpy as np
            arr = np.asarray(elapsed)
            results[ftype] = {
                "n": len(arr),
                "mean_s": round(float(arr.mean()), 3),
                "median_s": round(float(np.median(arr)), 3),
                "p95_s": round(float(np.percentile(arr, 95)), 3),
                "max_s": round(float(arr.max()), 3),
            }
            logger.info(f"  [{ftype}] mean={results[ftype]['mean_s']}s, "
                        f"p95={results[ftype]['p95_s']}s")
    return results


# ─── Phase 5: 분포 시각화 ────────────────────────────────────────────────────
def phase5_visualization():
    logger.info("═ Phase 5: 분포 시각화 ═")
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from scipy.stats import beta as beta_dist

        # [한글 폰트 패치] Windows 의 Malgun Gothic 사용 (없으면 영문 fallback)
        for font_name in ["Malgun Gothic", "NanumGothic", "AppleGothic", "Arial Unicode MS"]:
            try:
                plt.rcParams["font.family"] = font_name
                plt.rcParams["axes.unicode_minus"] = False
                break
            except Exception:
                continue

        cal_path = _BACKEND_DIR / "services" / "calibration.json"
        cal = json.loads(cal_path.read_text(encoding="utf-8"))

        domains = ["image", "audio", "doc", "bgm"]
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        axes = axes.flatten()

        for idx, dom in enumerate(domains):
            ax = axes[idx]
            d = cal.get(dom, {})
            irr = d.get("irrelevant") or d
            rel = d.get("relevant")

            x = np.linspace(-0.2, 0.5, 500)

            # irrelevant Beta
            irr_beta = irr.get("beta")
            if irr_beta:
                pdf = beta_dist.pdf(x, irr_beta["a"], irr_beta["b"],
                                     loc=irr_beta["loc"], scale=irr_beta["scale"])
                ax.plot(x, pdf, label=f"noise n={irr.get('n_samples', '?'):,}",
                        color="red", alpha=0.7)
            # relevant Beta
            if rel:
                rel_beta = rel.get("beta")
                if rel_beta:
                    pdf_r = beta_dist.pdf(x, rel_beta["a"], rel_beta["b"],
                                           loc=rel_beta["loc"], scale=rel_beta["scale"])
                    ax.plot(x, pdf_r, label=f"relevant n={rel.get('n_samples', '?')}",
                            color="green", alpha=0.7)

            ax.set_title(f"{dom} 도메인 분포")
            ax.set_xlabel("raw cosine")
            ax.set_ylabel("pdf")
            ax.legend()
            ax.grid(True, alpha=0.3)

        plt.tight_layout()
        out_path = _BACKEND_DIR / "scripts" / "calibration_distributions.png"
        plt.savefig(str(out_path), dpi=120)
        plt.close()
        logger.info(f"  → {out_path}")
        return {"path": str(out_path)}
    except Exception as e:
        logger.exception(f"  실패: {e}")
        return None


# ─── Phase 6: audio segment 분석 ─────────────────────────────────────────────
def phase6_audio_segment_analysis():
    logger.info("═ Phase 6: audio segment 분석 ═")
    queries = ["보이저호", "고양이 모시고", "AI 인공지능", "팝송", "주식"]
    results = {}
    for q in queries:
        try:
            res = search(q, top_k=5, file_type="audio")
            if not res:
                continue
            top = res[0]
            segs = top.get("segments", [])[:5]
            results[q] = {
                "top1_file": top.get("file_name"),
                "audio_match": round(top.get("audio_match") or 0, 3) if top.get("audio_match") is not None else None,
                "n_segments_returned": len(segs),
                "segment_score_mean": round(sum(s.get("score", 0) for s in segs) / max(len(segs), 1), 3),
            }
        except Exception:
            pass
    return results


# ─── Phase BGM 전용 ──────────────────────────────────────────────────────────
BGM_CATEGORIES = {
    "분위기": ["잔잔한 음악", "신나는 비트", "슬픈 발라드", "긴장감 있는 음악"],
    "장르": ["재즈 음악", "록 기타", "클래식 피아노", "EDM"],
    "악기": ["기타 솔로", "피아노 연주", "드럼 비트"],
    "템포": ["빠른 템포", "느린 음악"],
    "상황": ["영화 OST", "운동 음악", "카페 음악", "잘 때 듣는 음악"],
    "영문": ["soft jazz", "fast rock", "ambient electronic", "chill lofi", "dramatic orchestral"],
    "복합": ["여름 해변에서 듣는 음악", "비 오는 날 카페", "긴장감 있는 추격 장면"],
    "무관": ["고양이", "AI 인공지능", "주식 투자", "보이저호"],
}


def phase_bgm_evaluation():
    logger.info("═ Phase BGM: 카테고리별 평가 ═")
    results = {}
    for category, queries in BGM_CATEGORIES.items():
        cat_results = []
        for q in queries:
            try:
                res = search(q, top_k=5, file_type="bgm")
                top1 = res[0] if res else None
                cat_results.append({
                    "query": q,
                    "n": len(res),
                    "top1": top1.get("file_name") if top1 else None,
                    "top1_conf": round((top1.get("confidence") or 0) * 100, 1) if top1 else None,
                    "top1_dense": round((top1.get("dense") or 0) * 100, 1) if top1 else None,
                })
            except Exception:
                pass
        results[category] = cat_results
        logger.info(f"  [{category}] {len(queries)}쿼리: 평균 결과 수 "
                    f"{sum(c['n'] for c in cat_results) / max(len(cat_results), 1):.1f}")
    return results


# ─── 메인 ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-phase", action="append", default=[],
                        help="Skip Phase N (반복 가능)")
    args = parser.parse_args()
    skip = set(args.skip_phase)

    logger.info("═" * 60)
    logger.info("OVERNIGHT 통합 점검·개선 파이프라인 시작")
    logger.info("═" * 60)

    if not wait_flask_ready(timeout=5):
        kill_flask(); start_flask_bg()
        if not wait_flask_ready():
            sys.exit(1)

    full_report = {"start": time.strftime("%Y-%m-%d %H:%M:%S")}

    if "1" not in skip:
        full_report["phase1_calibration"] = phase1_calibration_strengthen()
    if "2" not in skip:
        suspects = phase2_caption_mismatch()
        if suspects:
            (Path(__file__).parent / "caption_mismatch_suspects.json").write_text(
                json.dumps(suspects, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        full_report["phase2_caption_mismatch_summary"] = {
            "n_total": suspects.get("n_total") if suspects else 0,
            "n_suspects": suspects.get("n_suspects") if suspects else 0,
        } if suspects else None
    if "3" not in skip:
        full_report["phase3_n_sigma_sweep"] = phase3_n_sigma_sweep()
    if "4" not in skip:
        latency = phase4_latency_baseline()
        full_report["phase4_latency"] = latency
        (Path(__file__).parent / "latency_baseline.json").write_text(
            json.dumps(latency, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if "5" not in skip:
        full_report["phase5_visualization"] = phase5_visualization()
    if "6" not in skip:
        full_report["phase6_audio_segments"] = phase6_audio_segment_analysis()
    if "bgm" not in skip:
        bgm_eval = phase_bgm_evaluation()
        full_report["phase_bgm"] = bgm_eval
        (Path(__file__).parent / "bgm_evaluation.json").write_text(
            json.dumps(bgm_eval, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    full_report["end"] = time.strftime("%Y-%m-%d %H:%M:%S")
    out_path = Path(__file__).parent / "overnight_report.json"
    out_path.write_text(json.dumps(full_report, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    logger.info("═" * 60)
    logger.info(f"완료. 통합 리포트: {out_path}")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
