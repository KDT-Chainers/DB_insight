"""검색 결과에 부착할 위치(location) 메타 추출 유틸.

도메인별로 사용자가 결과 행에서 즉시 읽을 수 있는 "여기 어디?" 정보를 생성한다.

도메인별 location 스키마 (모든 키는 optional, 없으면 누락):
- doc:    page         (int, 1-indexed)
          page_label   (str, "p.12")
          line         (int, 1-indexed, query 매칭된 첫 줄)
          line_label   (str, "L.45")
          snippet      (str, 매칭 줄 + 인접 컨텍스트, 최대 200자)
- image:  (해당 없음 — 이미지는 단일 위치)
- video:  timestamp    (float, sec)
          timestamp_end (float, sec)
          timestamp_label (str, "12:34" / "1:02:34")
          snippet      (str, 매칭 세그먼트 텍스트)
- audio:  동일 (video 와 같은 키)

설계 원칙:
- 신규 파일 1개 — search.py 가 결과 dict 빌드 직후 호출.
- 실패 시 None 반환 → 호출부가 그대로 location 키 생략.
- 백엔드 추가 의존성 없음 (caption_io / fitz 만 재사용).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# 한국어 조사·어미 — 매칭 시 제거하여 어간 매칭 강화
# 예: "박태웅의" → "박태웅", "AI를" → "AI"
_KOR_JOSA = (
    "에서는", "에서도", "에서의", "으로의", "으로는", "으로도", "이라는",
    "이라고", "이라며", "에서", "으로", "에게", "에는", "에도", "에서",
    "보다", "한테", "께서", "이다", "이며", "라고", "라는", "라며",
    "으면", "면서", "이라", "이고", "하고", "이고", "이고",
    "의", "에", "를", "을", "이", "가", "은", "는", "와", "과",
    "도", "만", "라", "면", "고", "며",
)


def _strip_josa(word: str) -> str:
    """한국어 어절 끝 조사 제거 (어간 추출 근사)."""
    if not word:
        return word
    for j in _KOR_JOSA:
        if word.endswith(j) and len(word) > len(j) + 1:
            return word[:-len(j)]
    return word


def _query_tokens(q: str) -> list[str]:
    """검색 쿼리를 한국어/영문/숫자 토큰으로 분리. 조사 제거 후 길이≥2 만 채택.

    예: "박태웅의 의장" → ["박태웅", "의장"]
        "AI 시대를 위한" → ["AI", "시대", "위한"] → 추가 _strip_josa 로 안정화
    """
    if not q:
        return []
    raw = re.findall(r"[\w가-힣]+", q.lower())
    out: list[str] = []
    seen: set[str] = set()
    for t in raw:
        # 한글 토큰만 조사 제거
        if any("가" <= c <= "힣" for c in t):
            stem = _strip_josa(t)
        else:
            stem = t
        if len(stem) >= 2 and stem not in seen:
            out.append(stem)
            seen.add(stem)
    return out


def _find_line_with_query(text: str, query: str, snippet_max: int = 200) -> dict | None:
    """페이지 텍스트에서 query 토큰 매칭 점수가 가장 높은 줄 찾기.

    개선: 줄 안 단어들도 조사 제거 후 token 과 비교 → 어간 매칭.

    Returns:
        { line: int(1-indexed), text: str, score: int } 또는 None.
    """
    tokens = _query_tokens(query)
    if not tokens or not text:
        return None
    lines = text.split("\n")
    best_idx = -1
    best_score = 0
    best_line = ""
    for i, line in enumerate(lines):
        ll = line.lower()
        # 1차: 단순 substring (빠름, 대부분 케이스)
        score = sum(1 for t in tokens if t in ll)
        # 2차: 단어 어간 매칭 (조사 제거된 형태)
        if score < len(tokens):
            line_words = re.findall(r"[\w가-힣]+", ll)
            line_stems = {_strip_josa(w) for w in line_words}
            stem_score = sum(1 for t in tokens if t in line_stems)
            score = max(score, stem_score)
        if score > best_score:
            best_score = score
            best_idx = i
            best_line = line.strip()
    if best_score == 0 or best_idx < 0:
        return None
    # 컨텍스트: 매칭 줄 + 다음 1~2줄 합쳐 스니펫
    ctx_lines = [l.strip() for l in lines[best_idx:best_idx + 2] if l.strip()]
    snippet = " ".join(ctx_lines)[:snippet_max]
    return {
        "line": best_idx + 1,            # 1-indexed
        "text": best_line[:snippet_max],
        "score": best_score,
        "snippet": snippet,
    }


def _hms(sec: float) -> str:
    """초 단위 → HH:MM:SS / MM:SS 자동 포맷."""
    if sec is None or sec < 0:
        sec = 0.0
    s = int(round(float(sec)))
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{ss:02d}"
    return f"{m}:{ss:02d}"


def _doc_location(trichef_id: str, query: str = "") -> dict | None:
    """trichef_id 'page_images/{stem}/p0023.png' → {page, page_label, line?, snippet?}.

    page_idx_from_stem 의 0-인덱스를 사용자 친화 1-인덱스로 변환.
    query 가 주어지면 해당 페이지의 PDF 텍스트에서 매칭 줄 검색 후 snippet 추가.
    """
    try:
        from embedders.trichef.caption_io import page_idx_from_stem
        parts = Path(trichef_id).parts
        if len(parts) < 3:
            return None
        stem = parts[1]
        page_stem = Path(parts[-1]).stem
        idx0 = page_idx_from_stem(page_stem)
        page1 = idx0 + 1
        out: dict = {"page": page1, "page_label": f"p.{page1}"}

        # query 가 있을 때만 PDF 텍스트 로드 + 줄 매칭 (비용 회피).
        if query:
            try:
                from services.trichef.lexical_rebuild import resolve_doc_pdf_map
                pdf_map = resolve_doc_pdf_map()
                pdf = pdf_map.get(stem)
                if pdf and pdf.exists() and pdf.stat().st_size > 0:
                    import fitz
                    with fitz.open(pdf) as d:
                        if 0 <= idx0 < len(d):
                            text = d[idx0].get_text("text") or ""
                    line_match = _find_line_with_query(text, query)
                    if line_match:
                        out["line"]       = line_match["line"]
                        out["line_label"] = f"L.{line_match['line']}"
                        out["snippet"]    = line_match["snippet"]
            except Exception as e:
                logger.debug(f"[location_resolver] doc PDF/line 추출 실패: {e}")

        return out
    except Exception as e:
        logger.debug(f"[location_resolver] doc 위치 추출 실패: {e}")
        return None


def _av_location(segments: list[dict]) -> dict | None:
    """segments 리스트에서 최고 점수 세그먼트의 시간 범위 + 텍스트 추출.

    search.py 가 _search_trichef_av 에서 만든 segments 는 이미 score 내림차순.
    [0] 이 대표 시점.
    """
    if not segments:
        return None
    top = segments[0] if isinstance(segments[0], dict) else None
    if not top:
        return None
    try:
        start = float(top.get("start", 0.0) or 0.0)
        end   = float(top.get("end", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    out = {
        "timestamp":     round(start, 2),
        "timestamp_end": round(end, 2),
        "timestamp_label": _hms(start),
    }
    # 매칭 세그먼트 텍스트(STT 결과 또는 caption) — preview 우선, 없으면 text
    snippet = (top.get("preview") or top.get("text") or top.get("caption") or "").strip()
    if snippet:
        out["snippet"] = snippet[:200]
    return out


def _img_location(trichef_id: str, query: str = "") -> dict | None:
    """이미지의 캡션 텍스트 + 쿼리 매칭 줄 추출.

    extracted_DB/Img/captions/<key>.json 또는 .txt 에서 BLIP/Qwen 캡션 로드.
    캡션 안에 쿼리 토큰 매칭 줄 + 200자 snippet 반환.
    """
    if not trichef_id:
        return None
    try:
        from config import PATHS
        cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
        # 매칭: <key>.json (e.g. "staged/abcd1234/foo.jpg.json")
        # key 의 / → __ 또는 그대로 — 두 형식 모두 시도
        candidates = [
            cap_dir / f"{trichef_id}.json",
            cap_dir / f"{trichef_id.replace('/', '__')}.json",
            cap_dir / f"{Path(trichef_id).name}.json",
            cap_dir / f"{trichef_id}.txt",
            cap_dir / f"{Path(trichef_id).name}.txt",
        ]
        cap_text = ""
        for cp in candidates:
            if cp.is_file():
                try:
                    if cp.suffix == ".json":
                        data = json.loads(cp.read_text(encoding="utf-8"))
                        # caption_3stage 형식 또는 단일 caption 형식
                        if isinstance(data, dict):
                            cap_text = " ".join(filter(None, (
                                data.get("caption", ""),
                                data.get("L1", ""),
                                data.get("L2", ""),
                                data.get("L3", ""),
                            ))).strip()
                        else:
                            cap_text = str(data).strip()
                    else:
                        cap_text = cp.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
                if cap_text:
                    break
        if not cap_text:
            return None
        out: dict[str, Any] = {"caption": cap_text[:300]}
        if query:
            line_match = _find_line_with_query(cap_text, query)
            if line_match:
                out["snippet"] = line_match.get("snippet", "")
        return out
    except Exception as e:
        logger.debug(f"[location_resolver] image 캡션 추출 실패: {e}")
        return None


def extract_location(result: dict[str, Any], query: str = "") -> dict | None:
    """결과 dict 1개 → location dict (또는 None).

    domain 판정은 result["file_type"] / result["trichef_domain"] 우선 순위.
    query 가 있으면 doc 의 line/snippet, image 의 매칭 캡션 줄도 채움.
    """
    file_type = (result.get("file_type") or "").lower()

    if file_type == "doc":
        return _doc_location(result.get("trichef_id") or "", query)

    if file_type in ("video", "audio"):
        return _av_location(result.get("segments") or [])

    if file_type == "image":
        return _img_location(result.get("trichef_id") or "", query)

    return None
