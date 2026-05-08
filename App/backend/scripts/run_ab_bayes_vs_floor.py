"""scripts/run_ab_bayes_vs_floor.py — image visual_check 모드 A/B 비교.

  A 모드: Bayesian dual-Beta (현재 default, OMC_VISUAL_USE_BAYES=1)
  B 모드: hard floor + penalty (OMC_VISUAL_USE_BAYES=0)

같은 쿼리 셋을 두 번 실행 후 비교:
  - 정상 쿼리 top1 confidence 평균 (높을수록 좋음)
  - 무관 쿼리 top1 confidence 평균 (낮을수록 좋음)
  - 0건 쿼리 수
  - 분리도 = (정상 평균 conf) - (무관 평균 conf)

산출물:
  scripts/ab_bayes_vs_floor.json
  scripts/ab_bayes_vs_floor_summary.md

사용:
  cd App/backend
  python scripts/run_ab_bayes_vs_floor.py
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


def kill_flask():
    try:
        subprocess.run(["powershell", "-Command",
                        "Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | "
                        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                       check=False, capture_output=True)
        time.sleep(2)
    except Exception:
        pass


def start_flask_bg(use_bayes: bool):
    env = os.environ.copy()
    env["TRICHEF_USE_RERANKER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["OMC_VISUAL_USE_BAYES"] = "1" if use_bayes else "0"
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


def search(query, top_k=10):
    q = urllib.parse.quote(query)
    url = f"{API}?q={q}&top_k={top_k}&type=image"
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


def run_query_set(label: str, queries: list[str]) -> list[dict]:
    out = []
    for q in queries:
        try:
            res = search(q)
            top1 = res[0] if res else None
            out.append({
                "q": q,
                "n": len(res),
                "top1_conf": round((top1.get("confidence") or 0) * 100, 2) if top1 else None,
                "top1_dense": round(top1.get("dense") or 0, 4) if top1 else None,
                "top1_visual_match": round(top1.get("visual_match") or 0, 4) if top1 else None,
                "top1_id": (top1.get("id") or top1.get("file_name") or "") if top1 else None,
            })
        except Exception as e:
            out.append({"q": q, "error": str(e)})
    return out


def summarize(results: list[dict]) -> dict:
    n_total = len(results)
    n_zero = sum(1 for r in results if r.get("n", 0) == 0)
    confs = [r["top1_conf"] for r in results if r.get("top1_conf") is not None]
    vms = [r["top1_visual_match"] for r in results if r.get("top1_visual_match") is not None]
    return {
        "n": n_total,
        "n_zero": n_zero,
        "n_with_top1": len(confs),
        "mean_top1_conf": round(sum(confs) / len(confs), 2) if confs else None,
        "mean_top1_visual_match": round(sum(vms) / len(vms), 4) if vms else None,
    }


def run_mode(use_bayes: bool) -> dict:
    label = "bayes" if use_bayes else "floor"
    logger.info("═" * 60)
    logger.info(f"모드: {label}  (OMC_VISUAL_USE_BAYES={'1' if use_bayes else '0'})")
    logger.info("═" * 60)
    kill_flask()
    start_flask_bg(use_bayes)
    if not wait_flask_ready():
        logger.error(f"Flask 기동 실패")
        return {}
    rel = run_query_set("relevant", RELEVANT)
    irr = run_query_set("irrelevant", IRRELEVANT)
    rel_s = summarize(rel)
    irr_s = summarize(irr)
    sep = (rel_s.get("mean_top1_conf") or 0) - (irr_s.get("mean_top1_conf") or 0)
    logger.info(f"  정상 평균 conf: {rel_s.get('mean_top1_conf')}% (0건 {rel_s.get('n_zero')}/{rel_s['n']})")
    logger.info(f"  무관 평균 conf: {irr_s.get('mean_top1_conf')}% (0건 {irr_s.get('n_zero')}/{irr_s['n']})")
    logger.info(f"  분리도 (정상-무관): {sep:.2f}%p")
    return {
        "mode": label,
        "relevant_summary": rel_s,
        "irrelevant_summary": irr_s,
        "separation_pct": round(sep, 2),
        "relevant_detail": rel,
        "irrelevant_detail": irr,
    }


def main():
    logger.info("═" * 60)
    logger.info("A/B 회귀 — Bayesian vs Floor (image)")
    logger.info("═" * 60)
    t0 = time.time()

    bayes = run_mode(True)
    floor = run_mode(False)

    out = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_relevant": len(RELEVANT),
        "n_irrelevant": len(IRRELEVANT),
        "bayes": bayes,
        "floor": floor,
    }

    # 비교
    bs = bayes.get("separation_pct", 0)
    fs = floor.get("separation_pct", 0)
    bayes_rel = bayes.get("relevant_summary", {})
    floor_rel = floor.get("relevant_summary", {})
    bayes_irr = bayes.get("irrelevant_summary", {})
    floor_irr = floor.get("irrelevant_summary", {})

    md = ["# Bayesian vs Floor — A/B 회귀 결과\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
          f"정상 쿼리: {len(RELEVANT)}, 무관 쿼리: {len(IRRELEVANT)}\n\n",
          "## 핵심 지표\n\n",
          "| 지표 | Bayesian | Floor | 우위 |\n",
          "|---|---|---|---|\n"]

    def cell(b, f, higher_better=True):
        if b is None or f is None:
            return "-"
        if higher_better:
            return "Bayes" if b > f else ("Floor" if f > b else "동등")
        else:
            return "Bayes" if b < f else ("Floor" if f < b else "동등")

    md.append(f"| 정상 평균 conf | {bayes_rel.get('mean_top1_conf')}% | "
              f"{floor_rel.get('mean_top1_conf')}% | "
              f"{cell(bayes_rel.get('mean_top1_conf'), floor_rel.get('mean_top1_conf'), True)} |\n")
    md.append(f"| 무관 평균 conf | {bayes_irr.get('mean_top1_conf')}% | "
              f"{floor_irr.get('mean_top1_conf')}% | "
              f"{cell(bayes_irr.get('mean_top1_conf'), floor_irr.get('mean_top1_conf'), False)} |\n")
    md.append(f"| 분리도 (정상-무관) | {bs}%p | {fs}%p | "
              f"{cell(bs, fs, True)} |\n")
    md.append(f"| 정상 0건 쿼리 | {bayes_rel.get('n_zero')} | "
              f"{floor_rel.get('n_zero')} | "
              f"{cell(bayes_rel.get('n_zero'), floor_rel.get('n_zero'), False)} |\n")
    md.append(f"| 무관 0건 쿼리 | {bayes_irr.get('n_zero')} | "
              f"{floor_irr.get('n_zero')} | "
              f"{cell(bayes_irr.get('n_zero'), floor_irr.get('n_zero'), True)} |\n")

    # 권고
    md.append("\n## 권고\n\n")
    if fs > bs and (floor_rel.get("n_zero", 0) <= bayes_rel.get("n_zero", 0)):
        md.append("**Floor 우세**: 분리도 더 크고 정상 매칭 손실 없음 → "
                  "`_USE_BAYES_DEFAULT = False` 로 변경 권장.\n")
    elif bs > fs and (bayes_rel.get("n_zero", 0) <= floor_rel.get("n_zero", 0)):
        md.append("**Bayesian 우세**: 분리도 더 크고 정상 매칭 손실 없음 → 현 default 유지.\n")
    else:
        md.append("**미묘함**: 단순성·예측가능성 측면에서 Floor 권장 (audio_check 패턴 일치).\n")

    out_path = SCRIPTS_DIR / "ab_bayes_vs_floor.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path = SCRIPTS_DIR / "ab_bayes_vs_floor_summary.md"
    md_path.write_text("".join(md), encoding="utf-8")

    logger.info(f"\n→ {out_path}")
    logger.info(f"→ {md_path}")
    logger.info(f"\n  Bayesian 분리도: {bs}%p")
    logger.info(f"  Floor    분리도: {fs}%p")
    logger.info(f"\n완료 — 소요 {(time.time() - t0)/60:.1f}분")


if __name__ == "__main__":
    main()
