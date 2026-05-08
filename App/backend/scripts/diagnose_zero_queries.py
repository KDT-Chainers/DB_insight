"""scripts/diagnose_zero_queries.py — 0건 쿼리 원인 진단.

각 0건 쿼리에 대해:
  1. 동일 쿼리 재실행 (현 설정) → 0건 재현 확인
  2. 도메인별 대용량 검색 (top_k=50) → 결과 자체가 있는지
  3. 데이터셋 자체 매칭 가능성 점검 — 인덱스에서 키워드 직접 grep
  4. 분류: (a) 데이터 부재 / (b) 의도적 차단 / (c) 필터 over-cut

산출물: scripts/zero_queries_diagnosis.json + .md
"""
from __future__ import annotations

import json
import logging
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

ZERO_QUERIES = json.loads((SCRIPTS_DIR / "_zero_queries.json").read_text(encoding="utf-8"))

# 의도적 차단 — 무관 쿼리 (0건이 정상)
INTENDED_IRRELEVANT = {
    "doc":   ["고양이", "햄버거", "벚꽃", "팝송", "보이저호"],
    "bgm":   ["고양이", "AI 인공지능", "주식 투자", "보이저호", "햄버거", "벚꽃"],
}


def search(q, top_k=20, file_type="image"):
    url = f"{API}?q={urllib.parse.quote(q)}&top_k={top_k}&type={file_type}"
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("results", [])


def grep_corpus(domain: str, q: str) -> int:
    """도메인 코퍼스(캡션/텍스트)에서 쿼리 토큰 등장 횟수 직접 카운트."""
    count = 0
    try:
        from config import PATHS
        if domain == "image":
            cap = json.loads((Path(PATHS["TRICHEF_IMG_CACHE"]) / "caption_3stage.json").read_text(encoding="utf-8"))
            ids = cap.get("ids", []); L1 = cap.get("L1", []); L2 = cap.get("L2", []); L3 = cap.get("L3", [])
            for i in range(len(ids)):
                full = (str(L1[i] if i < len(L1) else "") + " "
                        + str(L2[i] if i < len(L2) else "") + " "
                        + str(L3[i] if i < len(L3) else "")).lower()
                if q.lower() in full:
                    count += 1
        elif domain == "doc":
            # 간단 추정 — Doc 코퍼스 직접 접근 어려움. 도메인 검색 결과로 대체.
            count = -1  # 미지원 마커
        elif domain == "video":
            cap_path = Path(PATHS["TRICHEF_VID_CACHE"]) / "caption_3stage.json"
            if cap_path.exists():
                cap = json.loads(cap_path.read_text(encoding="utf-8"))
                ids = cap.get("ids", []); L1 = cap.get("L1", []); L2 = cap.get("L2", []); L3 = cap.get("L3", [])
                for i in range(len(ids)):
                    full = (str(L1[i] if i < len(L1) else "") + " "
                            + str(L2[i] if i < len(L2) else "") + " "
                            + str(L3[i] if i < len(L3) else "")).lower()
                    if q.lower() in full:
                        count += 1
            else:
                count = -1
        elif domain == "bgm":
            meta_path = Path(PATHS.get("BGM_AUDIO_META", "Data/extracted_DB/Music/audio_meta.json"))
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                # meta 형식 다양 — 모든 string 값에서 검색
                items = meta.get("items") if isinstance(meta, dict) else meta
                if isinstance(items, list):
                    for it in items:
                        full = json.dumps(it, ensure_ascii=False).lower()
                        if q.lower() in full:
                            count += 1
                else:
                    count = -1
            else:
                count = -1
    except Exception as e:
        logger.debug(f"grep failed: {e}")
        count = -2
    return count


def main():
    logger.info("═" * 60)
    logger.info("0건 쿼리 원인 진단 시작")
    logger.info("═" * 60)
    t0 = time.time()
    out = {}

    for domain, queries in ZERO_QUERIES.items():
        out[domain] = []
        for q in queries:
            logger.info(f"  [{domain}] '{q}' 진단 중...")
            entry = {"query": q}

            # 1) 의도적 차단인지
            intended = q in INTENDED_IRRELEVANT.get(domain, [])
            entry["intended_irrelevant"] = intended

            # 2) top_k=50 으로 재검색
            try:
                res = search(q, top_k=50, file_type=domain)
                entry["n_results_topk50"] = len(res)
                if res:
                    top = res[0]
                    entry["top1_dense"] = round(top.get("dense") or 0, 4)
                    entry["top1_conf"] = round((top.get("confidence") or 0) * 100, 2)
                    entry["top1_visual_match"] = round(top.get("visual_match") or 0, 4) if "visual_match" in top else None
            except Exception as e:
                entry["search_error"] = str(e)

            # 3) 코퍼스 직접 grep
            grep_n = grep_corpus(domain, q)
            entry["corpus_match_count"] = grep_n  # -1=미지원, -2=실패, ≥0=실제 카운트

            # 4) 분류
            if intended:
                category = "intended_block"
            elif grep_n == 0:
                category = "data_absence"   # 코퍼스에 키워드 없음
            elif grep_n > 0 and entry.get("n_results_topk50", 0) == 0:
                category = "filter_overcut"  # 코퍼스에 있는데 필터가 컷
            elif entry.get("n_results_topk50", 0) > 0:
                category = "topk_too_low"   # top_k=10 에서만 0, top_k=50 에서는 결과
            else:
                category = "unknown"
            entry["category"] = category

            logger.info(f"    → {category} (grep={grep_n}, topk50={entry.get('n_results_topk50', 0)})")
            out[domain].append(entry)

    # 저장
    json_path = SCRIPTS_DIR / "zero_queries_diagnosis.json"
    json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # 마크다운
    md = ["# 0건 쿼리 원인 진단\n",
          f"실행: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"]
    for domain, entries in out.items():
        md.append(f"## {domain} 도메인\n\n")
        md.append("| 쿼리 | 분류 | 의도? | top_k=50 | 코퍼스 매칭 | top1_dense |\n")
        md.append("|---|---|---|---|---|---|\n")
        for e in entries:
            grep = e.get("corpus_match_count")
            grep_s = "지원안함" if grep == -1 else ("실패" if grep == -2 else str(grep))
            md.append(f"| `{e['query']}` | **{e['category']}** | "
                      f"{'✓' if e['intended_irrelevant'] else '-'} | "
                      f"{e.get('n_results_topk50', '-')} | {grep_s} | "
                      f"{e.get('top1_dense', '-')} |\n")
        md.append("\n")

    # 요약 통계
    md.append("## 분류 요약\n\n")
    cats = {}
    for entries in out.values():
        for e in entries:
            cats[e["category"]] = cats.get(e["category"], 0) + 1
    md.append("| 분류 | 건수 | 의미 |\n|---|---|---|\n")
    explanations = {
        "intended_block": "무관 쿼리 의도적 차단 (정상 동작)",
        "data_absence": "코퍼스에 키워드 자체 없음 (데이터 부재)",
        "filter_overcut": "데이터 있는데 필터가 컷 (개선 필요)",
        "topk_too_low": "top_k=10 부족 — 50 에서는 결과 (UI 보정 필요)",
        "unknown": "추가 조사 필요",
    }
    for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
        md.append(f"| {cat} | {n} | {explanations.get(cat, '')} |\n")

    md_path = SCRIPTS_DIR / "zero_queries_diagnosis.md"
    md_path.write_text("".join(md), encoding="utf-8")

    logger.info(f"\n→ {json_path}")
    logger.info(f"→ {md_path}")
    logger.info(f"분류: {cats}")
    logger.info(f"완료 — 소요 {(time.time() - t0)/60:.1f}분")


if __name__ == "__main__":
    main()
