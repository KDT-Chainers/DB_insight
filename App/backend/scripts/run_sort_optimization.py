"""scripts/run_sort_optimization.py — 정렬 키 변형 최적화 실험.

8개 정렬 변형 × ~50 쿼리 → 자동 메트릭 산출 → 최선 변형 선정.

산출물:
  scripts/sort_opt_report.json  (변형별 raw 결과)
  scripts/sort_opt_summary.md   (사람 친화 요약 + 추천)
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
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = _BACKEND_DIR / "scripts"
sys.path.insert(0, str(_BACKEND_DIR))

API = "http://127.0.0.1:5001/api/search"
HEALTH = "http://127.0.0.1:5001/api/health"

VARIANTS = ["A", "B", "C", "D", "E", "F", "G", "H"]

# (query, expected_top_domain | None, is_irrelevant)
TEST_QUERIES = [
    # single_kr
    ("햄버거", "image", False), ("고양이", "image", False),
    ("꽃", "image", False), ("산", "image", False),
    ("바다", "image", False), ("벚꽃", "image", False),
    ("자동차", "image", False), ("강아지", "image", False),
    # multi_kr
    ("박스 안 고양이", "image", False), ("노을 지는 해변", "image", False),
    ("벚꽃 거리", "image", False), ("운동하는 사람", "image", False),
    # intent
    ("이미지인데 햄버거가 포함된 사진", "image", False),
    ("동영상에서 보이저호", "video", False),
    ("음악 재즈 피아노", "bgm", False),
    ("문서에서 AI 인공지능", "doc", False),
    # english
    ("cat", "image", False), ("dog", "image", False),
    ("modern building", "image", False), ("sunset beach", "image", False),
    # irrelevant (image 도메인 기준 무관)
    ("보이저호", None, True), ("팝송", None, True),
    ("양자컴퓨터", None, True), ("외계인", None, True),
    ("MZ세대", None, True),
    # multi-domain queries
    ("AI 인공지능", "doc", False), ("주식 투자", "doc", False),
    ("재즈 피아노", "bgm", False), ("EDM 음악", "bgm", False),
    ("다스뵈이다", "audio", False),
]


def kill_flask():
    try:
        subprocess.run(["powershell", "-Command",
                        "Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | "
                        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                       check=False, capture_output=True)
        time.sleep(2)
    except Exception:
        pass


def start_flask_bg(variant: str):
    env = os.environ.copy()
    env["TRICHEF_USE_RERANKER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["OMC_SORT_VARIANT"] = variant
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
        time.sleep(2)
    return False


def search(q, top_k=10, file_type=None):
    params = f"q={urllib.parse.quote(q)}&top_k={top_k}"
    if file_type:
        params += f"&type={file_type}"
    with urllib.request.urlopen(f"{API}?{params}", timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


def evaluate_variant(variant: str) -> dict:
    logger.info(f"\n══ 변형 {variant} 평가 ══")
    results_per_query = {}

    for q, expected, is_irr in TEST_QUERIES:
        try:
            res = search(q, top_k=10)
        except Exception as e:
            results_per_query[q] = {"error": str(e)}
            continue

        n = len(res)
        top1 = res[0] if res else None
        top5 = res[:5]

        # rerank_mean@5
        rr_scores = [r.get("rerank_score") for r in top5 if r.get("rerank_score") is not None]
        rr_mean5 = sum(rr_scores) / len(rr_scores) if rr_scores else None

        # 도메인 매칭 (top5 중 expected 도메인 비율)
        if expected:
            domain_matches = sum(1 for r in top5
                                  if r.get("file_type") == expected
                                  or (expected == "video" and r.get("file_type") in ("video", "movie"))
                                  or (expected == "audio" and r.get("file_type") in ("audio", "music"))
                                  or (expected == "doc" and r.get("file_type") in ("doc", "doc_page")))
            domain_match_rate = domain_matches / max(len(top5), 1)
        else:
            domain_match_rate = None

        results_per_query[q] = {
            "n": n,
            "is_irrelevant": is_irr,
            "expected": expected,
            "top1_type": top1.get("file_type") if top1 else None,
            "top1_conf": round((top1.get("confidence") or 0) * 100, 2) if top1 else None,
            "top1_dense": round(top1.get("dense") or 0, 4) if top1 else None,
            "top1_rerank": round(top1.get("rerank_score") or 0, 4) if top1 else None,
            "rr_mean5": round(rr_mean5, 4) if rr_mean5 is not None else None,
            "domain_match_rate": domain_match_rate,
        }
        if expected:
            sym = "✓" if domain_match_rate and domain_match_rate >= 0.6 else "✗"
            logger.info(f"  [{variant}] '{q[:30]}' → top1={top1.get('file_type') if top1 else 'X'}, "
                        f"domain_match={domain_match_rate:.0%} {sym}")
        else:
            logger.info(f"  [{variant}] '{q[:30]}' (무관) → n={n}, top1_conf={results_per_query[q]['top1_conf']}%")

    # 종합 통계
    relevant = [r for q, r in results_per_query.items() if not r.get("is_irrelevant") and not r.get("error")]
    irrelevant = [r for q, r in results_per_query.items() if r.get("is_irrelevant") and not r.get("error")]

    n_zero_relevant = sum(1 for r in relevant if r.get("n", 0) == 0)
    domain_match_avg = (sum(r["domain_match_rate"] for r in relevant if r.get("domain_match_rate") is not None)
                        / max(len([r for r in relevant if r.get("domain_match_rate") is not None]), 1))
    rr_mean_relevant = sum(r["rr_mean5"] for r in relevant if r.get("rr_mean5") is not None) / max(
        len([r for r in relevant if r.get("rr_mean5") is not None]), 1)

    irr_top1_conf_avg = sum(r["top1_conf"] for r in irrelevant if r.get("top1_conf") is not None) / max(
        len([r for r in irrelevant if r.get("top1_conf") is not None]), 1)

    rel_top1_conf_avg = sum(r["top1_conf"] for r in relevant if r.get("top1_conf") is not None) / max(
        len([r for r in relevant if r.get("top1_conf") is not None]), 1)
    separation_pct = rel_top1_conf_avg - irr_top1_conf_avg

    return {
        "variant": variant,
        "details": results_per_query,
        "stats": {
            "n_zero_relevant": n_zero_relevant,
            "domain_match_avg": round(domain_match_avg, 4),
            "rr_mean5_avg": round(rr_mean_relevant, 4),
            "rel_top1_conf_avg": round(rel_top1_conf_avg, 2),
            "irr_top1_conf_avg": round(irr_top1_conf_avg, 2),
            "separation_pct": round(separation_pct, 2),
        },
    }


def main():
    logger.info("═" * 60)
    logger.info("정렬 키 최적화 실험 — 8 변형 × 50 쿼리")
    logger.info("═" * 60)
    t0 = time.time()

    all_results = {}
    for variant in VARIANTS:
        kill_flask()
        start_flask_bg(variant)
        if not wait_flask_ready():
            logger.warning(f"  [{variant}] Flask 기동 실패 — skip")
            continue
        all_results[variant] = evaluate_variant(variant)

    # 저장
    out_json = SCRIPTS_DIR / "sort_opt_report.json"
    out_json.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")

    # 요약 마크다운
    md = ["# 정렬 키 최적화 — 결과\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n",
          "## 종합 비교\n\n",
          "| 변형 | 정렬 키 | 0건 회귀 | 도메인 매칭 | rerank@5 | 분리도 |\n",
          "|---|---|---|---|---|---|\n"]
    LABELS = {
        "A": "(dense, rerank, conf) [현재]",
        "B": "(rerank, dense, conf)",
        "C": "(rerank, dense)",
        "D": "(dense, rerank)",
        "E": "(conf, rerank, dense)",
        "F": "0.5·dense + 0.5·rerank_n",
        "G": "0.4·dense + 0.6·rerank_n",
        "H": "0.7·rerank_n + 0.3·dense",
    }
    rows = []
    for v in VARIANTS:
        if v not in all_results:
            continue
        s = all_results[v]["stats"]
        rows.append((v, s))
        md.append(f"| {v} | {LABELS[v]} | {s['n_zero_relevant']} | "
                  f"{s['domain_match_avg']*100:.1f}% | {s['rr_mean5_avg']:.3f} | "
                  f"{s['separation_pct']:.1f}%p |\n")

    # 추천 — 종합 점수: 도메인 매칭 가중 + 분리도 가중 - 0건 페널티
    best = None
    best_score = -1e9
    for v, s in rows:
        score = (s["domain_match_avg"] * 100  # 0~100
                 + s["separation_pct"] * 0.5  # weight
                 + s["rr_mean5_avg"] * 5      # rerank score 가중
                 - s["n_zero_relevant"] * 5)  # 0건 페널티
        if score > best_score:
            best_score = score
            best = (v, s)

    md.append("\n## 추천\n\n")
    if best:
        v, s = best
        md.append(f"**최선 변형: `{v}` ({LABELS[v]})**\n\n")
        md.append(f"- 종합 점수: {best_score:.2f}\n")
        md.append(f"- 도메인 매칭: {s['domain_match_avg']*100:.1f}%\n")
        md.append(f"- 0건 회귀: {s['n_zero_relevant']}건\n")
        md.append(f"- 분리도: {s['separation_pct']:.1f}%p\n\n")
        md.append("**적용 방법** (사용자 승인 후):\n")
        md.append(f"- search.py 의 `_sort_key` default 를 변형 {v} 로 변경\n")
        md.append(f"- 또는 환경변수 `OMC_SORT_VARIANT={v}` 항상 설정\n")

    md_path = SCRIPTS_DIR / "sort_opt_summary.md"
    md_path.write_text("".join(md), encoding="utf-8")

    logger.info(f"\n→ {out_json}")
    logger.info(f"→ {md_path}")
    logger.info(f"\n완료 — 소요 {(time.time() - t0)/60:.1f}분")


if __name__ == "__main__":
    main()
