"""4 도메인 검색 ground truth v2 — 1700+ 쿼리 자동 생성.

확장:
  - 도메인당 200 filename 쿼리 (1~3-gram, 매칭 [2, 50])
  - STT mining 확장 (인명+직함, 인명+동사, 주제어 — Movie/Rec)
  - Image caption mining (BLIP/Qwen 캡션 → 키워드)
  - 자연어 시나리오 wrapping ("X 에 대한 자료" 등)
  - Adversarial (오타, 어순, 조사) 자동 생성

출력: scripts/_ground_truth_v2.json
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RAW_DB = ROOT / "Data" / "raw_DB"
EMB_DB = ROOT / "Data" / "embedded_DB"
EXT_DB = ROOT / "Data" / "extracted_DB"
OUTPUT = ROOT / "scripts" / "_ground_truth_v2.json"

DOMAIN_LABEL = {"Doc": "doc", "Img": "image", "Movie": "video", "Rec": "audio"}
DOMAIN_EXT = {
    "Doc":   {".pdf"},
    "Img":   {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"},
    "Movie": {".mp4", ".avi", ".mov", ".mkv", ".webm"},
    "Rec":   {".wav", ".mp3", ".m4a", ".ogg", ".flac"},
}

STOPWORDS = {
    "the","and","for","you","are","with","this","that","have","not","but","all",
    "his","her","from","what","when","where","who","why","how","mp4","wav","mp3",
    "jpg","png","pdf","jpeg","webm","mov","avi","gif","webp","ai","tv","co","kr",
    "is","of","in","to","by","on","at","or","be","a","an","it","as","we","they",
    "이","그","저","것","수","들","및","또는","에서","에게","으로","하는","되는",
    "있는","없는","이다","있다","한다","위한","통해","대한","대해","관련","내용",
    "정보","자료","파일","영상","음성","파트","번째","해서","으로","로서","에게",
}

_KOR_RE = re.compile(r"[가-힣]+")
_ENG_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def collect_files(domain: str) -> list[Path]:
    domdir = RAW_DB / domain
    if not domdir.is_dir():
        return []
    exts = DOMAIN_EXT[domain]
    out = []
    for sub in domdir.iterdir():
        if not sub.is_dir() or sub.name == "staged":
            continue
        for p in sub.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                out.append(p)
    return out


def tokenize(text: str, min_len: int = 2, max_len: int = 12) -> list[str]:
    text = text.lower()
    toks = []
    for m in _KOR_RE.finditer(text):
        t = m.group()
        if min_len <= len(t) <= max_len and t not in STOPWORDS:
            toks.append(t)
    for m in _ENG_RE.finditer(text):
        t = m.group()
        if 3 <= len(t) <= max_len and t not in STOPWORDS:
            toks.append(t)
    return toks


def mine_filename_v2(files: list[Path], target_n: int = 200) -> list[dict]:
    """1-gram + 2-gram + 3-gram, 매칭 [2, 50] 범위, 도메인당 target_n 개."""
    tok_to_files: dict[str, set[str]] = defaultdict(set)
    for p in files:
        stem = p.stem
        words = _KOR_RE.findall(stem) + _ENG_RE.findall(stem)
        # 1-gram
        for w in tokenize(stem):
            tok_to_files[w].add(p.name)
        # 2-gram
        for i in range(len(words) - 1):
            bg = (words[i] + " " + words[i+1]).lower()
            if 4 <= len(bg) <= 25:
                tok_to_files[bg].add(p.name)
        # 3-gram
        for i in range(len(words) - 2):
            tg = (words[i] + " " + words[i+1] + " " + words[i+2]).lower()
            if 6 <= len(tg) <= 35:
                tok_to_files[tg].add(p.name)

    candidates = []
    for tok, names in tok_to_files.items():
        n = len(names)
        if 2 <= n <= 50:
            candidates.append((tok, sorted(names), n))

    # stratified sampling — 매칭 수 골고루
    candidates.sort(key=lambda x: x[2])
    if len(candidates) > target_n:
        step = max(1, len(candidates) // target_n)
        candidates = candidates[::step][:target_n]

    return [
        {"query": tok, "expected_basenames": names, "source": "filename"}
        for tok, names, _ in candidates
    ]


def mine_stt_v2(domain: str, target_n: int = 100) -> list[dict]:
    """STT 패턴 확장 — 인명+직함 + 핵심 명사구 + 주제어."""
    seg_path = EMB_DB / domain / "segments.json"
    if not seg_path.exists():
        return []
    segs = json.loads(seg_path.read_text(encoding="utf-8"))

    title_pat = re.compile(
        r"([가-힣]{2,4})\s*(의장|대표|대통령|박사|감독|교수|장관|위원|의원|소장|회장|기자|작가)"
    )
    # 명사구 패턴 — 한글 2~5자 단어 2개 결합 ("AI 시대", "한국 경제")
    nphrase_pat = re.compile(r"([가-힣A-Za-z]{2,5})\s+([가-힣A-Za-z]{2,5})")

    phr_to_files: dict[str, set[str]] = defaultdict(set)
    for s in segs:
        text = s.get("stt_text", "") or s.get("text", "") or ""
        if not text or len(text) < 4:
            continue
        fp = s.get("file") or s.get("file_path") or ""
        if not fp:
            continue
        fname = fp.replace("\\", "/").rsplit("/", 1)[-1]
        # 인명+직함
        for m in title_pat.finditer(text):
            phr_to_files[f"{m.group(1)} {m.group(2)}"].add(fname)
        # 명사구 (간단 — 빈도 기반 필터)
        for m in nphrase_pat.finditer(text):
            ph = f"{m.group(1)} {m.group(2)}".lower()
            if any(t in STOPWORDS for t in ph.split()):
                continue
            if 4 <= len(ph) <= 15:
                phr_to_files[ph].add(fname)

    cand = [(p, sorted(f), len(f)) for p, f in phr_to_files.items()
            if 2 <= len(f) <= 30]
    cand.sort(key=lambda x: -x[2])
    cand = cand[:target_n]
    return [
        {"query": p, "expected_basenames": f, "source": "stt"}
        for p, f, _ in cand
    ]


def mine_image_caption(target_n: int = 150) -> list[dict]:
    """extracted_DB/Img/captions/ 의 BLIP/Qwen 캡션 → 키워드 → 쿼리."""
    cap_dir = EXT_DB / "Img" / "captions"
    if not cap_dir.is_dir():
        return []
    # registry 로드 — caption file → 원본 image 매핑
    reg_path = EMB_DB / "Img" / "registry.json"
    if not reg_path.exists():
        return []
    reg = json.loads(reg_path.read_text(encoding="utf-8"))

    # caption file → image filename 매핑 (best-effort)
    img_to_text: dict[str, str] = {}
    for cap_file in cap_dir.iterdir():
        if cap_file.suffix not in (".json", ".txt"):
            continue
        # caption 파일 stem 으로 registry 매칭
        stem = cap_file.stem.replace("__", "/")
        if stem in reg:
            img_name = Path(stem).name
        elif Path(cap_file.stem).name in reg:
            img_name = Path(cap_file.stem).name
        else:
            # 직접 stem 사용
            img_name = Path(cap_file.stem).name
        try:
            if cap_file.suffix == ".json":
                d = json.loads(cap_file.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    txt = " ".join(filter(None, (
                        d.get("caption", ""), d.get("L1", ""),
                        d.get("L2", ""), d.get("L3", ""),
                    )))
                else:
                    txt = str(d)
            else:
                txt = cap_file.read_text(encoding="utf-8")
            img_to_text[img_name] = txt.strip()
        except Exception:
            pass

    if not img_to_text:
        return []

    # 토큰 → 이미지 set
    tok_to_imgs: dict[str, set[str]] = defaultdict(set)
    for img_name, txt in img_to_text.items():
        for t in tokenize(txt):
            tok_to_imgs[t].add(img_name)
        # 2-gram
        words = _ENG_RE.findall(txt) + _KOR_RE.findall(txt)
        for i in range(len(words) - 1):
            bg = (words[i] + " " + words[i+1]).lower()
            if 5 <= len(bg) <= 25:
                tok_to_imgs[bg].add(img_name)

    cand = [(t, sorted(imgs), len(imgs)) for t, imgs in tok_to_imgs.items()
            if 2 <= len(imgs) <= 30]
    cand.sort(key=lambda x: -x[2])
    cand = cand[:target_n]
    return [
        {"query": t, "expected_basenames": imgs, "source": "img_caption"}
        for t, imgs, _ in cand
    ]


def wrap_natural_language(base_queries: list[dict], n_wrap: int = 50,
                          domain: str = "") -> list[dict]:
    """기본 토큰 쿼리를 자연어 문장으로 wrapping."""
    templates = {
        "doc": [
            "{q} 에 대한 자료",
            "{q} 보고서",
            "{q} 관련 문서",
            "{q} 분석",
            "{q} 통계",
        ],
        "image": [
            "{q} 사진",
            "{q} 이미지",
            "사진에 {q}",
            "{q} 가 있는 사진",
        ],
        "video": [
            "{q} 영상",
            "{q} 가 나오는 동영상",
            "{q} 관련 뉴스",
            "{q} 인터뷰",
        ],
        "audio": [
            "{q} 음성",
            "{q} 가 말하는 음성",
            "{q} 관련 강의",
            "{q} 인터뷰 음성",
        ],
    }
    tpls = templates.get(domain, templates["doc"])
    sample = random.sample(base_queries, min(n_wrap, len(base_queries)))
    out = []
    for q in sample:
        tpl = random.choice(tpls)
        out.append({
            "query": tpl.format(q=q["query"]),
            "expected_basenames": q["expected_basenames"],
            "source": "natural_lang",
            "base_query": q["query"],
        })
    return out


def make_adversarial(base_queries: list[dict], n_adv: int = 30) -> list[dict]:
    """오타·어순 변경·조사 변형으로 robustness 쿼리 생성."""
    out = []
    sample = random.sample(base_queries, min(n_adv, len(base_queries)))
    for q in sample:
        orig = q["query"]
        words = orig.split()
        # 1. 어순 뒤집기 (2단어 이상)
        if len(words) >= 2:
            shuffled = list(words)
            random.shuffle(shuffled)
            new_q = " ".join(shuffled)
            if new_q != orig:
                out.append({
                    "query": new_q,
                    "expected_basenames": q["expected_basenames"],
                    "source": "adversarial_shuffle",
                    "base_query": orig,
                })
        # 2. 조사 추가 (한글 단어에)
        if any(_KOR_RE.match(w) for w in words):
            joshi = random.choice(["의", "에 대한", "관련", "은"])
            new_q = words[0] + joshi + (" " + " ".join(words[1:]) if len(words) > 1 else "")
            out.append({
                "query": new_q,
                "expected_basenames": q["expected_basenames"],
                "source": "adversarial_joshi",
                "base_query": orig,
            })
        # 3. 1글자 drop (오타 시뮬)
        if len(orig.replace(" ", "")) > 4:
            chars = list(orig)
            # 공백 아닌 인덱스 중 임의 1개 drop
            non_space = [i for i, c in enumerate(chars) if c != " "]
            if non_space:
                idx = random.choice(non_space)
                new_q = "".join(chars[:idx] + chars[idx+1:])
                out.append({
                    "query": new_q,
                    "expected_basenames": q["expected_basenames"],
                    "source": "adversarial_typo",
                    "base_query": orig,
                })
    return out[:n_adv * 2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-domain-fn", type=int, default=200,
                        help="도메인당 filename 기반 쿼리 수")
    parser.add_argument("--per-domain-stt", type=int, default=120,
                        help="STT 기반 쿼리 수 (Movie/Rec 만)")
    parser.add_argument("--n-img-caption", type=int, default=150)
    parser.add_argument("--n-wrap-per-dom", type=int, default=40)
    parser.add_argument("--n-adv-per-dom", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    random.seed(args.seed)
    all_queries: list[dict] = []

    for dom, label in DOMAIN_LABEL.items():
        files = collect_files(dom)
        print(f"\n[{dom}] raw_DB 파일: {len(files)}", flush=True)
        if not files:
            continue
        fn_qs = mine_filename_v2(files, args.per_domain_fn)
        for q in fn_qs:
            q["domain"] = label
        print(f"  filename: {len(fn_qs)}", flush=True)
        all_queries.extend(fn_qs)

        # STT (Movie/Rec)
        if dom in ("Movie", "Rec"):
            stt_qs = mine_stt_v2(dom, args.per_domain_stt)
            for q in stt_qs:
                q["domain"] = label
            print(f"  stt:      {len(stt_qs)}", flush=True)
            all_queries.extend(stt_qs)

        # Image caption (Img only)
        if dom == "Img":
            img_qs = mine_image_caption(args.n_img_caption)
            for q in img_qs:
                q["domain"] = label
            print(f"  caption:  {len(img_qs)}", flush=True)
            all_queries.extend(img_qs)

        # 자연어 wrapping (각 도메인의 base 토큰 쿼리에서 sample)
        base = [q for q in all_queries if q["domain"] == label
                and q["source"] == "filename"]
        nl_qs = wrap_natural_language(base, args.n_wrap_per_dom, domain=label)
        for q in nl_qs:
            q["domain"] = label
        print(f"  natural:  {len(nl_qs)}", flush=True)
        all_queries.extend(nl_qs)

        # Adversarial
        adv_qs = make_adversarial(base, args.n_adv_per_dom)
        for q in adv_qs:
            q["domain"] = label
        print(f"  adver:    {len(adv_qs)}", flush=True)
        all_queries.extend(adv_qs)

    Path(args.output).write_text(
        json.dumps(all_queries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n총 {len(all_queries)} 쿼리 → {args.output}", flush=True)

    by_dom = Counter(q["domain"] for q in all_queries)
    by_src = Counter(q["source"] for q in all_queries)
    print(f"  도메인별: {dict(by_dom)}", flush=True)
    print(f"  소스별:   {dict(by_src)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
