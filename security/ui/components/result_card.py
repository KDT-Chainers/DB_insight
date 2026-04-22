"""
ui/components/result_card.py
──────────────────────────────────────────────────────────────────────────────
검색 결과 카드 HTML 렌더러.

Gradio gr.HTML 위젯에 삽입할 카드 HTML 문자열을 생성한다.

ABC Rule: [C] 렌더링 출력 생성만 담당.
          원본 파일을 절대 수정하지 않는다.
          DANGEROUS 레이블에서는 카드를 렌더링하지 않는다.

v2 변경점:
  - `masked` 키 → `display_masked` 키로 교체 (단일 인덱스 구조)
  - display_masked=True AND has_pii=True 일 때만 UI 마스킹 렌더링
  - 원문은 저장소에서 변경되지 않음, 렌더링 시점에만 마스킹 사본 생성
"""
from __future__ import annotations

import base64
import html
import io
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ui.components.preview_renderer import render_masked_text

# ── 카드 공통 스타일 (다크 모드) ──────────────────────────────────────────────
_CARD_CSS = """
<style>
.result-card {
    border: 1px solid #2d3748;
    border-radius: 10px;
    padding: 16px;
    margin: 10px 0;
    background: #1a202c;
    box-shadow: 0 2px 12px rgba(0,0,0,0.4);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #e2e8f0;
}
.result-card.sensitive {
    border-left: 4px solid #f6ad55;
    background: #1f1a10;
}
.result-card.normal {
    border-left: 4px solid #48bb78;
    background: #0f1a15;
}
.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
}
.card-filename {
    font-weight: 700;
    font-size: 1.0em;
    color: #f7fafc;
}
.card-page {
    font-size: 0.85em;
    color: #a0aec0;
    background: #2d3748;
    padding: 2px 8px;
    border-radius: 12px;
}
.card-path {
    font-size: 0.78em;
    color: #718096;
    font-family: monospace;
    word-break: break-all;
    margin-bottom: 10px;
    padding: 6px 8px;
    background: #171923;
    border-radius: 6px;
    border: 1px solid #2d3748;
}
.card-preview {
    background: #171923;
    border: 1px solid #2d3748;
    border-radius: 6px;
    padding: 12px;
    font-size: 0.9em;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 200px;
    overflow-y: auto;
    margin-bottom: 10px;
    color: #cbd5e0;
}
.card-preview .masked-value {
    background: #744210;
    padding: 1px 5px;
    border-radius: 3px;
    font-family: monospace;
    color: #fbd38d;
    font-weight: 600;
}
.card-pii-badges {
    margin-bottom: 10px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}
.pii-badge {
    font-size: 0.75em;
    padding: 2px 8px;
    border-radius: 12px;
    background: #744210;
    color: #fbd38d;
    font-weight: 600;
}
.card-actions {
    display: flex;
    gap: 8px;
    margin-top: 8px;
}
.score-label {
    font-size: 0.78em;
    color: #4a5568;
    margin-left: auto;
    align-self: center;
}
</style>
"""

_CSS_INJECTED = False


def _inject_css_once() -> str:
    """CSS는 첫 번째 카드에만 삽입한다."""
    global _CSS_INJECTED
    if not _CSS_INJECTED:
        _CSS_INJECTED = True
        return _CARD_CSS
    return ""


def reset_css_flag() -> None:
    """카드 렌더링 사이클 시작 시 CSS 플래그 초기화."""
    global _CSS_INJECTED
    _CSS_INJECTED = False


# ──────────────────────────────────────────────────────────────────────────────
# 이미지 모자이크 렌더러
# ──────────────────────────────────────────────────────────────────────────────

def _render_image_preview(
    image_path: str,
    pii_regions: List[List],
    apply_mosaic: bool,
) -> str:
    """
    이미지를 로드하여 PII 영역에 모자이크를 적용한 후 base64 <img> 태그를 반환한다.

    Args:
        image_path:  원본 이미지 파일 경로
        pii_regions: 모자이크할 bbox 목록 [[[x1,y1],[x2,y1],[x2,y2],[x1,y2]], ...]
        apply_mosaic: True이면 pii_regions 에 픽셀화 적용

    Returns:
        HTML <img> 태그 (base64 inline), 실패 시 오류 메시지 div
    """
    if not image_path:
        return '<div style="color:#718096;font-style:italic;">이미지 경로 없음</div>'

    try:
        from PIL import Image

        # HEIC 지원 등록
        _ext = Path(image_path).suffix.lower()
        if _ext in {".heic", ".heif"}:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass

        if not Path(image_path).exists():
            return (
                f'<div style="color:#fc8181;font-size:0.85em;">'
                f'이미지 파일을 찾을 수 없습니다: {html.escape(image_path)}</div>'
            )

        img = Image.open(image_path).convert("RGB")

        # 모자이크 적용
        if apply_mosaic and pii_regions:
            for bbox in pii_regions:
                x_coords = [p[0] for p in bbox]
                y_coords = [p[1] for p in bbox]
                x1 = int(min(x_coords))
                y1 = int(min(y_coords))
                x2 = int(max(x_coords))
                y2 = int(max(y_coords))

                if x2 > x1 and y2 > y1:
                    region = img.crop((x1, y1, x2, y2))
                    rw, rh  = region.size
                    # 10x10 픽셀로 축소 후 원래 크기로 확대 → 픽셀화 모자이크
                    small   = region.resize((max(1, rw // 10), max(1, rh // 10)), Image.BOX)
                    mosaic  = small.resize((rw, rh), Image.NEAREST)
                    img.paste(mosaic, (x1, y1))

        # 표시용으로 너무 크면 축소 (최대 가로 800px)
        w, h = img.size
        if w > 800:
            ratio = 800 / w
            img = img.resize((800, int(h * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()

        return (
            f'<img src="data:image/jpeg;base64,{b64}" '
            f'style="max-width:100%;border-radius:6px;margin:6px 0;display:block;" />'
        )

    except Exception as exc:
        return (
            f'<div style="color:#fc8181;font-size:0.85em;">'
            f'이미지 로딩 오류: {html.escape(str(exc))}</div>'
        )


# ── 공개 API ──────────────────────────────────────────────────────────────────

def render_result_card(
    chunk_meta: Dict[str, Any],
    label: str,
    pii_results: Optional[List[Any]] = None,
) -> str:
    """
    청크 메타데이터로 검색 결과 카드 HTML을 생성한다.

    규칙:
      - NORMAL    → 마스킹 텍스트 표시
      - SENSITIVE → 마스킹 텍스트 + 경고 배지 표시
      - DANGEROUS → 빈 문자열 반환 (카드 렌더링 금지)

    Args:
        chunk_meta:  검색 결과 dict
                     ({file_name, source_path, source_page, text,
                       has_pii, pii_types, display_masked, score})
        label:       보안 레이블 ("NORMAL" / "SENSITIVE" / "DANGEROUS")
        pii_results: Presidio AnalyzerResult 리스트 (마스킹 위치 개선용, 없으면 정규식만 사용)

    Returns:
        Gradio gr.HTML에 삽입할 HTML 문자열
    """
    label_upper = label.upper()

    # ── DANGEROUS: 파일명·경로만 표시, 내용 차단 ────────────────────────────
    if label_upper == "DANGEROUS" or chunk_meta.get("_blocked"):
        file_name   = html.escape(chunk_meta.get("file_name") or chunk_meta.get("doc_name") or "알 수 없음")
        source_path = chunk_meta.get("source_path") or ""
        path_display = html.escape(source_path) if source_path else "(경로 없음)"
        css = _inject_css_once()
        return f"""{css}
<div class="result-card" style="border-left:4px solid #e53e3e;background:#1a0a0a;">
  <div class="card-header">
    <span class="card-filename">⛔ {file_name}</span>
    <span class="card-page" style="background:#742a2a;color:#feb2b2;">차단됨</span>
  </div>
  <div class="card-path">📂 {path_display}</div>
  <div class="card-preview" style="color:#fc8181;font-style:italic;">
    🔒 내용은 보안 정책으로 제한됩니다.<br>
    파일 경로를 직접 탐색기에서 열어 확인하세요.
  </div>
  <div class="card-actions">{_open_path_button_html(source_path)}</div>
</div>"""

    card_class  = "sensitive" if label_upper == "SENSITIVE" else "normal"

    file_name   = html.escape(chunk_meta.get("file_name") or chunk_meta.get("doc_name") or "알 수 없음")
    source_path = chunk_meta.get("source_path") or ""
    page_num    = chunk_meta.get("source_page", "?")
    score       = chunk_meta.get("score")
    has_pii     = chunk_meta.get("has_pii", False)
    # display_masked + has_pii 모두 True일 때만 UI 마스킹 (원본 불변)
    is_masked   = bool(chunk_meta.get("display_masked") or chunk_meta.get("masked")) and has_pii
    pii_types   = chunk_meta.get("pii_types") or []
    raw_text    = chunk_meta.get("text", "")

    # ── 이미지 파일 여부 ──────────────────────────────────────────────────────
    is_image    = bool(chunk_meta.get("is_image", False))
    image_path  = chunk_meta.get("image_path", "") or ""
    pii_regions = chunk_meta.get("pii_regions") or []

    # 파일 경로 표시
    path_display = html.escape(source_path) if source_path else "(경로 없음)"

    # PII 유형 배지
    pii_badges_html = ""
    if pii_types:
        badges = "".join(
            f'<span class="pii-badge">{html.escape(str(t))}</span>'
            for t in pii_types
        )
        pii_badges_html = f'<div class="card-pii-badges">{badges}</div>'

    # 점수 표시 (코사인 유사도 0~1, 높을수록 관련성 높음)
    score_html = ""
    if score is not None:
        pct = float(score) * 100
        score_html = f'<span class="score-label">관련도 {pct:.1f}%</span>'

    # ── 미리보기 콘텐츠 (이미지 vs 텍스트) ──────────────────────────────────
    if is_image and image_path:
        # 이미지: 원본 표시 + PII 영역 모자이크 (display_masked 시)
        img_html    = _render_image_preview(image_path, pii_regions, is_masked)
        preview_html = f'<div class="card-preview" style="padding:4px;background:#0d1117;">{img_html}</div>'
        icon = "🖼️"
    else:
        # 텍스트: 마스킹 렌더링
        display_text = render_masked_text(raw_text, pii_results) if is_masked else raw_text
        display_text_escaped = html.escape(display_text)
        import re
        display_text_html = re.sub(
            r"(●{2,})",
            r'<span class="masked-value">\1</span>',
            display_text_escaped,
        )
        preview_html = f'<div class="card-preview">{display_text_html}</div>'
        icon = "📄"

    # 카드 HTML 조립
    css = _inject_css_once()
    card_html = f"""{css}
<div class="result-card {card_class}">
  <div class="card-header">
    <span class="card-filename">{icon} {file_name}</span>
    <span class="card-page">p.{page_num}</span>
  </div>
  <div class="card-path">📂 {path_display}</div>
  {pii_badges_html}
  {preview_html}
  <div class="card-actions">
    {_open_path_button_html(source_path)}
    {score_html}
  </div>
</div>"""

    return card_html


def _open_path_button_html(source_path: str) -> str:
    """
    플랫폼별 [경로 열기] 버튼용 HTML을 생성한다.
    버튼 클릭 시 JavaScript를 통해 서버에 경로를 전달하는 대신,
    경로를 복사할 수 있는 링크 형태로 제공한다.
    (Gradio 내에서 subprocess는 별도 버튼으로 처리)
    """
    if not source_path:
        return ""
    safe_path = html.escape(source_path)
    return (
        f'<span style="font-size:0.82em;color:#4a5568;" title="{safe_path}">'
        f"📂 {Path(source_path).name}</span>"
    )


def build_sources_html(
    chunks: List[Dict[str, Any]],
    label: str,
    pii_results: Optional[List[Any]] = None,
) -> str:
    """
    복수 청크를 카드 HTML 목록으로 렌더링한다.

    Args:
        chunks:      검색 결과 청크 리스트
        label:       보안 레이블
        pii_results: 마스킹 위치 정보 (선택)

    Returns:
        Gradio gr.HTML에 삽입할 전체 HTML 문자열
    """
    if not chunks:
        return ""

    reset_css_flag()  # CSS 중복 삽입 방지

    parts = []
    for chunk in chunks:
        card = render_result_card(chunk, label, pii_results)
        if card:
            parts.append(card)

    if not parts:
        return ""

    count = len(parts)
    header = (
        f'<div style="font-size:0.9em;color:#718096;margin-bottom:6px;">'
        f"📑 검색 소스 {count}개</div>"
    )
    return header + "\n".join(parts)


def open_file_in_explorer(source_path: str) -> str:
    """
    [경로 열기] 버튼 클릭 시 플랫폼별로 파일 탐색기를 연다.
    원본 파일을 수정하지 않으며, 탐색기에서 파일을 선택 상태로 열기만 한다.

    Args:
        source_path: 열 파일의 절대 경로

    Returns:
        성공/실패 메시지 문자열
    """
    if not source_path:
        return "경로가 없습니다."
    path = Path(source_path)
    if not path.exists():
        return f"파일을 찾을 수 없습니다: {source_path}"

    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            subprocess.Popen(["open", "-R", str(path)])
            return f"Finder에서 열기: {path.name}"
        elif system == "Windows":
            subprocess.Popen(["explorer", f"/select,{path}"])
            return f"탐색기에서 열기: {path.name}"
        else:  # Linux 등
            subprocess.Popen(["xdg-open", str(path.parent)])
            return f"파일 관리자에서 열기: {path.parent}"
    except Exception as exc:
        return f"경로 열기 실패: {exc}"
