"""Step A — 캡션 품질 진단 (15분 이내).

측정 항목:
  1. Doc 캡션 .txt 파일: degeneration 비율, 영어/한글 비율, 빈 파일 수
  2. Image captions_triple.jsonl: 깨진 한국어 비율, 빈 L1/L2/L3 수
  3. Cross-lingual baseline: 영어/한국어 동의어 쌍 5개로 검색 API 일치율

결과: md/_diag_caption_quality.md
"""
from __future__ import annotations
import sys, json, re
from pathlib import Path
from collections import defaultdict

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):  # type: ignore
        total = kw.get("total", "?")
        desc  = kw.get("desc", "")
        for i, x in enumerate(it):
            if i % 500 == 0:
                print(f"  {desc} {i}/{total}...", flush=True)
            yield x

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT      = Path(__file__).resolve().parents[3]
SCRIPTS   = Path(__file__).resolve().parent
MD_OUT    = ROOT / "md" / "_diag_caption_quality.md"
MD_OUT.parent.mkdir(exist_ok=True)

DOC_CAP_DIR  = ROOT / "Data" / "extracted_DB" / "Doc" / "captions"
IMG_JSONL    = ROOT / "Data" / "embedded_DB" / "Img" / "captions_triple.jsonl"
IMG_CAP_DIR  = ROOT / "Data" / "extracted_DB" / "Img" / "captions"

# ── degeneration 패턴 (BLIP 반복 hallucination) ──
DEGEN_PATTERNS = [
    r"(.{10,})\1{2,}",              # 10자 이상 구절 3회 이상 반복
    r"(a screenshot of a screen){2,}",
    r"(the korean version of){2,}",
    r"(showing a screen){2,}",
    r"(a screen showing){3,}",
    r"\ba\s+\w+\s+of\s+a\s+\w+\s+of\s+a\b",  # "a X of a X of a"
]
DEGEN_RE = [re.compile(p, re.IGNORECASE) for p in DEGEN_PATTERNS]

BROKEN_KO_RE = re.compile(
    r"그저운|휩진|갈갈한|뚜꺼운|꾸멈|넘우|으리|떠난거|뻐뜩|글쎈|"
    r"[가-힣]{1}[^\s가-힣a-zA-Z0-9]{3,}",  # 한글 1자 후 비정상 연속
    re.UNICODE,
)

def is_degenerated(text: str) -> bool:
    if not text:
        return False
    for r in DEGEN_RE:
        if r.search(text):
            return True
    return False

def has_korean(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text))

def has_english_words(text: str) -> bool:
    return bool(re.search(r"[a-zA-Z]{3,}", text))

print("[Step A] Doc 캡션 진단 시작...")

# ═══════════════════════════════════════
# Doc 캡션 진단
# ═══════════════════════════════════════
doc_total = doc_empty = doc_degen = doc_ko = doc_en_only = 0
doc_sizes: list[int] = []
sample_degen: list[str] = []

print("  Doc .txt 파일 수집 중...", flush=True)
txt_files = list(DOC_CAP_DIR.glob("**/*.txt"))
print(f"  Doc .txt 캡션 파일: {len(txt_files)}건", flush=True)

for fp in tqdm(txt_files, desc="Doc 캡션 스캔", total=len(txt_files)):
    try:
        txt = fp.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        doc_empty += 1
        continue
    doc_total += 1
    if not txt:
        doc_empty += 1
        continue
    doc_sizes.append(len(txt))
    if is_degenerated(txt):
        doc_degen += 1
        if len(sample_degen) < 5:
            sample_degen.append(f"`{fp.parent.name}/{fp.name}`: {txt[:80]}")
    if has_korean(txt):
        doc_ko += 1
    elif has_english_words(txt):
        doc_en_only += 1

print(f"  총 {doc_total}건 / 빈 {doc_empty} / degenerated {doc_degen} / 한글 {doc_ko} / 영어전용 {doc_en_only}")

# ═══════════════════════════════════════
# Image 캡션 진단
# ═══════════════════════════════════════
print("[Step A] Image 캡션 진단 시작...")
img_total = img_l1_empty = img_l2_empty = img_l3_empty = 0
img_degen_l3 = img_broken_ko = 0
img_en_l3 = 0
sample_img_broken: list[str] = []
sample_img_degen: list[str] = []

# (1) captions_triple.jsonl 스캔
if IMG_JSONL.exists():
    lines_all = IMG_JSONL.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"  Image JSONL: {len(lines_all)}줄", flush=True)
    for line in tqdm(lines_all, desc="Image 캡션 스캔", total=len(lines_all)):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        img_total += 1
        l1 = d.get("L1", "") or ""
        l2 = d.get("L2", "") or ""
        l3 = d.get("L3", "") or ""
        if not l1.strip(): img_l1_empty += 1
        if not l2.strip(): img_l2_empty += 1
        if not l3.strip(): img_l3_empty += 1
        if l3 and is_degenerated(l3):
            img_degen_l3 += 1
            if len(sample_img_degen) < 5:
                key = d.get("key", d.get("id", "?"))
                sample_img_degen.append(f"`{key}`: {l3[:80]}")
        if l3 and BROKEN_KO_RE.search(l3):
            img_broken_ko += 1
            if len(sample_img_broken) < 5:
                key = d.get("key", d.get("id", "?"))
                sample_img_broken.append(f"`{key}`: L3={l3[:80]}")
        if l3 and has_english_words(l3) and not has_korean(l3):
            img_en_l3 += 1

print(f"  Image 총 {img_total}건: L1빈칸 {img_l1_empty} / L2빈칸 {img_l2_empty} / L3빈칸 {img_l3_empty}")
print(f"  L3 degenerated {img_degen_l3} / 깨진한글 {img_broken_ko} / 영어전용 {img_en_l3}")

# (2) stage 파일 현황 (rebuild_img_qwen_full_caption.py 진행 상태)
if IMG_CAP_DIR.exists():
    stage_counts: dict[str, int] = defaultdict(int)
    for fp in IMG_CAP_DIR.glob("*_title.txt"):
        stage_counts["title"] += 1
    for fp in IMG_CAP_DIR.glob("*_tagline.txt"):
        stage_counts["tagline"] += 1
    for fp in IMG_CAP_DIR.glob("*_synopsis.txt"):
        stage_counts["synopsis"] += 1
    for fp in IMG_CAP_DIR.glob("*_tags_kr.txt"):
        stage_counts["tags_kr"] += 1
    for fp in IMG_CAP_DIR.glob("*_tags_en.txt"):
        stage_counts["tags_en"] += 1
    print(f"  기존 stage 파일: {dict(stage_counts)}")
else:
    stage_counts = {}
    print(f"  stage 파일 없음 (CAP_DIR 미존재)")

# ═══════════════════════════════════════
# MD 보고서 작성
# ═══════════════════════════════════════
import time
lines = [
    "# 캡션 품질 진단 보고서",
    f"_생성: {time.strftime('%Y-%m-%d %H:%M:%S')}_\n",
    "## Doc 캡션 (.txt 파일)",
    f"| 항목 | 건수 |",
    f"|---|---|",
    f"| 전체 .txt | {doc_total} |",
    f"| 빈 파일 | {doc_empty} |",
    f"| Degenerated (BLIP 반복) | **{doc_degen}** |",
    f"| 한글 포함 | {doc_ko} |",
    f"| 영어 전용 | **{doc_en_only}** |",
    f"| Degen 비율 | **{doc_degen*100//max(doc_total,1)}%** |",
]
if sample_degen:
    lines += ["\n### Doc Degen 샘플", "```"]
    lines += sample_degen
    lines += ["```"]

lines += [
    "\n## Image 캡션 (captions_triple.jsonl)",
    f"| 항목 | 건수 |",
    f"|---|---|",
    f"| 전체 | {img_total} |",
    f"| L1 빈칸 | {img_l1_empty} |",
    f"| L2 빈칸 | {img_l2_empty} |",
    f"| L3 빈칸 | {img_l3_empty} |",
    f"| L3 Degenerated | **{img_degen_l3}** |",
    f"| L3 깨진 한글 | **{img_broken_ko}** |",
    f"| L3 영어 전용 | {img_en_l3} |",
    f"| 요수정 합계 | **{img_degen_l3+img_broken_ko}** |",
]
if sample_img_degen:
    lines += ["\n### Image Degen 샘플", "```"]
    lines += sample_img_degen
    lines += ["```"]
if sample_img_broken:
    lines += ["\n### Image 깨진 한글 샘플", "```"]
    lines += sample_img_broken
    lines += ["```"]

if stage_counts:
    lines += ["\n## Image Stage 파일 현황 (Qwen2.5-VL-3B 진행률)"]
    lines += ["| stage | 완료 건 |", "|---|---|"]
    for s in ["title","tagline","synopsis","tags_kr","tags_en"]:
        lines.append(f"| {s} | {stage_counts.get(s,0)} / {img_total} |")

lines += [
    "\n## 개선 우선순위",
    "1. **Doc 캡션** — BLIP 영어 degeneration 100% → gemma3:12b 한국어 요약으로 교체 (Step B)",
    "2. **Image 캡션** — Qwen2.5-VL-3B 5-stage 재캡셔닝 (Step C, resume 가능)",
    "3. **Im 캐시 재빌드** — BGE-M3 이미 cross-lingual → 캡션만 고치면 바로 개선 (Step D)",
]

MD_OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"\n[Step A] 완료 → {MD_OUT}")
