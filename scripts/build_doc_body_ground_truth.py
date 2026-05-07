"""Doc 본문 키워드 기반 ground truth 생성 — OCR/본문 fusion 효과 측정용.

기존 1211 쿼리는 filename 기반 → 본문 매칭 효과 측정 불가.
이 스크립트는 page_text/<stem>/p####.txt 본문에서 의미 있는 명사구를 추출하여
"이 키워드를 검색하면 어떤 PDF 가 나와야 하는가" ground truth 생성.

대상:
  - extracted_DB/Doc/page_text/ 의 모든 .txt
  - 페이지별 토큰 → DF 분석 → 1~5 PDF 매칭하는 키워드 채택

출력: scripts/_ground_truth_doc_body.json
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[build_doc_body_ground_truth] 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
PAGE_TEXT = ROOT / "Data" / "extracted_DB" / "Doc" / "page_text"
DOC_CACHE = ROOT / "Data" / "embedded_DB" / "Doc"
OUTPUT = ROOT / "scripts" / "_ground_truth_doc_body.json"

_KOR_RE = re.compile(r"[가-힣]+")
_ENG_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
STOPWORDS = {
    "이", "그", "저", "것", "수", "들", "및", "또는", "에서", "에게", "으로",
    "하는", "되는", "있는", "없는", "이다", "있다", "한다", "위한", "통해",
    "대한", "대해", "관련", "내용", "정보", "자료", "파일", "영상", "음성",
    "the", "and", "for", "you", "are", "with", "this", "that", "have", "not",
    "but", "all", "his", "her", "from", "what", "when", "where", "who", "why",
    "how", "of", "in", "to", "by", "on", "at", "or", "be", "is", "as",
}


def tokenize_meaningful(text: str) -> set[str]:
    """본문에서 의미 있는 단어 추출 (3-8자, stopword 제외)."""
    out: set[str] = set()
    for m in _KOR_RE.finditer(text):
        t = m.group()
        if 3 <= len(t) <= 8 and t not in STOPWORDS:
            out.add(t)
    for m in _ENG_RE.finditer(text):
        t = m.group().lower()
        if 4 <= len(t) <= 12 and t not in STOPWORDS:
            out.add(t)
    return out


def extract_phrases(text: str) -> set[str]:
    """본문에서 명사구 추출 (2단어 결합)."""
    out: set[str] = set()
    words = _KOR_RE.findall(text)
    for i in range(len(words) - 1):
        bg = f"{words[i]} {words[i+1]}"
        if 5 <= len(bg) <= 18 and not any(w in STOPWORDS for w in bg.split()):
            out.add(bg)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-n", type=int, default=200)
    parser.add_argument("--min-match", type=int, default=2)
    parser.add_argument("--max-match", type=int, default=8,
                        help="너무 많이 매칭되는 흔한 단어 제외")
    args = parser.parse_args()

    # 본문 텍스트 → PDF 매핑
    if not PAGE_TEXT.is_dir():
        print(f"[ERROR] {PAGE_TEXT} 없음 — Doc body 추출 먼저 수행", flush=True)
        return 2

    print("page_text 디렉토리 스캔...", flush=True)
    token_to_pdfs: dict[str, set[str]] = defaultdict(set)
    phrase_to_pdfs: dict[str, set[str]] = defaultdict(set)
    n_files = 0
    for stem_dir in PAGE_TEXT.iterdir():
        if not stem_dir.is_dir():
            continue
        stem = stem_dir.name
        # PDF 단위로 토큰 모음 (모든 페이지 합)
        all_tokens: set[str] = set()
        all_phrases: set[str] = set()
        for txt_file in stem_dir.glob("*.txt"):
            try:
                t = txt_file.read_text(encoding="utf-8")
            except Exception:
                continue
            all_tokens |= tokenize_meaningful(t)
            all_phrases |= extract_phrases(t)
            n_files += 1
        for tok in all_tokens:
            token_to_pdfs[tok].add(stem)
        for ph in all_phrases:
            phrase_to_pdfs[ph].add(stem)

    print(f"  스캔된 페이지: {n_files}", flush=True)
    print(f"  유니크 토큰: {len(token_to_pdfs)}", flush=True)
    print(f"  유니크 명사구: {len(phrase_to_pdfs)}", flush=True)

    # PDF 매칭 [min_match, max_match] 범위만 채택
    candidates = []
    for tok, pdfs in token_to_pdfs.items():
        n = len(pdfs)
        if args.min_match <= n <= args.max_match:
            candidates.append((tok, sorted(pdfs), n, "body_token"))
    for ph, pdfs in phrase_to_pdfs.items():
        n = len(pdfs)
        if args.min_match <= n <= args.max_match:
            candidates.append((ph, sorted(pdfs), n, "body_phrase"))

    print(f"  후보: {len(candidates)}", flush=True)

    # stratified sampling — 매칭 수 골고루
    candidates.sort(key=lambda x: x[2])
    if len(candidates) > args.target_n:
        step = max(1, len(candidates) // args.target_n)
        candidates = candidates[::step][:args.target_n]

    # PDF stem → file_name 매핑 (registry 활용)
    reg_path = DOC_CACHE / "registry.json"
    stem_to_fname: dict[str, str] = {}
    if reg_path.exists():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        for k, v in reg.items():
            stem_to_fname[Path(k).stem] = Path(k).name
            if isinstance(v, dict):
                for a in v.get("abs_aliases") or []:
                    stem_to_fname.setdefault(Path(a).stem, Path(a).name)

    out: list[dict] = []
    for tok, stems, n, src in candidates:
        # stem → filename (확장자 포함)
        fnames = [stem_to_fname.get(s, s + ".pdf") for s in stems]
        out.append({
            "query": tok,
            "expected_basenames": fnames,
            "domain": "doc",
            "source": src,
        })

    Path(OUTPUT).write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n총 {len(out)} 쿼리 → {OUTPUT}", flush=True)
    by_src = Counter(q["source"] for q in out)
    print(f"  소스별: {dict(by_src)}", flush=True)
    print("  샘플 5:", flush=True)
    for q in out[:5]:
        print(f"    [{q['source']}] '{q['query']}' → {len(q['expected_basenames'])} PDF", flush=True)


if __name__ == "__main__":
    main()
