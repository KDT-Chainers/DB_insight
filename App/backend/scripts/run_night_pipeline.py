"""scripts/run_night_pipeline.py — 통합 오버나이트 검증 파이프라인 (A~G).

읽기·검증 전용 — 데이터/calibration 변경 없음. 안전한 자동 실행 (~5~6h).

  A. 기존 5개 파이프라인 재실행 (~1h)
     overnight → next_improvement → v2_improvements → caption_lies_by_category
     → caption_quality
  B. 확장 회귀 — 200+ 쿼리 × 5 도메인 (~2h)
  C. n_sigma 정밀 sweep — n=0.5 ~ 5.0, step 0.5 (~1.5h)
  D. 도메인별 relevant 표본 강화 (n≥50 목표) 측정 (~1h)
  E. BGM 정밀 평가 — top1 file path × cosine 분포 (~30m)
  F. 캡션 거짓 클러스터 분석 — 키워드 빈도/공기어 (~30m)
  G. 한글 시각화 — 도메인별 분포 + 회귀 결과 PNG (~15m)

산출물 (scripts/night_v2/):
  overnight_v2_report.json, extended_regression.json, n_sigma_precision.json,
  relevant_strength.json, bgm_precision.json, caption_clusters.json,
  visualizations/*.png, night_v2_summary.md

사용:
  cd App/backend
  python scripts/run_night_pipeline.py [--skip A,B,...]
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
from collections import Counter, defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = _BACKEND_DIR / "scripts"
OUT_DIR = SCRIPTS_DIR / "night_v2"
VIZ_DIR = OUT_DIR / "visualizations"
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


def start_flask_bg(extra_env: dict | None = None):
    env = os.environ.copy()
    env["TRICHEF_USE_RERANKER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})
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
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def search(query, top_k=20, file_type="image"):
    q = urllib.parse.quote(query)
    url = f"{API}?q={q}&top_k={top_k}&type={file_type}"
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


def ensure_flask():
    if wait_flask_ready(timeout=5):
        return
    kill_flask()
    start_flask_bg()
    if not wait_flask_ready():
        logger.error("Flask 기동 실패")
        sys.exit(1)


# ─── A. 기존 파이프라인 재실행 ────────────────────────────────────────────────
def step_A_existing_pipelines() -> dict:
    logger.info("═" * 60)
    logger.info("[A] 기존 5개 파이프라인 재실행")
    logger.info("═" * 60)
    pipelines = [
        "run_overnight_pipeline.py",
        "run_next_improvement_pipeline.py",
        "run_v2_improvements.py",
        "extract_caption_lies_by_category.py",
        "run_caption_quality_pipeline.py",
    ]
    results = {}
    for name in pipelines:
        path = SCRIPTS_DIR / name
        if not path.exists():
            logger.warning(f"  skip {name} (없음)")
            results[name] = {"status": "missing"}
            continue
        t0 = time.time()
        logger.info(f"  ▶ {name}")
        try:
            r = subprocess.run([sys.executable, str(path)], cwd=str(_BACKEND_DIR),
                               check=False, capture_output=False)
            results[name] = {"status": "ok" if r.returncode == 0 else "fail",
                             "exit": r.returncode, "elapsed_s": round(time.time() - t0, 1)}
        except Exception as e:
            results[name] = {"status": "exception", "error": str(e)}
        logger.info(f"  ↳ {name} 완료 ({results[name]})")
    return results


# ─── B. 확장 회귀 ────────────────────────────────────────────────────────────
EXTENDED_QUERIES = {
    "image": [
        "고양이", "강아지", "토끼", "기린", "말", "닭", "새", "물고기", "곰", "여우",
        "햄버거", "피자", "초밥", "케이크", "떡볶이", "파스타", "샐러드", "스테이크",
        "자동차", "비행기", "자전거", "선박", "기차", "오토바이",
        "산", "바다", "강", "꽃", "노을", "구름", "눈", "비",
        "운동하는 사람", "공부하는 학생", "요리사", "의사", "교사",
        "도시 야경", "공원", "박물관", "교회", "사원",
        "박스 안 고양이", "노을 지는 해변", "벚꽃 거리", "눈 덮인 산",
        "cat", "dog", "modern building", "vintage car", "sunset beach",
        "팝송", "보이저호", "양자컴퓨터", "추상 개념", "외계인",  # 무관
    ],
    "doc": [
        "AI 인공지능", "주식 투자", "부동산", "환경 정책", "교육 개혁",
        "범죄 데이터", "농촌 토지", "자전거길", "공간 데이터", "보고서",
        "기술 발전", "코스피", "GDP", "에너지", "원전",
        "고양이", "햄버거", "벚꽃",  # 도메인 무관
    ],
    "video": [
        "고양이", "강아지", "요리", "운동", "여행",
        "AI 인공지능", "음악", "춤", "게임", "뉴스",
        "팝송", "보이저호",  # 무관
    ],
    "audio": [
        "고양이 모시고", "박춘봉 초밥", "AI 인공지능", "GPT OpenAI",
        "주식 투자", "코스피", "다스뵈이다", "철학자", "윤석열",
        "자율주행", "딥페이크", "한예종", "검찰 개혁",
        "팝송", "보이저호", "벚꽃",  # 무관
    ],
    "bgm": [
        "잔잔한 음악", "신나는 비트", "슬픈 발라드", "긴장감 있는 음악",
        "재즈 피아노", "록 기타", "클래식 음악", "EDM",
        "빠른 템포", "느린 음악", "여름 해변 음악", "카페 음악",
        "soft jazz", "fast rock", "ambient electronic", "chill lofi",
        "고양이", "AI 인공지능", "주식 투자", "보이저호",  # 무관
    ],
}


def step_B_extended_regression() -> dict:
    logger.info("═" * 60)
    logger.info("[B] 확장 회귀 200+ 쿼리 × 5 도메인")
    logger.info("═" * 60)
    ensure_flask()
    out = {}
    for domain, queries in EXTENDED_QUERIES.items():
        per_q = []
        for q in queries:
            try:
                res = search(q, top_k=10, file_type=domain)
                per_q.append({
                    "q": q,
                    "n": len(res),
                    "top1_conf": round((res[0].get("confidence") or 0) * 100, 1) if res else None,
                    "top1_dense": round(res[0].get("dense") or 0, 4) if res else None,
                    "top1_rerank": round(res[0].get("rerank_score") or 0, 4) if res else None,
                    "top1_file": (res[0].get("file_name") or res[0].get("id") or "") if res else None,
                })
            except Exception as e:
                per_q.append({"q": q, "error": str(e)})
        out[domain] = per_q
        n_with = sum(1 for x in per_q if x.get("n", 0) > 0)
        logger.info(f"  [{domain}] {len(queries)}쿼리 — 결과있음 {n_with}건")
    return out


# ─── C. n_sigma 정밀 sweep ───────────────────────────────────────────────────
N_SIGMA_FINE = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
SWEEP_QUERIES = {
    "image": ["고양이", "박스 속에 들어있는 고양이", "햄버거", "팝송", "보이저호"],
    "audio": ["보이저호", "고양이", "팝송", "AI 인공지능", "주식 투자"],
}


def step_C_n_sigma_precision() -> dict:
    logger.info("═" * 60)
    logger.info("[C] n_sigma 정밀 sweep")
    logger.info("═" * 60)
    out = {}
    for domain, queries in SWEEP_QUERIES.items():
        env_var = "OMC_VISUAL_N_SIGMA" if domain == "image" else "OMC_AUDIO_N_SIGMA"
        domain_out = {}
        for n in N_SIGMA_FINE:
            kill_flask()
            start_flask_bg(extra_env={env_var: n})
            if not wait_flask_ready():
                continue
            per_q = {}
            for q in queries:
                try:
                    res = search(q, top_k=10, file_type=domain)
                    per_q[q] = {
                        "n": len(res),
                        "top1_conf": round((res[0].get("confidence") or 0) * 100, 1) if res else None,
                    }
                except Exception:
                    per_q[q] = {"error": True}
            domain_out[f"n_{n}"] = per_q
            logger.info(f"  [{domain} n={n}] {sum(v.get('n', 0) for v in per_q.values())}건")
        out[domain] = domain_out
    # cleanup
    for v in ["OMC_VISUAL_N_SIGMA", "OMC_AUDIO_N_SIGMA"]:
        os.environ.pop(v, None)
    kill_flask()
    start_flask_bg()
    wait_flask_ready()
    return out


# ─── D. relevant 표본 강화 측정 ──────────────────────────────────────────────
RELEVANT_TARGETS = {
    "image": (50, "image", "visual_match", 0.0, 0.10),
    "audio": (50, "audio", "audio_match", 0.5, 0.32),
    "doc":   (50, "doc",   "dense",        0.0, 0.65),
    "bgm":   (30, "bgm",   "dense",        0.0, 0.55),
    "video": (30, "video", "dense",        0.0, 0.60),
}


def step_D_relevant_strength() -> dict:
    logger.info("═" * 60)
    logger.info("[D] 도메인별 relevant 표본 강화 측정")
    logger.info("═" * 60)
    ensure_flask()
    out = {}
    for domain, (target, file_type, match_field, rerank_min, match_min) in RELEVANT_TARGETS.items():
        cosines = []
        queries = EXTENDED_QUERIES.get(domain, [])
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
        n = len(cosines)
        try:
            import numpy as np
            arr = np.asarray(cosines)
            stats = {
                "n": n,
                "target": target,
                "met_target": n >= target,
                "min": round(float(arr.min()), 4) if n else None,
                "max": round(float(arr.max()), 4) if n else None,
                "mean": round(float(arr.mean()), 4) if n else None,
                "median": round(float(np.median(arr)), 4) if n else None,
                "std": round(float(arr.std()), 4) if n else None,
            }
        except Exception:
            stats = {"n": n, "target": target, "met_target": n >= target}
        out[domain] = stats
        logger.info(f"  [{domain}] n={n} (target {target}) {'✓' if stats.get('met_target') else '✗'}")
    return out


# ─── E. BGM 정밀 평가 ────────────────────────────────────────────────────────
BGM_DETAILED = {
    "분위기": ["잔잔한 음악", "신나는 비트", "슬픈 발라드", "긴장감 있는 음악", "몽환적 음악"],
    "장르": ["재즈 음악", "록 기타", "클래식 피아노", "EDM", "힙합", "발라드"],
    "악기": ["기타 솔로", "피아노 연주", "드럼 비트", "바이올린", "색소폰"],
    "템포": ["빠른 템포", "느린 음악", "중간 템포"],
    "상황": ["영화 OST", "운동 음악", "카페 음악", "잘 때 듣는 음악", "공부할 때 듣는 음악"],
    "영문": ["soft jazz", "fast rock", "ambient electronic", "chill lofi", "dramatic orchestral", "acoustic guitar"],
    "복합": ["여름 해변에서 듣는 음악", "비 오는 날 카페", "긴장감 있는 추격 장면", "겨울 밤 재즈"],
    "무관": ["고양이", "AI 인공지능", "주식 투자", "보이저호", "햄버거"],
}


def step_E_bgm_precision() -> dict:
    logger.info("═" * 60)
    logger.info("[E] BGM 정밀 평가")
    logger.info("═" * 60)
    ensure_flask()
    out = {}
    for category, queries in BGM_DETAILED.items():
        cat_results = []
        for q in queries:
            try:
                res = search(q, top_k=5, file_type="bgm")
            except Exception:
                cat_results.append({"q": q, "error": True})
                continue
            top_list = []
            for r in res:
                top_list.append({
                    "file": r.get("file_name") or r.get("id"),
                    "conf": round((r.get("confidence") or 0) * 100, 1),
                    "dense": round(r.get("dense") or 0, 4),
                    "rerank": round(r.get("rerank_score") or 0, 4),
                })
            cat_results.append({"q": q, "n": len(res), "top": top_list})
        out[category] = cat_results
        avg_n = sum(c.get("n", 0) for c in cat_results) / max(len(cat_results), 1)
        logger.info(f"  [{category}] 평균 결과 {avg_n:.1f}")
    return out


# ─── F. 캡션 거짓 클러스터 분석 ──────────────────────────────────────────────
def step_F_caption_clusters() -> dict:
    logger.info("═" * 60)
    logger.info("[F] 캡션 거짓 클러스터 분석")
    logger.info("═" * 60)
    lies_dir = SCRIPTS_DIR / "lies_by_category"
    if not lies_dir.exists():
        logger.warning(f"  {lies_dir} 없음 — A 단계 후 재실행")
        return {"error": "lies_by_category missing"}

    out = {"by_category": {}, "global_keywords": {}, "cooccurrence": {}}
    global_kw = Counter()
    cooccur = defaultdict(Counter)
    target_kws = ["고양이", "강아지", "사람", "음식", "건물", "하늘", "차", "꽃", "산", "바다",
                  "cat", "dog", "person", "building", "flower", "car", "food", "tree",
                  "sunset", "mountain", "beach", "kitchen", "table"]

    for category in ["cat", "dog", "food", "person", "building", "vehicle", "nature", "other"]:
        cat_path = lies_dir / f"{category}_lies.json"
        if not cat_path.exists():
            continue
        data = json.loads(cat_path.read_text(encoding="utf-8"))
        items = data.get("items", [])
        cat_kw = Counter()
        for s in items:
            cap = s.get("caption", "").lower()
            present = [kw for kw in target_kws if kw in cap]
            for kw in present:
                cat_kw[kw] += 1
                global_kw[kw] += 1
            for i, k1 in enumerate(present):
                for k2 in present[i + 1:]:
                    pair = tuple(sorted([k1, k2]))
                    cooccur[pair][category] += 1
        out["by_category"][category] = {
            "n_items": len(items),
            "top_keywords": cat_kw.most_common(15),
        }

    out["global_keywords"] = global_kw.most_common(30)
    out["cooccurrence"] = [
        {"pair": list(p), "total": sum(c.values()), "by_cat": dict(c)}
        for p, c in sorted(cooccur.items(), key=lambda x: -sum(x[1].values()))[:20]
    ]
    logger.info(f"  Top 키워드: {global_kw.most_common(10)}")
    return out


# ─── G. 한글 시각화 ──────────────────────────────────────────────────────────
def step_G_visualizations(b_results: dict, c_results: dict, d_results: dict) -> dict:
    logger.info("═" * 60)
    logger.info("[G] 한글 시각화 PNG 생성")
    logger.info("═" * 60)
    VIZ_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        for font_name in ["Malgun Gothic", "NanumGothic", "AppleGothic", "Arial Unicode MS"]:
            try:
                plt.rcParams["font.family"] = font_name
                plt.rcParams["axes.unicode_minus"] = False
                break
            except Exception:
                continue

        # 1) 도메인별 결과 수 (B)
        if b_results:
            fig, ax = plt.subplots(figsize=(10, 6))
            domains = list(b_results.keys())
            avg_n = [sum(x.get("n", 0) for x in b_results[d]) / max(len(b_results[d]), 1) for d in domains]
            zero_n = [sum(1 for x in b_results[d] if x.get("n", 0) == 0) for d in domains]
            x = np.arange(len(domains))
            ax.bar(x - 0.2, avg_n, 0.4, label="평균 결과 수", color="#4caf50")
            ax.bar(x + 0.2, zero_n, 0.4, label="0건 쿼리 수", color="#f44336")
            ax.set_xticks(x); ax.set_xticklabels(domains)
            ax.set_title("도메인별 회귀 결과 (B)")
            ax.legend(); ax.grid(True, alpha=0.3)
            p = VIZ_DIR / "B_domain_results.png"
            plt.tight_layout(); plt.savefig(str(p), dpi=120); plt.close()
            out["B"] = str(p)

        # 2) n_sigma sweep (C)
        if c_results:
            for domain, dom_data in c_results.items():
                fig, ax = plt.subplots(figsize=(10, 6))
                ns = sorted([float(k.replace("n_", "")) for k in dom_data.keys()])
                queries = sorted({q for v in dom_data.values() for q in v.keys()})
                for q in queries:
                    ys = []
                    for n in ns:
                        v = dom_data.get(f"n_{n}", {}).get(q, {})
                        ys.append(v.get("n", 0))
                    ax.plot(ns, ys, marker="o", label=q[:20])
                ax.set_xlabel("n_sigma"); ax.set_ylabel("결과 수")
                ax.set_title(f"{domain} — n_sigma sweep (C)")
                ax.legend(loc="upper right", fontsize=8); ax.grid(True, alpha=0.3)
                p = VIZ_DIR / f"C_n_sigma_{domain}.png"
                plt.tight_layout(); plt.savefig(str(p), dpi=120); plt.close()
                out[f"C_{domain}"] = str(p)

        # 3) relevant 표본 (D)
        if d_results:
            fig, ax = plt.subplots(figsize=(10, 6))
            domains = list(d_results.keys())
            ns = [d_results[d].get("n", 0) for d in domains]
            targets = [d_results[d].get("target", 0) for d in domains]
            x = np.arange(len(domains))
            ax.bar(x - 0.2, ns, 0.4, label="실제 n", color="#2196f3")
            ax.bar(x + 0.2, targets, 0.4, label="목표 n", color="#ff9800")
            ax.set_xticks(x); ax.set_xticklabels(domains)
            ax.set_title("도메인별 relevant 표본 강화 (D)")
            ax.legend(); ax.grid(True, alpha=0.3)
            p = VIZ_DIR / "D_relevant_strength.png"
            plt.tight_layout(); plt.savefig(str(p), dpi=120); plt.close()
            out["D"] = str(p)
    except Exception as e:
        logger.exception(f"  실패: {e}")
        out["error"] = str(e)
    logger.info(f"  → {len(out)} PNG 생성")
    return out


# ─── 요약 ────────────────────────────────────────────────────────────────────
def write_summary(report: dict):
    md = ["# Night V2 통합 검증 — 요약\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"]

    md.append("## A. 기존 파이프라인 재실행\n\n")
    for name, r in (report.get("A") or {}).items():
        md.append(f"- `{name}` — {r.get('status')} ({r.get('elapsed_s', '?')}s)\n")

    md.append("\n## B. 확장 회귀\n\n")
    md.append("| 도메인 | 쿼리 수 | 결과 있음 | 0건 |\n|---|---|---|---|\n")
    for d, lst in (report.get("B") or {}).items():
        n_total = len(lst); n_with = sum(1 for x in lst if x.get("n", 0) > 0)
        md.append(f"| {d} | {n_total} | {n_with} | {n_total - n_with} |\n")

    md.append("\n## C. n_sigma 정밀 sweep\n\n")
    md.append("→ `night_v2/n_sigma_precision.json` 및 `visualizations/C_*.png`\n")

    md.append("\n## D. relevant 표본 강화\n\n")
    md.append("| 도메인 | n | target | 충족 | mean | std |\n|---|---|---|---|---|---|\n")
    for d, s in (report.get("D") or {}).items():
        md.append(f"| {d} | {s.get('n')} | {s.get('target')} | "
                  f"{'✓' if s.get('met_target') else '✗'} | "
                  f"{s.get('mean', '-')} | {s.get('std', '-')} |\n")

    md.append("\n## E. BGM 정밀\n\n→ `night_v2/bgm_precision.json`\n")

    md.append("\n## F. 캡션 거짓 클러스터\n\n")
    gk = (report.get("F") or {}).get("global_keywords", [])
    if gk:
        md.append("Top 10 키워드: " + ", ".join(f"{k}({n})" for k, n in gk[:10]) + "\n")

    md.append("\n## G. 시각화\n\n")
    for k, v in (report.get("G") or {}).items():
        if k != "error":
            md.append(f"- {k}: `{v}`\n")

    md.append("\n## 다음 액션\n\n")
    md.append("1. `night_v2_summary.md` 검토 → 영향도 큰 변경부터 적용\n")
    md.append("2. n_sigma 권장값 visual_check.py / audio_check.py 반영 검토\n")
    md.append("3. relevant 표본 미충족 도메인 → 쿼리 확장 또는 threshold 완화\n")

    out_path = OUT_DIR / "night_v2_summary.md"
    out_path.write_text("".join(md), encoding="utf-8")
    logger.info(f"  → {out_path}")


# ─── 메인 ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip", default="", help="스킵 단계 (예: A,C)")
    args = parser.parse_args()
    skip = {s.strip().upper() for s in args.skip.split(",") if s.strip()}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    VIZ_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("═" * 60)
    logger.info(f"NIGHT V2 통합 검증 시작 (skip={skip or '없음'})")
    logger.info("═" * 60)
    t0 = time.time()
    report = {"start": time.strftime("%Y-%m-%d %H:%M:%S"), "skip": list(skip)}

    if "A" not in skip:
        report["A"] = step_A_existing_pipelines()

    ensure_flask()

    if "B" not in skip:
        report["B"] = step_B_extended_regression()
        (OUT_DIR / "extended_regression.json").write_text(
            json.dumps(report["B"], indent=2, ensure_ascii=False), encoding="utf-8")

    if "C" not in skip:
        report["C"] = step_C_n_sigma_precision()
        (OUT_DIR / "n_sigma_precision.json").write_text(
            json.dumps(report["C"], indent=2, ensure_ascii=False), encoding="utf-8")

    if "D" not in skip:
        report["D"] = step_D_relevant_strength()
        (OUT_DIR / "relevant_strength.json").write_text(
            json.dumps(report["D"], indent=2, ensure_ascii=False), encoding="utf-8")

    if "E" not in skip:
        report["E"] = step_E_bgm_precision()
        (OUT_DIR / "bgm_precision.json").write_text(
            json.dumps(report["E"], indent=2, ensure_ascii=False), encoding="utf-8")

    if "F" not in skip:
        report["F"] = step_F_caption_clusters()
        (OUT_DIR / "caption_clusters.json").write_text(
            json.dumps(report["F"], indent=2, ensure_ascii=False), encoding="utf-8")

    if "G" not in skip:
        report["G"] = step_G_visualizations(report.get("B", {}), report.get("C", {}), report.get("D", {}))

    report["end"] = time.strftime("%Y-%m-%d %H:%M:%S")
    report["elapsed_min"] = round((time.time() - t0) / 60, 1)

    out_path = OUT_DIR / "overnight_v2_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary(report)

    logger.info("═" * 60)
    logger.info(f"완료 — 소요 {report['elapsed_min']}분")
    logger.info(f"  통합 리포트: {out_path}")
    logger.info(f"  요약: {OUT_DIR / 'night_v2_summary.md'}")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
