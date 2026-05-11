"""routes/export_pdf.py — 검색 결과 PDF 내보내기.

POST /api/export/pdf
    Body: { query, results, save_path?, max_per_type? }

PDF 구성:
  표지 (쿼리 / 날짜 / 타입별 개수 요약)
  섹션별 리스트 형식: [썸네일] | 파일명 / 경로 / 점수 / 스니펫

썸네일:
  - 이미지/문서: PIL (5MB 이하)
  - 동영상: ffmpeg 3초 프레임 (타임아웃 3초)
  - 음성/BGM: 타입 아이콘 텍스트
  ★ ThreadPoolExecutor 병렬 사전 로드 → 순차 대기 없이 전체 소요 = 단일 최대값
"""
from __future__ import annotations

import io
import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

logger = logging.getLogger(__name__)
export_pdf_bp = Blueprint("export_pdf", __name__, url_prefix="/api/export")

# ── 상수 ─────────────────────────────────────────────────────────────────
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\NanumGothic.ttf",
    r"/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    r"/usr/share/fonts/nanum/NanumGothic.ttf",
]

_TYPE_ORDER  = ["image", "doc", "video", "audio", "bgm"]
_TYPE_LABELS = {"image": "이미지", "doc": "문서", "video": "동영상", "audio": "음성", "bgm": "BGM"}
_TYPE_ICONS  = {"image": "IMG", "doc": "DOC", "video": "VID", "audio": "MIC", "bgm": "BGM"}
_TYPE_COLORS = {
    "image": (100, 180, 255),
    "doc":   ( 80, 140, 220),
    "video": (180, 100, 255),
    "audio": (100, 200, 150),
    "bgm":   (255, 160,  80),
}

A4_W, A4_H  = 210, 297
MARGIN      = 12
THUMB_W     = 32
ROW_H       = 26
SECTION_H   = 10
HEADER_H    = 8
FOOTER_H    = 10

_MAX_IMG_BYTES = 5 * 1024 * 1024


# ── 헬퍼 ─────────────────────────────────────────────────────────────────
def _find_font() -> str | None:
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def _norm_type(ft: str) -> str:
    return {"doc_page": "doc", "movie": "video", "music": "audio"}.get(
        (ft or "").lower(), (ft or "").lower()
    )


def _group(results: list[dict]) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = {t: [] for t in _TYPE_ORDER}
    for r in results:
        t = _norm_type(r.get("file_type", ""))
        if t in g:
            g[t].append(r)
    return g


def _trunc(s: str, n: int) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt_time(sec) -> str:
    try:
        s = int(float(sec))
        return f"{s // 60:02d}:{s % 60:02d}"
    except Exception:
        return str(sec)


def _sigm_calibrated(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-((x + 3.0) / 3.0)))


def _score_strs(item: dict) -> tuple[str, str, str]:
    dense  = item.get("dense")
    sim_str = f"{dense * 100:.1f}%" if dense is not None else "—"

    rerank = item.get("rerank_score") or item.get("rerank")
    if rerank is not None:
        try:
            acc_str = f"{_sigm_calibrated(float(rerank)) * 100:.1f}%"
        except Exception:
            acc_str = "—"
    else:
        acc_str = "—"

    conf     = item.get("confidence") or item.get("similarity") or 0
    conf_str = f"{conf * 100:.1f}%"
    return sim_str, acc_str, conf_str


def _snippet_text(item: dict) -> str:
    snippet = (item.get("snippet") or "").strip()
    if snippet:
        return snippet.split("\n")[0]
    segs = item.get("segments") or []
    if segs:
        seg0  = segs[0]
        label = (seg0.get("text") or seg0.get("caption") or seg0.get("preview") or "").strip()
        s     = seg0.get("start")
        ts    = f"[{_fmt_time(s)}] " if s is not None else ""
        if label:
            return ts + label
    bgm_title = item.get("bgm_title") or ""
    if bgm_title:
        artist = item.get("bgm_artist") or ""
        return f"{bgm_title}" + (f" — {artist}" if artist else "")
    return ""


# ── 썸네일 로드 ───────────────────────────────────────────────────────────
def _video_thumb_cache_path(file_path: str) -> Path | None:
    """동영상 썸네일 캐시 파일 경로 (extracted_DB/Movie/{stem}_pdf_thumb.jpg)."""
    try:
        import hashlib as _hl
        from config import EXTRACTED_DB_VIDEO as _EV
        stem = Path(file_path).stem
        h    = _hl.md5(file_path.encode()).hexdigest()[:12]
        return _EV / f"{stem}_{h}_pdf_thumb.jpg"
    except Exception:
        return None


def _extract_video_thumb(file_path: str, max_dim: int = 160) -> bytes | None:
    """동영상 썸네일 — 캐시 파일만 사용 (PDF 생성 중 ffmpeg 호출 없음 → 즉시 반환).

    캐시 없으면 None → VID 아이콘 표시.
    캐시 생성은 /api/export/warmup-thumb 엔드포인트에서 비동기 처리.
    """
    cache_path = _video_thumb_cache_path(file_path)
    if cache_path and cache_path.exists():
        try:
            data = cache_path.read_bytes()
            if data:
                return data
        except Exception:
            pass
    return None


def _warmup_video_thumb_sync(file_path: str, max_dim: int = 160) -> bool:
    """썸네일 캐시 생성 (warmup 엔드포인트 전용, ffmpeg 호출).
    성공 True / 실패 False.
    """
    cache_path = _video_thumb_cache_path(file_path)
    if not cache_path:
        return False
    if cache_path.exists():
        return True

    import subprocess, tempfile
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tmp_path = tf.name
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", "1", "-i", file_path,
             "-frames:v", "1", "-vf", f"scale={max_dim}:-2", "-q:v", "5", tmp_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if r.returncode == 0 and Path(tmp_path).exists():
            data = Path(tmp_path).read_bytes()
            if data:
                cache_path.write_bytes(data)
                return True
    except Exception as ex:
        logger.debug(f"[export_pdf] warmup ffmpeg 실패: {ex}")
    finally:
        try:
            if tmp_path:
                os.unlink(tmp_path)
        except Exception:
            pass
    return False


def _load_preview(item: dict, max_dim: int = 160) -> bytes | None:
    """썸네일 바이트 반환 (image/doc: PIL, video: ffmpeg, audio/bgm: None)."""
    ft = _norm_type(item.get("file_type", ""))

    if ft == "video":
        fp = (item.get("file_path") or "").strip()
        if fp and Path(fp).exists():
            return _extract_video_thumb(fp, max_dim)
        return None

    if ft not in ("image", "doc"):
        return None

    paths_to_try: list[str] = []

    if ft == "image":
        fp = (item.get("file_path") or "").strip()
        if not fp:
            return None
        try:
            if Path(fp).stat().st_size > _MAX_IMG_BYTES:
                return None
        except Exception:
            pass
        paths_to_try.append(fp)

    elif ft == "doc":
        import re as _re
        tid = (item.get("trichef_id") or "").strip()
        m   = _re.match(r"^page_images/(.+)/p(\d+)\.(jpg|png)$", tid)
        if m:
            try:
                from config import EXTRACTED_DB_DOC as _EDD
                stem, page_str, ext = m.group(1), m.group(2), m.group(3)
                paths_to_try.append(str(_EDD / "page_images" / stem / f"p{page_str}.{ext}"))
            except Exception:
                pass
        if not paths_to_try:
            fp = (item.get("file_path") or "").strip()
            if fp:
                paths_to_try.append(fp)

    for p in paths_to_try:
        try:
            from PIL import Image as PILImage
            with PILImage.open(p) as img:
                img.thumbnail((max_dim, max_dim))
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=75)
                return buf.getvalue()
        except Exception as ex:
            logger.debug(f"[export_pdf] PIL 실패 {p!r}: {ex}")

    return None


def _preload_thumbs(items: list[dict], max_dim: int = 160) -> list[bytes | None]:
    """★ ThreadPoolExecutor 병렬 사전 로드 + 글로벌 타임아웃.

    - 개별 ffmpeg: 타임아웃 2초 (내부에서 kill)
    - 전체 썸네일 로드: 최대 8초 글로벌 타임아웃 (걸리면 나머지 None 처리)
    """
    from concurrent.futures import wait as _wait, FIRST_EXCEPTION as _FE
    result_map: dict[int, bytes | None] = {}
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="pdf-thumb") as ex:
        futures = {ex.submit(_load_preview, item, max_dim): i
                   for i, item in enumerate(items)}
        # ★ 전체 최대 8초 대기 — 초과하면 남은 것은 None 처리
        done, not_done = _wait(futures, timeout=8)
        for fut in done:
            idx = futures[fut]
            try:
                result_map[idx] = fut.result()
            except Exception:
                result_map[idx] = None
        # 시간 초과된 future → None
        for fut in not_done:
            result_map[futures[fut]] = None
            fut.cancel()
    return [result_map.get(i) for i in range(len(items))]


# ── PDF 클래스 ────────────────────────────────────────────────────────────
def _make_pdf(use_kr: bool, font_path: str | None):
    from fpdf import FPDF

    class ReportPDF(FPDF):
        def __init__(self):
            super().__init__("P", "mm", "A4")
            self._use_kr = use_kr

        def footer(self):
            self.set_y(-10)
            self._sf(7)
            self.set_text_color(120, 120, 140)
            self.cell(0, 6, f"Insight 검색 리포트  |  p.{self.page_no()}", align="C")

        def _sf(self, size: int, bold: bool = False):
            if self._use_kr:
                self.set_font("kr", style="B" if bold else "", size=size)
            else:
                self.set_font("Helvetica", style="B" if bold else "", size=size)

        def dark_bg(self):
            self.set_fill_color(14, 19, 34)
            self.rect(0, 0, A4_W, A4_H, "F")

        def color_bar(self, r, g, b, height=3):
            self.set_fill_color(r, g, b)
            self.rect(0, 0, A4_W, height, "F")

    pdf = ReportPDF()
    pdf.set_auto_page_break(False)

    if font_path and use_kr:
        try:
            pdf.add_font("kr", fname=font_path)
            pdf.add_font("kr", style="B", fname=font_path)
        except Exception as fe:
            logger.warning(f"[export_pdf] 폰트 로드 실패: {fe}")
            pdf._use_kr = False

    return pdf


# ── 항목 행 렌더러 ────────────────────────────────────────────────────────
def _render_row(pdf, item: dict, ry: float, ft: str,
                thumb_bytes: bytes | None = None) -> None:
    """리스트 한 행 (썸네일 bytes 는 호출 전 사전 로드하여 전달)."""
    rc, gc, bc = _TYPE_COLORS.get(ft, (200, 200, 200))
    pad          = 2.5
    text_x       = MARGIN + THUMB_W + pad * 2
    text_w       = A4_W - MARGIN - text_x - pad
    thumb_inner_h = ROW_H - pad * 2

    # 행 배경
    pdf.set_fill_color(20, 27, 46)
    pdf.set_draw_color(40, 55, 88)
    pdf.rect(MARGIN, ry, A4_W - MARGIN * 2, ROW_H - 1, "FD")

    # 좌측 컬러 바
    pdf.set_fill_color(rc, gc, bc)
    pdf.rect(MARGIN, ry, 1.5, ROW_H - 1, "F")

    # 썸네일 영역
    thumb_x = MARGIN + 2.5
    if thumb_bytes:
        try:
            pdf.image(io.BytesIO(thumb_bytes), x=thumb_x, y=ry + pad,
                      w=THUMB_W - 2, h=thumb_inner_h)
        except Exception as ie:
            logger.debug(f"[export_pdf] 이미지 삽입 오류: {ie}")
            thumb_bytes = None

    if not thumb_bytes:
        icon_label = _TYPE_ICONS.get(ft, ft.upper())
        pdf.set_fill_color(rc // 4, gc // 4, bc // 4)
        pdf.rect(thumb_x, ry + pad, THUMB_W - 2, thumb_inner_h, "F")
        pdf.set_xy(thumb_x, ry + pad + thumb_inner_h / 2 - 3)
        pdf._sf(10, bold=True)
        pdf.set_text_color(rc, gc, bc)
        pdf.cell(THUMB_W - 2, 6, icon_label, align="C")

    # 파일명
    fname = item.get("file_name") or Path(item.get("file_path", "") or "").name or "?"
    pdf.set_xy(text_x, ry + pad)
    pdf._sf(8, bold=True)
    pdf.set_text_color(220, 228, 255)
    pdf.cell(text_w, 5, _trunc(fname, 55))

    # 경로
    fpath = (item.get("file_path") or "").strip()
    pdf.set_xy(text_x, ry + pad + 5.5)
    pdf._sf(6)
    pdf.set_text_color(110, 120, 150)
    pdf.cell(text_w, 4, _trunc(fpath, 75))

    # 점수
    sim_s, acc_s, conf_s = _score_strs(item)
    pdf.set_xy(text_x, ry + pad + 10.5)
    pdf._sf(6)
    pdf.set_text_color(140, 160, 200)
    pdf.cell(text_w, 4, f"유사도 {sim_s}   정확도 {acc_s}   신뢰도 {conf_s}")

    # 스니펫
    snippet = _snippet_text(item)
    if snippet:
        pdf.set_xy(text_x, ry + pad + 16)
        pdf._sf(6)
        pdf.set_text_color(120, 130, 158)
        pdf.cell(text_w, 4, _trunc(snippet, 80))


# ── PDF 빌더 ──────────────────────────────────────────────────────────────
def _build_pdf(query: str, results: list[dict], max_per_type: int = 50) -> bytes:
    font_path = _find_font()
    use_kr    = font_path is not None
    pdf       = _make_pdf(use_kr, font_path)

    groups = _group(results)
    total  = len(results)
    ts_str = datetime.now().strftime("%Y년 %m월 %d일  %H:%M")

    # ── ★ 병렬 썸네일 사전 로드 ──────────────────────────────────────────
    # 섹션 순서대로 flatten → 병렬 로드 → index로 되찾기
    flat_items: list[dict] = []
    flat_meta:  list[tuple[str, int]] = []   # (file_type, local_idx)
    for t in _TYPE_ORDER:
        items = groups.get(t, [])[:max_per_type]
        for local_i, item in enumerate(items):
            flat_items.append(item)
            flat_meta.append((t, local_i))

    # ★ 병렬 로드 (subprocess 없이 PIL만 → deadlock 위험 없음)
    # - video: _extract_video_thumb 가 캐시만 사용 (즉시 반환)
    # - image/doc: PIL Image (CPU-bound이지만 GIL이 I/O 시 해제되어 병렬화 효과)
    t_thumb0 = time.time()
    logger.info(f"[export_pdf] 썸네일 병렬 로드 시작: {len(flat_items)}개")
    flat_thumbs: list[bytes | None] = [None] * len(flat_items)
    if flat_items:
        from concurrent.futures import wait as _wait
        with ThreadPoolExecutor(max_workers=min(8, len(flat_items)),
                                thread_name_prefix="pdf-thumb") as ex:
            futures = {ex.submit(_load_preview, _it, 160): i
                       for i, _it in enumerate(flat_items)}
            # 글로벌 6초 타임아웃: 그 안에 못 끝나면 나머지 None 처리
            done, not_done = _wait(futures, timeout=6)
            for fut in done:
                try:
                    flat_thumbs[futures[fut]] = fut.result()
                except Exception:
                    pass
            for fut in not_done:
                fut.cancel()
    logger.info(f"[export_pdf] 썸네일 로드 완료 ({time.time()-t_thumb0:.2f}s)")

    # flat_index → thumb_bytes 맵
    thumb_map: dict[int, bytes | None] = {i: b for i, b in enumerate(flat_thumbs)}

    # ── 표지 ──────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.dark_bg()

    pdf.set_y(48)
    pdf._sf(9)
    pdf.set_text_color(100, 120, 160)
    pdf.cell(0, 7, "INSIGHT", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf._sf(26, bold=True)
    pdf.set_text_color(230, 235, 255)
    pdf.cell(0, 13, "검색 결과 리포트", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(3)
    pdf.set_draw_color(60, 80, 130)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(5)

    pdf._sf(17)
    pdf.set_text_color(100, 180, 255)
    pdf.cell(0, 9, f'"{_trunc(query, 40)}"', align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)
    pdf._sf(10)
    pdf.set_text_color(140, 140, 160)
    pdf.cell(0, 7, ts_str, align="C", new_x="LMARGIN", new_y="NEXT")

    # 요약 카드
    pdf.ln(12)
    card_x, card_w = 55, 100
    card_h = 12 + sum(1 for t in _TYPE_ORDER if groups.get(t)) * 9 + 12
    pdf.set_fill_color(22, 30, 52)
    pdf.set_draw_color(50, 70, 110)
    pdf.rect(card_x, pdf.get_y(), card_w, card_h, "FD")

    pdf.set_xy(card_x, pdf.get_y() + 6)
    pdf._sf(11, bold=True)
    pdf.set_text_color(200, 210, 255)
    pdf.cell(card_w, 8, f"총 {total}건", align="C", new_x="LMARGIN", new_y="NEXT")

    for t in _TYPE_ORDER:
        cnt = len(groups.get(t, []))
        if cnt == 0:
            continue
        rc, gc, bc = _TYPE_COLORS.get(t, (200, 200, 200))
        pdf.set_x(card_x + 14)
        pdf._sf(10)
        pdf.set_text_color(rc, gc, bc)
        pdf.cell(52, 8, _TYPE_LABELS.get(t, t), new_x="RIGHT", new_y="TOP")
        pdf.set_text_color(220, 220, 240)
        pdf.cell(card_w - 52 - 14, 8, f"{cnt}건", align="R", new_x="LMARGIN", new_y="NEXT")

    # ── 섹션 리스트 ──────────────────────────────────────────────────────
    CONTENT_TOP = HEADER_H + SECTION_H
    CONTENT_BOT = A4_H - FOOTER_H
    rows_per_page = max(1, int((CONTENT_BOT - CONTENT_TOP) / ROW_H))

    flat_idx = 0   # flat_items 의 현재 위치
    for t in _TYPE_ORDER:
        items = groups.get(t, [])[:max_per_type]
        if not items:
            flat_idx += 0
            continue

        rc, gc, bc = _TYPE_COLORS.get(t, (200, 200, 200))
        label      = _TYPE_LABELS.get(t, t)

        for page_start in range(0, len(items), rows_per_page):
            page_items = items[page_start: page_start + rows_per_page]

            pdf.add_page()
            pdf.dark_bg()
            pdf.color_bar(rc, gc, bc, height=3)

            pdf.set_xy(MARGIN, 5)
            pdf._sf(11, bold=True)
            pdf.set_text_color(rc, gc, bc)
            end_idx = min(page_start + rows_per_page, len(items))
            pdf.cell(0, 7,
                     f"{label}  {page_start + 1}–{end_idx} / 총 {len(items)}건",
                     new_x="LMARGIN", new_y="NEXT")

            pdf.set_draw_color(rc // 2, gc // 2, bc // 2)
            pdf.line(MARGIN, HEADER_H, A4_W - MARGIN, HEADER_H)

            for i, item in enumerate(page_items):
                ry         = CONTENT_TOP + i * ROW_H
                item_flat  = flat_idx + page_start + i
                _render_row(pdf, item, ry, t, thumb_map.get(item_flat))

        flat_idx += len(items)

    return bytes(pdf.output())


# ── 엔드포인트 ────────────────────────────────────────────────────────────
@export_pdf_bp.post("/pdf")
def generate_pdf():
    try:
        body         = request.get_json(silent=True) or {}
        query        = (body.get("query") or "검색 결과").strip()
        results      = body.get("results") or []
        save_path    = (body.get("save_path") or "").strip()
        max_per_type = int(body.get("max_per_type") or 50)

        if not results:
            return jsonify({"error": "results 가 비어 있습니다."}), 400

        logger.info(f"[export_pdf] 생성 시작: query={query!r} n={len(results)}")
        t0 = time.time()

        pdf_bytes = _build_pdf(query, results, max_per_type=max_per_type)

        elapsed = time.time() - t0
        logger.info(f"[export_pdf] 완료: {len(pdf_bytes)//1024}KB ({elapsed:.2f}s)")

        # ASCII만 사용 — HTTP 헤더에 한글 들어가면 fetch 'Failed to fetch' 발생.
        # 한글 등 비-ASCII 문자는 제거.
        safe_q = "".join(c for c in query if (c.isascii() and (c.isalnum() or c in " _-")))[:28].strip()
        if not safe_q:
            safe_q = "search"
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname  = f"insight_{safe_q}_{ts}.pdf"

        if save_path:
            out = Path(save_path)
            if out.is_dir():
                out = out / fname
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(pdf_bytes)
            return jsonify({
                "ok": True,
                "saved_path": str(out),
                "size_kb": len(pdf_bytes) // 1024,
                "file_name": fname,
            })

        import tempfile
        tmp_dir  = Path(tempfile.gettempdir()) / "insight_pdf"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / fname
        tmp_path.write_bytes(pdf_bytes)

        resp = send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=fname,
        )
        # 한글 경로 → URL 인코딩 (HTTP 헤더는 ASCII만 허용 → 한글 그대로 넣으면 fetch 거부)
        from urllib.parse import quote as _q
        resp.headers["X-Saved-Path"]                  = _q(str(tmp_path), safe=":/\\")
        resp.headers["Access-Control-Expose-Headers"] = "X-Saved-Path"
        return resp

    except Exception as e:
        logger.exception(f"[export_pdf] 오류: {e}")
        return jsonify({"error": str(e)}), 500


@export_pdf_bp.post("/warmup-thumbs")
def warmup_thumbs():
    """동영상 썸네일 백그라운드 사전 캐싱.

    POST { "paths": ["C:\\...\\video.mkv", ...] }
    → 즉시 202 반환, 백그라운드 스레드에서 ffmpeg 캐시 생성.
    PDF 생성 전 검색 결과가 나오면 프론트엔드가 호출.
    """
    try:
        body  = request.get_json(silent=True) or {}
        paths = [p for p in (body.get("paths") or []) if isinstance(p, str) and p.strip()]
        if not paths:
            return jsonify({"ok": True, "queued": 0})

        # 이미 캐시된 것은 제외
        missing = [p for p in paths if not (_video_thumb_cache_path(p) or Path("")).exists()]

        def _bg():
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb-warm") as ex:
                futures = [ex.submit(_warmup_video_thumb_sync, p) for p in missing]
                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception:
                        pass

        if missing:
            import threading
            threading.Thread(target=_bg, daemon=True).start()
            logger.info(f"[export_pdf] warmup 시작: {len(missing)}개")

        return jsonify({"ok": True, "queued": len(missing)})
    except Exception as e:
        logger.exception(f"[warmup_thumbs] 오류: {e}")
        return jsonify({"error": str(e)}), 500


@export_pdf_bp.post("/open-file")
def open_file():
    try:
        body      = request.get_json(silent=True) or {}
        file_path = (body.get("path") or "").strip()
        if not file_path:
            return jsonify({"error": "path 가 비어 있습니다."}), 400
        p = Path(file_path)
        if not p.exists():
            return jsonify({"error": f"파일을 찾을 수 없습니다: {file_path}"}), 404
        import os as _os
        _os.startfile(str(p))
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception(f"[open_file] 오류: {e}")
        return jsonify({"error": str(e)}), 500
