"""scripts/test_ocr_search.py — 이미지·문서 내 텍스트 검색 가능 여부 진단.

이미지·문서 페이지에 포함된 텍스트(차트 레이블, 표 내용, 캡션 등)가
텍스트 쿼리로 검색되는지 세 가지 경로를 검증한다.

검증 경로:
  1. OCR 파일 존재 여부 (pytesseract / EasyOCR 결과 txt/json)
  2. Qwen 캡션 샘플 — 이미지 내 텍스트가 캡션에 언급되는지 정성 확인
  3. 실제 검색 — 캡션에서 발견된 핵심 단어로 쿼리 → 해당 이미지/문서 히트 여부

실행:
  python scripts/test_ocr_search.py
  python scripts/test_ocr_search.py --samples 10
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
os.chdir(ROOT / "App" / "backend")

DATA = ROOT / "Data"


def _has_korean(s: str) -> bool:
    return bool(re.search(r"[가-힣]", s))


def _has_numbers(s: str) -> bool:
    return bool(re.search(r"\d{4}", s))  # 연도/수치 포함 여부


def check_ocr_files(n: int) -> dict:
    """OCR 결과 파일 존재 여부 및 샘플 확인."""
    result: dict = {"ocr_files": [], "summary": {}}

    # 이미지 OCR
    img_ocr_dir = DATA / "extracted_DB" / "Img"
    ocr_txts = list(img_ocr_dir.rglob("*.txt"))[:n]
    ocr_jsons = list(img_ocr_dir.rglob("ocr_*.json"))[:n]

    print(f"\n[OCR 파일 탐색]")
    print(f"  Img .txt  파일 수: {len(list(img_ocr_dir.rglob('*.txt')))}")
    print(f"  Img ocr_*.json 수: {len(list(img_ocr_dir.rglob('ocr_*.json')))}")

    # 문서 페이지 OCR (ocr_doc_pages.py 결과)
    doc_ocr_dir = DATA / "extracted_DB" / "Doc"
    doc_ocr = list(doc_ocr_dir.rglob("ocr_*.json"))
    print(f"  Doc ocr_*.json 수: {len(doc_ocr)}")

    if not ocr_txts and not ocr_jsons and not doc_ocr:
        print("  ⚠ OCR 결과 파일 없음 — 이미지 내 텍스트는 캡션 의존")
        result["summary"]["ocr_implemented"] = False
        result["summary"]["note"] = (
            "OCR 미구현. 이미지 내 텍스트는 Qwen/BLIP 캡션이 묘사 방식으로 "
            "포함 시에만 검색 가능. 정확한 텍스트(연도, 고유명사 등) 검색 불가."
        )
    else:
        result["summary"]["ocr_implemented"] = True
        for f in (ocr_txts + ocr_jsons + doc_ocr)[:3]:
            result["ocr_files"].append(str(f))
    return result


def sample_captions(n: int) -> dict:
    """Qwen/BLIP 캡션 샘플 — 이미지 내 텍스트 언급 여부."""
    result: dict = {"samples": [], "summary": {}}
    caption_dir = DATA / "extracted_DB" / "Img" / "captions"
    if not caption_dir.exists():
        print(f"\n[캡션 샘플] ⚠ {caption_dir} 없음")
        result["summary"]["error"] = "캡션 디렉토리 없음"
        return result

    files = list(caption_dir.glob("*.json"))[:n]
    print(f"\n[캡션 샘플]  ({len(files)}개 / 총 {len(list(caption_dir.glob('*.json')))}개)")
    has_kr, has_num, has_text = 0, 0, 0
    for f in files:
        try:
            d = json.loads(f.read_bytes().decode("utf-8", errors="replace"))
            # 단일 문자열 or 딕셔너리
            if isinstance(d, str):
                cap = d
            elif isinstance(d, dict):
                cap = " ".join(str(v) for v in d.values() if v)
            else:
                cap = str(d)

            kr = _has_korean(cap)
            num = _has_numbers(cap)
            # 이미지 내 텍스트를 언급하는 패턴: "text", "reads", "says", "written"
            text_mention = bool(re.search(
                r"\b(text|reads|says|written|labeled|shows|caption|titled)\b", cap, re.I
            ))
            if kr:     has_kr += 1
            if num:    has_num += 1
            if text_mention: has_text += 1

            print(f"  [{f.stem[:30]}]  한글={kr}  숫자={num}  텍스트언급={text_mention}")
            print(f"    {cap[:120]}")
            result["samples"].append({
                "file": f.name, "has_korean": kr,
                "has_numbers": num, "text_mention": text_mention,
                "caption_preview": cap[:200],
            })
        except Exception as e:
            print(f"  ⚠ {f.name}: {e}")

    total = max(len(files), 1)
    result["summary"] = {
        "sampled": len(files),
        "korean_pct":       round(has_kr / total * 100, 1),
        "numbers_pct":      round(has_num / total * 100, 1),
        "text_mention_pct": round(has_text / total * 100, 1),
    }
    print(f"\n  → 한국어 포함: {has_kr}/{len(files)}  숫자: {has_num}/{len(files)}"
          f"  텍스트언급: {has_text}/{len(files)}")
    return result


def test_text_search(eng, n: int) -> dict:
    """캡션에서 핵심 단어 추출 → 실제 검색으로 hit 여부 검증."""
    result: dict = {"tests": [], "summary": {"hit": 0, "miss": 0, "skip": 0}}

    caption_dir = DATA / "extracted_DB" / "Img" / "captions"
    if not caption_dir.exists() or "image" not in eng._cache:
        result["summary"]["skip"] = n
        return result

    files = list(caption_dir.glob("*.json"))[:n]
    print(f"\n[이미지 텍스트 검색 테스트]  {len(files)}개 샘플")
    for f in files:
        try:
            d = json.loads(f.read_bytes().decode("utf-8", errors="replace"))
            cap = d if isinstance(d, str) else " ".join(str(v) for v in d.values() if v)

            # 4글자 이상 한글 단어 또는 4글자 이상 영어 단어 추출
            kr_words = re.findall(r"[가-힣]{4,}", cap)
            en_words = re.findall(r"[a-zA-Z]{5,}", cap)
            words = (kr_words + en_words)[:3]
            if not words:
                result["summary"]["skip"] += 1
                continue

            query = " ".join(words[:2])
            # 원본 파일명 (캡션 파일명 == 이미지 파일명 stem)
            expected_stem = f.stem.lower()

            results = eng.search(query, domain="image", topk=5, use_lexical=True)
            hit_ids = [r.id.lower() for r in results]
            hit = any(expected_stem in rid or rid in expected_stem for rid in hit_ids)

            status = "✓" if hit else "✗"
            print(f"  {status} '{query}' → hit={hit}  "
                  f"top={results[0].id[:50] if results else 'none'}")
            result["tests"].append({
                "file": f.name, "query": query,
                "expected_stem": expected_stem, "hit": hit,
                "top_result": results[0].id if results else "",
                "top_conf": round(results[0].confidence, 4) if results else 0.0,
            })
            if hit:
                result["summary"]["hit"] += 1
            else:
                result["summary"]["miss"] += 1
        except Exception as e:
            print(f"  ⚠ {f.name}: {e}")
            result["summary"]["skip"] += 1

    total = result["summary"]["hit"] + result["summary"]["miss"]
    result["summary"]["hit_rate"] = round(
        result["summary"]["hit"] / max(total, 1), 3
    )
    print(f"\n  → Hit={result['summary']['hit']}  Miss={result['summary']['miss']}"
          f"  HitRate={result['summary']['hit_rate']:.1%}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=10, help="샘플 수")
    args = parser.parse_args()

    print("=" * 65)
    print("  DB_insight 이미지/문서 내 텍스트 검색 진단")
    print("=" * 65)

    from services.trichef.unified_engine import TriChefEngine
    print("\n[엔진 로드 중...]")
    eng = TriChefEngine()

    report: dict = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "ocr_check":     check_ocr_files(args.samples),
        "caption_sample": sample_captions(args.samples),
        "search_test":   test_text_search(eng, args.samples),
    }

    # 종합 진단
    ocr_ok = report["ocr_check"]["summary"].get("ocr_implemented", False)
    kr_pct = report["caption_sample"]["summary"].get("korean_pct", 0)
    hit_rate = report["search_test"]["summary"].get("hit_rate", 0)

    print(f"\n{'=' * 65}")
    print("[종합 진단]")
    print(f"  OCR 구현:          {'✓' if ocr_ok else '✗ 미구현'}")
    print(f"  캡션 한국어 비율:  {kr_pct:.1f}%"
          f"  {'✓ 양호' if kr_pct >= 50 else '⚠ 낮음 (Qwen 재캡션 권장)'}")
    print(f"  캡션 기반 검색률:  {hit_rate:.1%}"
          f"  {'✓' if hit_rate >= 0.5 else '⚠'}")

    if not ocr_ok:
        print("\n  [개선 권장]")
        print("  1. scripts/ocr_doc_pages.py 실행 → 문서 페이지 OCR 텍스트 추가")
        print("  2. EasyOCR/pytesseract로 이미지 내 한국어 텍스트 추출 파이프라인 추가")
        print("  3. 추출 텍스트를 Im_body 채널에 병합 → 검색 정확도 향상")

    report["diagnosis"] = {
        "ocr_implemented": ocr_ok,
        "caption_korean_pct": kr_pct,
        "caption_search_hit_rate": hit_rate,
        "recommendation": (
            "OCR 미구현 — 이미지 내 텍스트 검색 불완전. "
            "ocr_doc_pages.py 실행 및 EasyOCR 통합 권장."
            if not ocr_ok else "OCR 구현됨 — 추가 정확도 검증 필요"
        ),
    }

    out_dir = ROOT / "bench_results"
    out_dir.mkdir(exist_ok=True)
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"{ts}_test_ocr_search.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[saved] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
