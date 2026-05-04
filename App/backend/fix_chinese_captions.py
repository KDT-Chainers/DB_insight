"""fix_chinese_captions.py — captions_triple.jsonl 의 Chinese 문자 오염 L2 정리.

Chinese 문자(U+4E00~U+9FFF)가 포함된 L1/L2/L3 필드를 탐지하고,
한국어/영어 토큰만 남기도록 정리합니다.

실행:
    python fix_chinese_captions.py [--dry-run]
"""
import sys, io, json, re, argparse
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
from config import PATHS

JSONL = Path(PATHS["TRICHEF_IMG_CACHE"]) / "captions_triple.jsonl"

# 중국어/일본어 문자 범위
CJK_RE = re.compile(r"[一-鿿぀-ヿ㐀-䶿豈-﫿]")

def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text or ""))

def strip_cjk_sentences(text: str) -> str:
    """CJK 문자 포함 문장을 제거. 문장 단위로 분리 후 필터링."""
    if not text:
        return text
    # 문장 분리: 마침표/개행/세미콜론 기준
    sents = re.split(r"(?<=[.!?。\n])\s*|[;；]", text)
    clean = [s.strip() for s in sents if s.strip() and not has_cjk(s)]
    return " ".join(clean) if clean else ""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="변경 없이 통계만 출력")
    args = parser.parse_args()

    if not JSONL.exists():
        print(f"파일 없음: {JSONL}")
        return

    lines = JSONL.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    affected = 0
    new_lines = []

    for line in lines:
        if not line.strip():
            new_lines.append(line)
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue

        changed = False
        for field in ("L1", "L2", "L3"):
            val = obj.get(field, "")
            if has_cjk(val):
                cleaned = strip_cjk_sentences(val)
                if cleaned != val:
                    obj[field] = cleaned
                    changed = True

        if changed:
            affected += 1
            if args.dry_run:
                rel = obj.get("rel", "?")
                print(f"  [dry] 수정 대상: {rel}")
            new_lines.append(json.dumps(obj, ensure_ascii=False))
        else:
            new_lines.append(line)

    print(f"총 {total}개 항목 중 {affected}개 CJK 오염 발견")

    if not args.dry_run and affected > 0:
        JSONL.write_text("\n".join(new_lines), encoding="utf-8")
        print(f"  -> {JSONL} 업데이트 완료")
    elif args.dry_run:
        print("  (dry-run: 파일 미변경)")
    else:
        print("  변경 없음")

if __name__ == "__main__":
    main()
