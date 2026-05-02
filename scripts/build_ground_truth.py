"""4 도메인 검색 ground truth 자동 생성.

전략:
  1. filename token mining — 파일명에서 한글/영어 N-gram 추출 후 매칭 파일이
     [2, 30] 범위에 들어가는 토큰만 쿼리 후보로 채택 (너무 일반/특수한 것 제외)
  2. STT mining (Movie/Rec) — segments.json 의 stt_text 에서 인명·고유명사
     패턴 (한글 3-5자 + 의장/대표/대통령/박사/감독 등 직함) 추출
  3. 도메인별 균형 ~50 쿼리 = 총 200 쿼리

출력: scripts/_ground_truth_auto.json
   [{"query": "...", "domain": "doc|image|video|audio",
     "expected_basenames": ["...","..."], "source": "filename|stt"}]

사용:
  python scripts/build_ground_truth.py
  python scripts/build_ground_truth.py --per-domain 50
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
RAW_DB = ROOT / "Data" / "raw_DB"
EMB_DB = ROOT / "Data" / "embedded_DB"
OUTPUT = ROOT / "scripts" / "_ground_truth_auto.json"

DOMAIN_LABEL = {
    "Doc":   "doc",
    "Img":   "image",
    "Movie": "video",
    "Rec":   "audio",
}

DOMAIN_EXT = {
    "Doc":   {".pdf"},
    "Img":   {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"},
    "Movie": {".mp4", ".avi", ".mov", ".mkv", ".webm"},
    "Rec":   {".wav", ".mp3", ".m4a", ".ogg", ".flac"},
}

# 너무 흔한 단어 — 쿼리에서 제외
STOPWORDS = {
    "the", "and", "for", "you", "are", "with", "this", "that", "have", "not",
    "but", "all", "his", "her", "from", "what", "when", "where", "who", "why",
    "how", "mp4", "wav", "mp3", "jpg", "png", "pdf", "ai", "tv", "co", "kr",
    "the", "a", "an", "is", "of", "in", "to", "by", "on", "at", "or", "be",
    "이", "그", "저", "것", "수", "들", "및", "또는", "에서", "에게", "으로",
    "하는", "되는", "있는", "없는", "이다", "있다", "한다", "위한", "통해",
    "대한", "대해", "관련", "내용", "정보", "자료", "파일", "영상", "음성",
}


def collect_files(domain: str) -> list[Path]:
    domdir = RAW_DB / domain
    if not domdir.is_dir():
        return []
    exts = DOMAIN_EXT[domain]
    out: list[Path] = []
    for sub in domdir.iterdir():
        if not sub.is_dir() or sub.name == "staged":
            continue
        for p in sub.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                out.append(p)
    return out


_KOR_RE = re.compile(r"[가-힣]+")
_ENG_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """한글/영어 단어 추출. 길이 2자 이상, stopword 제외."""
    text = text.lower()
    tokens = []
    for m in _KOR_RE.finditer(text):
        t = m.group()
        if 2 <= len(t) <= 8 and t not in STOPWORDS:
            tokens.append(t)
    for m in _ENG_RE.finditer(text):
        t = m.group()
        if 3 <= len(t) <= 12 and t not in STOPWORDS:
            tokens.append(t)
    return tokens


def mine_filename_queries(files: list[Path], target_n: int,
                          min_match: int = 2, max_match: int = 20) -> list[dict]:
    """파일명에서 토큰 추출 → 매칭 파일 수 [min_match, max_match] 범위만 선택."""
    token_to_files: dict[str, list[str]] = defaultdict(list)
    for p in files:
        stem = p.stem
        tokens = set(tokenize(stem))
        # 2-gram 도 추출 (한글: 인접 단어 결합)
        kor_words = _KOR_RE.findall(stem)
        for i in range(len(kor_words) - 1):
            bg = kor_words[i] + " " + kor_words[i+1]
            if len(bg) <= 12:
                tokens.add(bg)
        for t in tokens:
            token_to_files[t].append(p.name)

    # 빈도 필터: [min_match, max_match] 매칭하는 토큰만
    candidates = []
    for tok, names in token_to_files.items():
        n = len(set(names))
        if min_match <= n <= max_match:
            candidates.append((tok, sorted(set(names)), n))

    # 다양성 우선: 토큰별 매칭 파일 수가 골고루 분산되도록 stratified sampling
    candidates.sort(key=lambda x: x[2])  # 매칭 수 오름차순
    if len(candidates) > target_n:
        # bin 별로 sampling
        step = max(1, len(candidates) // target_n)
        candidates = candidates[::step][:target_n]

    return [
        {"query": tok, "expected_basenames": names, "source": "filename"}
        for tok, names, _ in candidates
    ]


def mine_stt_queries(domain: str, target_n: int,
                     min_match: int = 2, max_match: int = 8) -> list[dict]:
    """Rec/Movie 의 segments.json 에서 인명·고유명사 추출.

    패턴:
      - 한글 2-4자 + " " + (의장|대표|대통령|박사|감독|교수|장관|위원|의원)
      - 한글 3-5자 단독 (인명 가능성)
    """
    seg_path = EMB_DB / domain / "segments.json"
    if not seg_path.exists():
        return []
    segs = json.loads(seg_path.read_text(encoding="utf-8"))
    title_pattern = re.compile(
        r"([가-힣]{2,4})\s*(의장|대표|대통령|박사|감독|교수|장관|위원|의원|소장|회장)"
    )

    phrase_to_files: dict[str, set[str]] = defaultdict(set)
    for s in segs:
        text = s.get("stt_text", "") or s.get("text", "") or ""
        if not text or len(text) < 4:
            continue
        fp = s.get("file") or s.get("file_path") or ""
        if not fp:
            continue
        fname = fp.replace("\\", "/").rsplit("/", 1)[-1]
        for m in title_pattern.finditer(text):
            phrase = f"{m.group(1)} {m.group(2)}"
            phrase_to_files[phrase].add(fname)

    candidates = []
    for phr, names in phrase_to_files.items():
        n = len(names)
        if min_match <= n <= max_match:
            candidates.append((phr, sorted(names), n))

    candidates.sort(key=lambda x: -x[2])  # 매칭 많은 순
    candidates = candidates[:target_n]
    return [
        {"query": phr, "expected_basenames": names, "source": "stt"}
        for phr, names, _ in candidates
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-domain", type=int, default=50,
                        help="도메인당 생성할 쿼리 수 (기본 50, 총 200)")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    all_queries: list[dict] = []
    for dom, label in DOMAIN_LABEL.items():
        files = collect_files(dom)
        print(f"\n[{dom}] raw_DB 파일: {len(files)}")
        if not files:
            continue

        # filename 기반 (Img/Doc 은 100% filename, Movie/Rec 는 60%)
        fn_target = args.per_domain if dom in ("Doc", "Img") else int(args.per_domain * 0.6)
        fn_queries = mine_filename_queries(files, fn_target)
        for q in fn_queries:
            q["domain"] = label
        print(f"  filename 쿼리: {len(fn_queries)}")
        all_queries.extend(fn_queries)

        # STT 기반 (Movie/Rec 만)
        if dom in ("Movie", "Rec"):
            stt_target = args.per_domain - len(fn_queries)
            stt_queries = mine_stt_queries(dom, stt_target)
            for q in stt_queries:
                q["domain"] = label
            print(f"  STT 쿼리:      {len(stt_queries)}")
            all_queries.extend(stt_queries)

    # 출력
    Path(args.output).write_text(
        json.dumps(all_queries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n총 {len(all_queries)} 쿼리 생성 → {args.output}")

    # 도메인별 카운트
    by_dom = Counter(q["domain"] for q in all_queries)
    by_src = Counter(q["source"] for q in all_queries)
    print(f"  도메인별: {dict(by_dom)}")
    print(f"  소스별:   {dict(by_src)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
