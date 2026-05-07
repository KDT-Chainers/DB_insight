"""evaluate_xlang_50.py — 한↔영 cross-lingual 50케이스 평가.

같은 의미의 한국어/영어 쿼리 쌍으로 동일 파일이 상위 결과에 나오는지 평가.
예: "고양이" vs "cat" → 동일 이미지가 top-5에 공통으로 나타나는가?

BGE-M3가 이미 cross-lingual을 지원하므로, 캡션 품질 개선 후 얼마나 개선됐는지 측정.

결과: md/_xlang_50_eval.md
"""
from __future__ import annotations
import sys, json, urllib.request, urllib.parse, time
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).resolve().parents[3]
API    = "http://127.0.0.1:5001/api/search"
TOP_K  = 20
OUT_MD = ROOT / "md" / "_xlang_50_eval.md"
OUT_MD.parent.mkdir(exist_ok=True)

# 한↔영 동의어 쌍 (도메인별 10쌍씩)
XLANG_PAIRS = [
    # ── Image (고양이/동물/도시 등) ──
    ("image", "고양이", "cat"),
    ("image", "개", "dog"),
    ("image", "사람 손", "human hand"),
    ("image", "도시 풍경", "city view"),
    ("image", "나무", "tree"),
    ("image", "꽃", "flower"),
    ("image", "자동차", "car"),
    ("image", "음식", "food"),
    ("image", "건물", "building"),
    ("image", "하늘", "sky"),

    # ── Doc ──
    ("doc", "인공지능", "artificial intelligence"),
    ("doc", "환경 보고서", "environmental report"),
    ("doc", "삼성전자", "Samsung Electronics"),
    ("doc", "탄소중립", "carbon neutral"),
    ("doc", "식량 가격", "food price"),
    ("doc", "지속가능성", "sustainability"),
    ("doc", "보도자료", "press release"),
    ("doc", "기술 동향", "technology trend"),
    ("doc", "경제 분석", "economic analysis"),
    ("doc", "정책 제안", "policy proposal"),

    # ── Video ──
    ("video", "뉴스", "news"),
    ("video", "다큐멘터리", "documentary"),
    ("video", "인터뷰", "interview"),
    ("video", "스포츠", "sports"),
    ("video", "요리", "cooking"),

    # ── Audio ──
    ("audio", "팝송", "pop song"),
    ("audio", "재즈", "jazz"),
    ("audio", "클래식", "classical music"),
    ("audio", "힙합", "hip hop"),
    ("audio", "록", "rock music"),

    # ── BGM ──
    ("bgm", "배경음악", "background music"),
    ("bgm", "잔잔한 음악", "calm music"),
    ("bgm", "긴장감", "suspense music"),
    ("bgm", "행복한 느낌", "happy music"),
    ("bgm", "슬픈 음악", "sad music"),
]


def search(query: str, top_k: int = TOP_K) -> list[dict]:
    url = f"{API}?q={urllib.parse.quote(query)}&top_k={top_k}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read()).get("results", []) or []
    except Exception:
        return []


def file_ids(results: list[dict]) -> set[str]:
    return {r.get("file_name", r.get("id", "")) for r in results if r}


def overlap_at_k(ids_ko: set[str], ids_en: set[str], k: int) -> int:
    """상위 k개 결과 집합의 교집합 크기."""
    return len(ids_ko & ids_en)


def main():
    print(f"[xlang] {len(XLANG_PAIRS)}케이스 평가 시작 (top_k={TOP_K})", flush=True)
    t0 = time.time()

    rows = []
    domain_stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "hit1": 0, "hit5": 0, "hit10": 0})

    for i, (domain, q_ko, q_en) in enumerate(XLANG_PAIRS):
        res_ko = search(q_ko)
        res_en = search(q_en)

        ids_ko_1  = file_ids(res_ko[:1])
        ids_ko_5  = file_ids(res_ko[:5])
        ids_ko_10 = file_ids(res_ko[:10])
        ids_en_1  = file_ids(res_en[:1])
        ids_en_5  = file_ids(res_en[:5])
        ids_en_10 = file_ids(res_en[:10])

        ov1  = overlap_at_k(ids_ko_1,  ids_en_1,  1)
        ov5  = overlap_at_k(ids_ko_5,  ids_en_5,  5)
        ov10 = overlap_at_k(ids_ko_10, ids_en_10, 10)

        rows.append({
            "domain": domain, "q_ko": q_ko, "q_en": q_en,
            "n_ko": len(res_ko), "n_en": len(res_en),
            "overlap@1": ov1, "overlap@5": ov5, "overlap@10": ov10,
        })
        s = domain_stats[domain]
        s["n"] += 1
        s["hit1"]  += int(ov1 >= 1)
        s["hit5"]  += int(ov5 >= 1)
        s["hit10"] += int(ov10 >= 1)

        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(XLANG_PAIRS)} ({time.time()-t0:.1f}s)", flush=True)

    elapsed = time.time() - t0

    # 집계
    total = len(rows)
    total_hit1  = sum(1 for r in rows if r["overlap@1"] >= 1)
    total_hit5  = sum(1 for r in rows if r["overlap@5"] >= 1)
    total_hit10 = sum(1 for r in rows if r["overlap@10"] >= 1)

    print(f"\n=== Cross-lingual 결과 ===")
    print(f"총 {total}케이스")
    print(f"  overlap@1  (top1 일치): {total_hit1}/{total} = {total_hit1*100//total}%")
    print(f"  overlap@5  (top5 교집합 ≥1): {total_hit5}/{total} = {total_hit5*100//total}%")
    print(f"  overlap@10 (top10 교집합 ≥1): {total_hit10}/{total} = {total_hit10*100//total}%")

    # MD 보고서
    md = [
        "# Cross-lingual 50케이스 평가",
        f"_생성: {time.strftime('%Y-%m-%d %H:%M:%S')} · {elapsed:.1f}s_\n",
        "## 종합",
        f"| 지표 | 값 |", "|---|---|",
        f"| 총 케이스 | {total} |",
        f"| overlap@1 (한영 top1 동일) | **{total_hit1*100//total}%** ({total_hit1}/{total}) |",
        f"| overlap@5 (한영 top5 교집합≥1) | **{total_hit5*100//total}%** ({total_hit5}/{total}) |",
        f"| overlap@10 (한영 top10 교집합≥1) | **{total_hit10*100//total}%** ({total_hit10}/{total}) |",
        "\n## 도메인별",
        "| domain | n | @1 | @5 | @10 |", "|---|---|---|---|---|",
    ]
    for dom, s in sorted(domain_stats.items()):
        n = s["n"]
        md.append(f"| {dom} | {n} | {s['hit1']*100//n}% | {s['hit5']*100//n}% | {s['hit10']*100//n}% |")

    md += ["\n## 케이스별 상세", "| domain | 한국어 쿼리 | 영어 쿼리 | @1 | @5 | @10 |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(
            f"| {r['domain']} | {r['q_ko']} | {r['q_en']} | "
            f"{r['overlap@1']} | {r['overlap@5']} | {r['overlap@10']} |"
        )

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\n[xlang] 완료 → {OUT_MD}")


if __name__ == "__main__":
    main()
