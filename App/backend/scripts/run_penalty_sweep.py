"""scripts/run_penalty_sweep.py — image visual_check 페널티 강도 sweep.

  모드 (2): Bayesian / Floor
  페널티 (3): 0.3 (강), 0.5 (중), 0.7 (약)
  → 6 조합 × 66 쿼리

산출물:
  scripts/penalty_sweep.json
  scripts/penalty_sweep_summary.md

사용:
  cd App/backend
  python scripts/run_penalty_sweep.py
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
SCRIPTS_DIR = _BACKEND_DIR / "scripts"
sys.path.insert(0, str(_BACKEND_DIR))

API = "http://127.0.0.1:5001/api/search"
HEALTH = "http://127.0.0.1:5001/api/health"

RELEVANT = [
    "고양이", "강아지", "토끼", "기린", "말", "닭", "여우", "곰",
    "햄버거", "피자", "초밥", "케이크", "떡볶이", "파스타",
    "자동차", "비행기", "자전거", "선박", "기차", "오토바이",
    "산", "바다", "강", "꽃", "노을", "구름", "벚꽃", "단풍",
    "운동하는 사람", "공부하는 학생", "요리사", "아기",
    "도시 야경", "공원", "박물관", "교회", "해변", "숲",
    "박스 안 고양이", "노을 지는 해변", "벚꽃 거리", "눈 덮인 산",
    "cat", "dog", "modern building", "vintage car", "sunset beach",
    "kitten", "puppy", "flower", "mountain",
]
IRRELEVANT = [
    "팝송", "보이저호", "양자컴퓨터", "추상 개념", "외계인",
    "MZ세대", "인플레이션", "GDP", "민주주의", "코스피",
    "암호화폐", "비트코인", "메타버스", "원전", "탄소중립",
]

MODES = [("bayes", "1"), ("floor", "0")]
PENALTIES = [0.3, 0.5, 0.7]


def kill_flask():
    try:
        subprocess.run(["powershell", "-Command",
                        "Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | "
                        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                       check=False, capture_output=True)
        time.sleep(2)
    except Exception:
        pass


def start_flask_bg(use_bayes: str, penalty: float):
    env = os.environ.copy()
    env["TRICHEF_USE_RERANKER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["OMC_VISUAL_USE_BAYES"] = use_bayes
    env["OMC_VISUAL_PENALTY"] = str(penalty)
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


def search(q):
    url = f"{API}?q={urllib.parse.quote(q)}&top_k=10&type=image"
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


def run_set(queries):
    out = []
    for q in queries:
        try:
            res = search(q)
            top = res[0] if res else None
            out.append({
                "q": q, "n": len(res),
                "top1_conf": round((top.get("confidence") or 0) * 100, 2) if top else None,
            })
        except Exception:
            out.append({"q": q, "error": True})
    return out


def summarize(results):
    confs = [r["top1_conf"] for r in results if r.get("top1_conf") is not None]
    n_zero = sum(1 for r in results if r.get("n", 0) == 0)
    return {
        "n_total": len(results),
        "n_zero": n_zero,
        "mean_conf": round(sum(confs) / len(confs), 2) if confs else None,
    }


def main():
    logger.info("═" * 60)
    logger.info("페널티 강도 sweep — 6 조합 (mode × penalty)")
    logger.info("═" * 60)
    t0 = time.time()
    results = {}

    for mode_name, bayes_val in MODES:
        for p in PENALTIES:
            key = f"{mode_name}_p{p}"
            logger.info(f"\n══ {key} ══")
            kill_flask()
            start_flask_bg(bayes_val, p)
            if not wait_flask_ready():
                logger.warning(f"  Flask 기동 실패 — skip")
                continue
            rel = run_set(RELEVANT)
            irr = run_set(IRRELEVANT)
            rel_s = summarize(rel)
            irr_s = summarize(irr)
            sep = (rel_s.get("mean_conf") or 0) - (irr_s.get("mean_conf") or 0)
            results[key] = {
                "mode": mode_name, "penalty": p,
                "relevant": rel_s, "irrelevant": irr_s,
                "separation_pct": round(sep, 2),
            }
            logger.info(f"  정상 {rel_s.get('mean_conf')}%, 무관 {irr_s.get('mean_conf')}%, 분리도 {sep:.2f}%p")

    # 저장
    out_path = SCRIPTS_DIR / "penalty_sweep.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # 마크다운
    md = ["# 페널티 강도 sweep — 결과\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n",
          "## 비교표\n\n",
          "| 모드 | penalty | 정상 conf | 무관 conf | 분리도 | 정상 0건 | 무관 0건 |\n",
          "|---|---|---|---|---|---|---|\n"]
    for key, r in results.items():
        rel = r.get("relevant", {}); irr = r.get("irrelevant", {})
        md.append(f"| {r['mode']} | {r['penalty']} | "
                  f"{rel.get('mean_conf')}% | {irr.get('mean_conf')}% | "
                  f"**{r['separation_pct']}%p** | "
                  f"{rel.get('n_zero')} | {irr.get('n_zero')} |\n")

    # 최적 선정 — 분리도 최대 + 정상 conf ≥ 80%
    best = None
    for key, r in results.items():
        rel = r.get("relevant", {})
        if (rel.get("mean_conf") or 0) >= 80 and r.get("separation_pct") is not None:
            if best is None or r["separation_pct"] > best[1]["separation_pct"]:
                best = (key, r)

    md.append("\n## 권고\n\n")
    if best:
        bk, br = best
        md.append(f"**추천 조합**: `{bk}` (mode={br['mode']}, penalty={br['penalty']})\n\n")
        md.append(f"- 정상 평균 conf: {br['relevant'].get('mean_conf')}%\n")
        md.append(f"- 무관 평균 conf: {br['irrelevant'].get('mean_conf')}%\n")
        md.append(f"- 분리도: **{br['separation_pct']}%p**\n\n")
        md.append("**적용 방법** (사용자 승인 후):\n")
        md.append(f"- `OMC_VISUAL_USE_BAYES={'1' if br['mode']=='bayes' else '0'}` 환경변수 설정\n")
        md.append(f"- 또는 visual_check.py 의 `_PENALTY_FACTOR` default 를 {br['penalty']} 로 변경\n")
    else:
        md.append("정상 conf ≥ 80% 조건 만족하는 조합 없음 — 추가 조사 필요.\n")

    md_path = SCRIPTS_DIR / "penalty_sweep_summary.md"
    md_path.write_text("".join(md), encoding="utf-8")

    logger.info(f"\n→ {out_path}")
    logger.info(f"→ {md_path}")
    logger.info(f"\n완료 — 소요 {(time.time() - t0)/60:.1f}분")


if __name__ == "__main__":
    main()
