"""ASF vocab + token_sets 4 도메인 재구축 — lexical 채널 활성화.

발견된 약점:
  vocab_music.json (20000 어휘) 에 "박태웅", "의장" 모두 포함 X
  → ASF lexical 매칭 0% → 인명·고유명사 검색 약함

해결:
  raw_DB 의 모든 텍스트 (filename + STT + Qwen 캡션 + PDF 본문) 수집
  → 한국어 NER + 영문 고유명사 + n-gram 빈도 분석
  → 의미 있는 vocab 재구축 (도메인별 ~30000 토큰)
  → segment/page 단위 token_sets 재생성

영향 도메인:
  - Movie/Rec: vocab_movie/music.json + movie/music_token_sets.json
  - Doc:       auto_vocab.json + asf_token_sets.json (페이지 단위)
  - Img:       auto_vocab.json + asf_token_sets.json (이미지 단위)

사용:
  python scripts/rebuild_asf_vocab.py
  python scripts/rebuild_asf_vocab.py --domain Rec  # 단일 도메인
"""
from __future__ import annotations
import argparse
import io
import json
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[rebuild_asf_vocab] 스크립트 시작", flush=True)

ROOT = Path(__file__).resolve().parents[1]
RAW_DB = ROOT / "Data" / "raw_DB"
EMB_DB = ROOT / "Data" / "embedded_DB"
EXT_DB = ROOT / "Data" / "extracted_DB"

# 도메인별 텍스트 소스 + 출력 파일
DOM_CFG = {
    "Doc": {
        "ids": "doc_page_ids.json",
        "vocab_out": "auto_vocab.json",
        "tokenset_out": "asf_token_sets.json",
        # 페이지 단위 — ids[i] = "page_images/<stem>/p####.jpg"
    },
    "Img": {
        "ids": "img_ids.json",
        "vocab_out": "auto_vocab.json",
        "tokenset_out": "asf_token_sets.json",
    },
    "Movie": {
        "ids": "movie_ids.json",
        "vocab_out": "vocab_movie.json",
        "tokenset_out": "movie_token_sets.json",
    },
    "Rec": {
        "ids": "music_ids.json",
        "vocab_out": "vocab_music.json",
        "tokenset_out": "music_token_sets.json",
    },
}

_KOR_RE = re.compile(r"[가-힣]+")
_ENG_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_NUM_RE = re.compile(r"\d{2,}")

STOPWORDS = {
    "the","and","for","you","are","with","this","that","have","not","but","all",
    "his","her","from","what","when","where","who","why","how","mp4","wav","mp3",
    "jpg","png","pdf","jpeg","webm","mov","avi","gif","webp","ai","tv","co","kr",
    "is","of","in","to","by","on","at","or","be","a","an","it","as","we","they",
    "이","그","저","것","수","들","및","또는","에서","에게","으로","하는","되는",
    "있는","없는","이다","있다","한다","위한","통해","대한","대해","관련","내용",
    "정보","자료","파일","영상","음성","파트","번째","해서","으로","로서",
    "그래서","그러나","그리고","하지만","아니","에서는","입니다","합니다",
}


def tokenize(text: str) -> set[str]:
    """한글/영문 토큰 + 숫자(2자리+) 추출, 길이/stopword 필터."""
    out: set[str] = set()
    if not text:
        return out
    text_lower = text.lower()
    for m in _KOR_RE.finditer(text_lower):
        t = m.group()
        if 2 <= len(t) <= 8 and t not in STOPWORDS:
            out.add(t)
    for m in _ENG_RE.finditer(text_lower):
        t = m.group()
        if 3 <= len(t) <= 12 and t not in STOPWORDS:
            out.add(t)
    for m in _NUM_RE.finditer(text):
        out.add(m.group())
    return out


def collect_text_for_av(domain: str) -> list[set[str]]:
    """Movie/Rec: segments.json 의 stt_text + file_name 토큰을 segment 단위로."""
    seg_path = EMB_DB / domain / "segments.json"
    if not seg_path.exists():
        return []
    segs = json.loads(seg_path.read_text(encoding="utf-8"))
    out: list[set[str]] = []
    for s in segs:
        text = s.get("stt_text", "") or s.get("text", "") or ""
        fname = s.get("file_name", "") or s.get("file", "").replace("\\", "/").rsplit("/", 1)[-1]
        toks = tokenize(text) | tokenize(fname)
        out.append(toks)
    return out


def collect_text_for_doc() -> list[set[str]]:
    """Doc: ids 순서대로 페이지별 본문 + 파일명 토큰."""
    cache = EMB_DB / "Doc"
    ids = json.loads((cache / "doc_page_ids.json").read_text(encoding="utf-8"))
    ids_list = ids.get("ids", []) if isinstance(ids, dict) else ids

    # registry → stem → abs PDF 매핑
    reg = json.loads((cache / "registry.json").read_text(encoding="utf-8"))
    stem_to_pdf: dict[str, Path] = {}
    for k, v in reg.items():
        if isinstance(v, dict):
            ap = v.get("abs")
            if ap:
                stem_to_pdf[Path(k).stem] = Path(ap)
            for a in v.get("abs_aliases") or []:
                stem_to_pdf.setdefault(Path(a).stem, Path(a))

    # 추출된 페이지 텍스트 (extracted_DB/Doc/page_text/<stem>/p####.txt) 시도
    page_text_root = EXT_DB / "Doc" / "page_text"

    print(f"  Doc 페이지 텍스트 수집: {len(ids_list)}", flush=True)
    out: list[set[str]] = []
    for i, rid in enumerate(ids_list):
        if i % 5000 == 0:
            print(f"    {i}/{len(ids_list)}", flush=True)
        # rid = "page_images/<stem>/p####.jpg"
        m = re.match(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$", rid)
        if not m:
            out.append(set())
            continue
        stem, page_num_str = m.group(1), m.group(2)
        toks = tokenize(stem)
        # cached page text 시도 (이미 추출된 경우)
        cached = page_text_root / stem / f"p{page_num_str}.txt"
        if cached.is_file():
            try:
                toks |= tokenize(cached.read_text(encoding="utf-8"))
            except Exception:
                pass
        out.append(toks)
    return out


def collect_text_for_img() -> list[set[str]]:
    """Img: ids 순서대로 filename + Qwen 캡션 + BLIP 3-stage 캡션 토큰."""
    cache = EMB_DB / "Img"
    ids = json.loads((cache / "img_ids.json").read_text(encoding="utf-8"))
    ids_list = ids.get("ids", []) if isinstance(ids, dict) else ids

    # caption_3stage.json (BLIP) — ids 순서로 L1/L2/L3 텍스트 매핑
    cap3_path = cache / "caption_3stage.json"
    cap3_data: dict[int, set[str]] = {}
    if cap3_path.exists():
        try:
            cap3 = json.loads(cap3_path.read_text(encoding="utf-8"))
            cap3_ids = cap3.get("ids", [])
            L1 = cap3.get("L1", [])
            L2 = cap3.get("L2", [])
            L3 = cap3.get("L3", [])
            id_to_idx = {rid: i for i, rid in enumerate(cap3_ids)}
            for i, rid in enumerate(ids_list):
                if rid in id_to_idx:
                    j = id_to_idx[rid]
                    s: set[str] = set()
                    if j < len(L1) and L1[j]: s |= tokenize(L1[j])
                    if j < len(L2) and L2[j]: s |= tokenize(L2[j])
                    if j < len(L3) and L3[j]: s |= tokenize(L3[j])
                    cap3_data[i] = s
            print(f"  caption_3stage.json 매핑: {len(cap3_data)}/{len(ids_list)}", flush=True)
        except Exception as e:
            print(f"  caption_3stage 로드 실패: {e}", flush=True)

    cap_dir = EXT_DB / "Img" / "captions"
    out: list[set[str]] = []
    for i, rid in enumerate(ids_list):
        toks = tokenize(rid)
        # 1차: BLIP 3-stage caption (caption_3stage.json)
        if i in cap3_data:
            toks |= cap3_data[i]
        # 2차: 기존 단일 caption 파일 (있을 경우)
        for cand in (cap_dir / f"{rid}.json",
                     cap_dir / f"{rid.replace('/', '__')}.json",
                     cap_dir / f"{Path(rid).name}.json",
                     cap_dir / f"{rid}.txt",
                     cap_dir / f"{Path(rid).name}.txt"):
            if cand.is_file():
                try:
                    if cand.suffix == ".json":
                        d = json.loads(cand.read_text(encoding="utf-8"))
                        if isinstance(d, dict):
                            for k in ("caption", "L1", "L2", "L3"):
                                if d.get(k):
                                    toks |= tokenize(d[k])
                        else:
                            toks |= tokenize(str(d))
                    else:
                        toks |= tokenize(cand.read_text(encoding="utf-8"))
                except Exception:
                    pass
                break
        out.append(toks)
    return out


def build_vocab_and_tokensets(domain: str) -> dict:
    cfg = DOM_CFG[domain]
    cache_dir = EMB_DB / domain

    print(f"\n=== {domain} 텍스트 수집 ===", flush=True)
    if domain in ("Movie", "Rec"):
        token_sets = collect_text_for_av(domain)
    elif domain == "Doc":
        token_sets = collect_text_for_doc()
    else:  # Img
        token_sets = collect_text_for_img()

    n = len(token_sets)
    print(f"  total entries: {n}", flush=True)
    if n == 0:
        return {"domain": domain, "skipped": True}

    # vocab 빈도 집계 (DF — Document Frequency)
    df = Counter()
    for ts in token_sets:
        df.update(ts)

    # vocab 선정: DF >= 2 (한 entry 만 등장하면 over-specific) AND DF <= 30% (over-common 제외)
    n_total = n
    df_min = 2
    df_max = max(int(n_total * 0.3), 100)
    vocab = {tok: float(round(1.0 + (1.0 - df_count / n_total), 4))
             for tok, df_count in df.items()
             if df_min <= df_count <= df_max}

    print(f"  unique tokens: {len(df)}", flush=True)
    print(f"  vocab 채택:    {len(vocab)} (DF [{df_min}, {df_max}])", flush=True)

    # 인명 검증 — "박태웅" / "의장" 포함 여부
    test_tokens = ["박태웅", "의장", "장동혁", "코코펠리", "korean"]
    for t in test_tokens:
        if t in vocab:
            print(f"    ✓ '{t}' 포함 (df={df[t]})", flush=True)

    # token_sets 를 vocab 에 포함된 것만 필터
    token_sets_filtered = []
    for ts in token_sets:
        filtered = {t: vocab[t] for t in ts if t in vocab}
        token_sets_filtered.append(filtered)

    # 백업 + 저장
    ts_now = int(time.time())
    vocab_path = cache_dir / cfg["vocab_out"]
    tokenset_path = cache_dir / cfg["tokenset_out"]
    if vocab_path.exists():
        shutil.copy2(vocab_path, vocab_path.with_suffix(vocab_path.suffix + f".bak.{ts_now}"))
    if tokenset_path.exists():
        shutil.copy2(tokenset_path, tokenset_path.with_suffix(tokenset_path.suffix + f".bak.{ts_now}"))

    vocab_path.write_text(json.dumps(vocab, ensure_ascii=False, indent=2), encoding="utf-8")
    tokenset_path.write_text(json.dumps(token_sets_filtered, ensure_ascii=False), encoding="utf-8")
    print(f"  저장: {vocab_path.name} ({len(vocab)} 토큰)", flush=True)
    print(f"  저장: {tokenset_path.name} ({len(token_sets_filtered)} entries)", flush=True)
    return {"domain": domain, "n_entries": n_total, "vocab_size": len(vocab),
            "박태웅": "박태웅" in vocab, "의장": "의장" in vocab}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=list(DOM_CFG.keys()))
    args = parser.parse_args()
    domains = [args.domain] if args.domain else list(DOM_CFG.keys())
    results = []
    for d in domains:
        try:
            r = build_vocab_and_tokensets(d)
            results.append(r)
        except Exception as e:
            print(f"[{d}] 실패: {e}", flush=True)
            results.append({"domain": d, "error": str(e)[:120]})

    print("\n" + "=" * 60, flush=True)
    print("ASF vocab/token_sets 재구축 결과", flush=True)
    print("=" * 60, flush=True)
    for r in results:
        if r.get("skipped"):
            print(f"  {r['domain']}: skipped")
        elif r.get("error"):
            print(f"  {r['domain']}: ERROR — {r['error']}")
        else:
            mark = "✓" if (r.get("박태웅") or r.get("의장")) else "·"
            print(f"  {r['domain']}: vocab={r['vocab_size']} entries={r['n_entries']} "
                  f"{mark} 박태웅={r['박태웅']} 의장={r['의장']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
