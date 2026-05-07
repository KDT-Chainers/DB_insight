"""gen_doc_summaries_gemma.py — Doc 페이지 한국어 요약 생성 (gemma3:12b Ollama).

문제: 기존 Doc 캡션(.txt) = BLIP 영어 degenerated (완전 무용)
해결: _body_texts.json (PDF 본문) → gemma3:12b → 한국어 3-tier 요약
     저장: extracted_DB/Doc/captions/{doc_folder}/summary.caption.json
     형식: {"L1": "30자 제목", "L2": "80자 한문장", "L3": "200자 상세"}

전략:
  - 문서 단위 요약 (447 docs × ~8s = ~1h)
  - 각 문서의 모든 페이지가 같은 doc-level summary를 캡션으로 사용
  - 페이지별 .caption.json = doc summary (Im 캐시 재빌드 시 사용)
  - Resume: 이미 summary.caption.json 있으면 스킵

사용:
  cd App/backend && python scripts/gen_doc_summaries_gemma.py
"""
from __future__ import annotations
import sys, json, re, time, urllib.request, urllib.parse
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT         = Path(__file__).resolve().parents[3]
DOC_CACHE    = ROOT / "Data" / "embedded_DB" / "Doc"
DOC_CAP_DIR  = ROOT / "Data" / "extracted_DB" / "Doc" / "captions"
BODY_TEXTS   = DOC_CACHE / "_body_texts.json"
DOC_IDS_PATH = DOC_CACHE / "doc_page_ids.json"

OLLAMA_URL   = "http://localhost:11434/api/generate"
MODEL        = "gemma3:12b"
TIMEOUT_S    = 120   # 요청당 타임아웃

PROMPT_TMPL = """\
다음은 한국어 문서에서 추출한 텍스트입니다. 한국어로 3단계 요약을 작성하세요.

반드시 아래 JSON 형식으로만 출력하고, 설명 없이 JSON만 출력하세요:
{{"L1": "30자 이내 핵심 제목", "L2": "80자 이내 한문장 요약", "L3": "200자 이내 상세 요약 (주제·키워드·맥락 포함)"}}

문서 제목: {title}

텍스트:
{text}
"""

JSON_RE = re.compile(r'\{[^{}]+\}', re.DOTALL)


def ollama_summarize(title: str, text: str) -> dict | None:
    """gemma3:12b 로 한국어 3-tier 요약 생성."""
    prompt = PROMPT_TMPL.format(
        title=title[:80],
        text=text[:2000],  # 토큰 절약
    )
    payload = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 300},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            raw = result.get("response", "")
    except Exception as e:
        print(f"    [Ollama 오류] {e}", flush=True)
        return None

    # JSON 추출
    m = JSON_RE.search(raw)
    if not m:
        # fallback: raw 텍스트를 L3로
        clean = raw.strip()[:200]
        return {"L1": title[:30], "L2": clean[:80], "L3": clean}
    try:
        d = json.loads(m.group())
        return {
            "L1": str(d.get("L1", title[:30]))[:30],
            "L2": str(d.get("L2", ""))[:80],
            "L3": str(d.get("L3", ""))[:250],
        }
    except Exception:
        clean = raw.strip()[:200]
        return {"L1": title[:30], "L2": clean[:80], "L3": clean}


def load_body_texts() -> dict[str, str]:
    """_body_texts.json → {page_id: text}"""
    print(f"[B] _body_texts.json 로드 중 ({BODY_TEXTS.stat().st_size // 1024 // 1024}MB)...",
          flush=True)
    if not BODY_TEXTS.exists():
        print("  [경고] _body_texts.json 없음", flush=True)
        return {}
    raw = json.loads(BODY_TEXTS.read_bytes().decode("utf-8", errors="replace"))
    if isinstance(raw, dict):
        return {k: str(v) for k, v in raw.items() if v}
    # list → 페이지 ID 순서로 매핑
    ids_raw = json.loads(DOC_IDS_PATH.read_text(encoding="utf-8"))
    ids = ids_raw.get("ids", ids_raw) if isinstance(ids_raw, dict) else ids_raw
    return {ids[i]: str(t) for i, t in enumerate(raw) if i < len(ids) and t}


def main():
    t0 = time.time()
    print(f"[Step B] Doc 한국어 요약 생성 시작 (모델: {MODEL})", flush=True)

    # Ollama 상태 확인
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            tags = json.loads(r.read())
            models = [m["name"] for m in tags.get("models", [])]
            if not any(MODEL.split(":")[0] in m for m in models):
                print(f"  [경고] {MODEL} 미발견. 사용 가능: {models}", flush=True)
            else:
                print(f"  Ollama OK, 모델 확인 완료", flush=True)
    except Exception as e:
        print(f"  [경고] Ollama 연결 실패: {e} — 계속 시도", flush=True)

    # body_texts 로드
    body_texts = load_body_texts()
    print(f"  body_texts: {len(body_texts)}건 로드", flush=True)

    # 페이지 ID → 문서 폴더 그룹핑
    # page_id 예: "page_images/Samsung_Report/p0000.jpg"
    doc_groups: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for page_id, text in body_texts.items():
        parts = Path(page_id).parts
        if len(parts) >= 2:
            # parts[0]="page_images", parts[1]=doc_folder, parts[2]="p0000.jpg"
            doc_folder = parts[1] if parts[0] == "page_images" else parts[0]
            stem = Path(parts[-1]).stem  # "p0000"
            try:
                page_num = int(stem[1:]) if stem.startswith("p") else 0
            except ValueError:
                page_num = 0
            doc_groups[doc_folder].append((page_num, page_id, text))

    # 페이지 번호 정렬
    for folder in doc_groups:
        doc_groups[folder].sort(key=lambda x: x[0])

    total_docs = len(doc_groups)
    print(f"  문서 수: {total_docs}건", flush=True)
    print(f"  저장 경로: {DOC_CAP_DIR}", flush=True)

    done = skip = fail = 0

    for i, (doc_folder, pages) in enumerate(sorted(doc_groups.items())):
        out_dir = DOC_CAP_DIR / doc_folder
        summary_path = out_dir / "summary.caption.json"

        # Resume: 이미 있으면 스킵
        if summary_path.exists():
            try:
                existing = json.loads(summary_path.read_text(encoding="utf-8"))
                if existing.get("L1") and existing.get("L3"):
                    skip += 1
                    # 페이지별 파일도 보장
                    _write_page_captions(out_dir, pages, existing)
                    continue
            except Exception:
                pass

        # 상위 3페이지 텍스트 합산 (최대 2500자)
        combined_text = ""
        for _, _, txt in pages[:3]:
            combined_text += txt.strip() + "\n"
            if len(combined_text) > 2500:
                break
        combined_text = combined_text.strip()

        if not combined_text:
            fail += 1
            continue

        # Ollama 요약
        summary = ollama_summarize(doc_folder, combined_text)
        if not summary:
            fail += 1
            continue

        # 저장
        out_dir.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 페이지별 .caption.json 생성 (Im 캐시 재빌드에서 사용)
        _write_page_captions(out_dir, pages, summary)
        done += 1

        if (i + 1) % 20 == 0 or i < 3:
            elapsed = time.time() - t0
            eta = elapsed / (done + skip + 1) * (total_docs - i - 1)
            print(
                f"  [{i+1}/{total_docs}] 완료:{done} 스킵:{skip} 실패:{fail} "
                f"경과:{elapsed/60:.1f}분 ETA:{eta/60:.1f}분",
                flush=True,
            )

    elapsed = time.time() - t0
    print(f"\n[Step B] 완료 — 생성:{done} 스킵:{skip} 실패:{fail} ({elapsed/60:.1f}분)")


def _write_page_captions(
    out_dir: Path,
    pages: list[tuple[int, str, str]],
    summary: dict,
) -> None:
    """모든 페이지에 doc-level summary를 .caption.json으로 저장."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for page_num, page_id, page_text in pages:
        stem = Path(page_id).stem  # p0000
        cap_path = out_dir / f"{stem}.caption.json"
        if cap_path.exists():
            continue
        # 페이지 텍스트가 있으면 L3에 page snippet 보강
        page_cap = dict(summary)
        if page_text.strip():
            snippet = page_text.strip()[:100]
            page_cap["L3"] = (summary.get("L3", "") + " " + snippet).strip()[:250]
        cap_path.write_text(
            json.dumps(page_cap, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
