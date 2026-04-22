"""
ui/gradio_app.py
──────────────────────────────────────────────────────────────────────────────
Gradio 기반 웹 UI.

탭 구성:
  1. 📁 파일 업로드   — 파일 선택 → 자동 스캔·임베딩 → PII 감지 시 알림 모달
  2. 💬 질문 & 답변   — 질문 입력 → 보안 분류 → 정책 적용 → 답변 출력
  3. 📋 감사 로그     — 최근 업로드/질문 이벤트 표시

v3 업로드 흐름 변경:
  파일 선택 즉시 자동으로 스캔 + 임베딩 시작
  - PII 없음 → 그냥 임베딩 완료 (알림 없음)
  - PII 있음 → ⚠️ 알림 배너 + 처리 방식 선택 모달 표시
  "보안 스캔 시작" 버튼 제거
"""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, List, Optional, Tuple

import gradio as gr

from agents.orchestrator import Orchestrator
from audit.logger import AuditLogger
from security.policy import UploadPolicy
from ui.components.result_card import build_sources_html, open_file_in_explorer

# ──────────────────────────────────────────────────────────────────────────────
# 전역 오케스트레이터 (앱 시작 시 1회 초기화)
# ──────────────────────────────────────────────────────────────────────────────

_orchestrator: Optional[Orchestrator] = None
_audit: Optional[AuditLogger] = None

# 업로드 스캔 결과(복수 파일)를 브레이크 모달까지 임시 보관
_pending_scans: Optional[List[Any]] = None  # List[UploadScanResult]


def _get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator.build()
    return _orchestrator


def _get_audit() -> AuditLogger:
    global _audit
    if _audit is None:
        _audit = AuditLogger()
    return _audit


def _normalize_upload_files(file_obj: Any) -> List[Any]:
    """Gradio File 단일/복수 입력을 항상 리스트로 통일."""
    if file_obj is None:
        return []
    if isinstance(file_obj, list):
        return file_obj
    return [file_obj]


def _upload_file_path(f: Any) -> Optional[str]:
    """Gradio FileData / dict / str 에서 로컬 경로 추출."""
    if f is None:
        return None
    if isinstance(f, str):
        return f
    path = getattr(f, "name", None) or getattr(f, "path", None)
    if path:
        return str(path)
    if isinstance(f, dict):
        return str(f.get("path") or f.get("name") or "")
    return None


def _upload_policy_label(policy: str) -> str:
    """감사 로그·UI용 짧은 한글 라벨."""
    return {
        UploadPolicy.MASK_AND_EMBED:   "UI 마스킹 표시 (원문 저장)",
        UploadPolicy.SKIP_PII_CHUNKS:  "민감 청크 제외 후 임베딩",
        UploadPolicy.EMBED_ALL:        "원문 그대로 임베딩",
        UploadPolicy.CANCEL:           "취소",
    }.get(policy, policy)


# ──────────────────────────────────────────────────────────────────────────────
# 탭 1: 파일 업로드 (v3 — 자동 스캔·임베딩)
# ──────────────────────────────────────────────────────────────────────────────

def _build_file_section(scan: Any) -> str:
    """파일 한 건의 스캔 결과를 Markdown으로 요약한다."""
    if scan.error:
        return f"- ❌ `{scan.filename}` — {scan.error}"
    summary = scan.pii_summary
    if scan.has_pii:
        types_str = ", ".join(
            f"**{k}**({v})" for k, v in summary.get("pii_type_counts", {}).items()
        )
        return (
            f"- ⚠️ `{scan.filename}` — PII {summary.get('affected_chunks', 0)}개 청크 감지 "
            f"| 유형: {types_str or '-'}"
        )
    return f"- ✅ `{scan.filename}` — PII 없음 ({summary.get('total_chunks', 0)}청크)"


def _do_commit(scans: List[Any], policy_choice: str) -> Tuple[int, int, int, List[str]]:
    """
    스캔 결과 리스트를 주어진 정책으로 임베딩한다.
    Returns: (ok_files, total_chunks, embedded_chunks, detail_lines)
    """
    orch = _get_orchestrator()
    choice_map = {
        "UI 마스킹 표시 (원문 저장)": UploadPolicy.MASK_AND_EMBED,
        "마스킹 후 임베딩":           UploadPolicy.MASK_AND_EMBED,
        "민감 청크 제외 후 임베딩":   UploadPolicy.SKIP_PII_CHUNKS,
        "그대로 임베딩":              UploadPolicy.EMBED_ALL,
        "취소":                       UploadPolicy.CANCEL,
    }
    pol = choice_map.get(policy_choice, UploadPolicy.CANCEL)

    ok, total, embedded = 0, 0, 0
    lines: List[str] = []

    for scan in scans:
        if getattr(scan, "error", None):
            lines.append(f"- `{scan.filename}`: 스킵 (오류: {scan.error})")
            continue

        effective = UploadPolicy.EMBED_ALL if not scan.has_pii else pol
        note = "원문 자동" if not scan.has_pii else _upload_policy_label(effective)

        result = orch.commit_upload(scan, effective)
        if result["status"] == "cancelled":
            lines.append(f"- `{scan.filename}`: 취소됨")
            continue

        ok += 1
        total    += result["total_chunks"]
        embedded += result["embedded_chunks"]
        pii_tag   = result.get("pii_tagged", 0)
        ui_mask   = result.get("ui_masked", 0)
        lines.append(
            f"- `{scan.filename}` ({note}) — "
            f"저장 {result['embedded_chunks']}청크 / PII 태그 {pii_tag} / UI 마스킹 {ui_mask}"
        )

    return ok, total, embedded, lines


def on_file_change(file_obj):
    """
    파일 선택 후 임베딩 시작 버튼 클릭 시 실행.

    yield로 단계별 진행 상태를 UI에 실시간 표시:
      1단계: 파일 분석 중...
      2단계: (PII 없음) 임베딩 중... → 완료
             (PII 있음) 처리 방식 선택 모달 표시

    Yields:
        (status_md, modal_group_update, result_md)
    """
    global _pending_scans

    files = _normalize_upload_files(file_obj)
    paths = [p for p in (_upload_file_path(f) for f in files) if p]

    # 파일 없음 → 리셋
    if not paths:
        _pending_scans = None
        yield "", gr.update(visible=False), ""
        return

    # ── 1단계: 분석 시작 알림 ────────────────────────────────────────────────
    yield (
        f"### ⏳ {len(paths)}개 파일 분석 중...\n\n"
        + "\n".join(f"- 🔍 `{Path(p).name}`" for p in paths),
        gr.update(visible=False),
        "",
    )

    try:
        orch = _get_orchestrator()
        scans: List[Any] = []
        any_pii = False

        # ── 파일별 스캔 (진행 상황 표시) ────────────────────────────────────
        done_lines: List[str] = []
        for i, path in enumerate(paths, 1):
            yield (
                f"### ⏳ 파일 분석 중... ({i}/{len(paths)})\n\n"
                + "\n".join(done_lines)
                + f"\n- 🔍 `{Path(path).name}` 분석 중...",
                gr.update(visible=False),
                "",
            )
            scan = orch.handle_upload(path)
            scans.append(scan)
            if scan.has_pii:
                any_pii = True
            done_lines.append(_build_file_section(scan))

        _pending_scans = scans
        file_lines = "\n".join(done_lines)

        # ── PII 없음 → 자동 임베딩 ──────────────────────────────────────────
        if not any_pii:
            yield (
                f"### ⚙️ 개인정보 없음 — 임베딩 중...\n\n{file_lines}",
                gr.update(visible=False),
                "⏳ 임베딩 처리 중입니다...",
            )
            ok, total, embedded, detail = _do_commit(scans, "그대로 임베딩")
            _pending_scans = None
            yield (
                f"### ✅ {len(paths)}개 파일 완료\n\n{file_lines}",
                gr.update(visible=False),
                (
                    f"✅ **임베딩 완료** ({ok}개 파일)\n\n"
                    f"- 저장 청크: {embedded} / {total}\n\n"
                    + "\n".join(detail)
                ),
            )
            return

        # ── PII 있음 → 알림 + 모달(+확인 버튼 포함) 표시 ───────────────────
        pii_file_count = sum(1 for s in scans if s.has_pii)
        yield (
            f"### ⚠️ {len(paths)}개 파일 중 **{pii_file_count}개**에서 개인정보가 감지되었습니다\n\n"
            f"{file_lines}\n\n"
            f"> 아래에서 처리 방식을 선택하고 **✅ 확인** 버튼을 눌러주세요.",
            gr.update(visible=True),
            "",
        )

    except Exception as exc:
        traceback.print_exc()
        _pending_scans = None
        yield f"❌ 오류: {exc}", gr.update(visible=False), ""


def on_upload_commit(user_choice: str):
    """
    PII 감지 모달에서 처리 방식 선택 후 [확인] 클릭.

    Yields:
        (result_md, modal_group_update)
    """
    global _pending_scans

    if not _pending_scans:
        yield "❌ 파일을 먼저 업로드해주세요.", gr.update()
        return

    if user_choice == "취소":
        _pending_scans = None
        yield "🚫 업로드가 취소되었습니다.", gr.update(visible=False)
        return

    # 모달 즉시 숨기고 진행 상태 표시
    yield "⏳ 임베딩 처리 중입니다...", gr.update(visible=False)

    try:
        ok, total, embedded, detail = _do_commit(_pending_scans, user_choice)
        _pending_scans = None

        yield (
            f"✅ **임베딩 완료** ({ok}개 파일)\n\n"
            f"- 저장 청크: {embedded} / {total}\n\n"
            + "\n".join(detail),
            gr.update(visible=False),
        )

    except Exception as exc:
        traceback.print_exc()
        yield f"❌ 오류: {exc}", gr.update()


# ──────────────────────────────────────────────────────────────────────────────
# 탭 2: 질문 & 답변
# ──────────────────────────────────────────────────────────────────────────────

def on_query(user_query: str, full_view: bool) -> Tuple[str, str, str, str]:
    """
    사용자 질문 처리.

    Returns:
        (label_badge, policy_info, sources_html)
    """
    if not user_query.strip():
        return "", "", ""

    try:
        orch = _get_orchestrator()
        resp = orch.handle_query(user_query, full_view=full_view)

        label_icon = {"NORMAL": "🟢", "SENSITIVE": "🟡", "DANGEROUS": "🔴"}.get(resp.label, "⚪")
        label_badge = f"{label_icon} **{resp.label}** — {resp.reason}"

        policy_info = f"Action: `{resp.action}`"
        if resp.blocked:
            policy_info += "  |  ⛔ 차단됨 — 검색 결과를 표시할 수 없습니다."

        # 검색 소스 카드 HTML 생성
        sources_html = build_sources_html(
            chunks=getattr(resp, "retrieved_chunks", []),
            label=resp.label,
        )

        return label_badge, policy_info, sources_html

    except Exception as exc:
        traceback.print_exc()
        return "ERROR", f"❌ 오류: {exc}", ""


def on_open_path(source_path: str) -> str:
    """
    [경로 열기] 버튼 클릭 시 파일 탐색기에서 해당 파일을 선택해서 연다.
    원본 파일을 수정하지 않으며, 탐색기 열기만 수행한다.
    """
    if not source_path.strip():
        return "⚠️ 경로를 입력해주세요."
    return open_file_in_explorer(source_path.strip())


# ──────────────────────────────────────────────────────────────────────────────
# 탭 3: 감사 로그
# ──────────────────────────────────────────────────────────────────────────────

def on_refresh_log() -> Tuple[str, str]:
    """감사 로그 최신 20건 반환"""
    audit = _get_audit()

    uploads = audit.recent_uploads(20)
    queries = audit.recent_queries(20)

    upload_lines = ["| 시간 | 파일명 | PII 유형 | 선택 |", "|------|--------|---------|------|"]
    for u in uploads:
        types = ", ".join(u["pii_types"]) or "-"
        upload_lines.append(f"| {u['timestamp']} | {u['filename']} | {types} | {u['user_choice']} |")

    query_lines = ["| 시간 | 질문 | 레이블 | 차단 |", "|------|------|--------|------|"]
    for q in queries:
        blocked = "⛔" if q["blocked"] else "✅"
        query_lines.append(f"| {q['timestamp']} | {q['query'][:40]}… | {q['label']} | {blocked} |")

    return "\n".join(upload_lines), "\n".join(query_lines)


# ──────────────────────────────────────────────────────────────────────────────
# Gradio 앱 빌드
# ──────────────────────────────────────────────────────────────────────────────

_DARK_CSS = """
/* ── 전체 배경 / 기본 텍스트 ─────────────────────────────────────── */
body, .gradio-container {
    background-color: #0f1117 !important;
    color: #e2e8f0 !important;
}

/* ── 탭 바 ──────────────────────────────────────────────────────── */
.tab-nav button {
    background: #1a202c !important;
    color: #a0aec0 !important;
    border-bottom: 2px solid transparent !important;
}
.tab-nav button.selected {
    background: #2d3748 !important;
    color: #f7fafc !important;
    border-bottom: 2px solid #63b3ed !important;
}

/* ── 패널 / 그룹 박스 ───────────────────────────────────────────── */
.block, .form, .panel, fieldset {
    background: #1a202c !important;
    border-color: #2d3748 !important;
}

/* ── 레이블 텍스트 ───────────────────────────────────────────────── */
label span, .label-wrap span {
    color: #a0aec0 !important;
}

/* ── 입력 필드 (Textbox / Textarea) ─────────────────────────────── */
textarea, input[type="text"], input[type="number"] {
    background: #171923 !important;
    color: #e2e8f0 !important;
    border-color: #2d3748 !important;
}
textarea:focus, input[type="text"]:focus {
    border-color: #63b3ed !important;
    box-shadow: 0 0 0 2px rgba(99,179,237,0.25) !important;
}

/* ── 버튼 ────────────────────────────────────────────────────────── */
button.primary {
    background: #2b6cb0 !important;
    color: #f7fafc !important;
    border: none !important;
}
button.primary:hover {
    background: #2c5282 !important;
}
button.secondary {
    background: #2d3748 !important;
    color: #e2e8f0 !important;
    border-color: #4a5568 !important;
}

/* ── Radio / Checkbox ────────────────────────────────────────────── */
.wrap .wrap-inner {
    background: #1a202c !important;
}
.wrap label span {
    color: #cbd5e0 !important;
}

/* ── 파일 업로드 영역 ────────────────────────────────────────────── */
.upload-container, .file-preview {
    background: #1a202c !important;
    border-color: #2d3748 !important;
    color: #a0aec0 !important;
}

/* ── Markdown 렌더 영역 ──────────────────────────────────────────── */
.prose, .markdown-body {
    color: #cbd5e0 !important;
}
.prose h1, .prose h2, .prose h3 {
    color: #f7fafc !important;
}
.prose code, code {
    background: #2d3748 !important;
    color: #90cdf4 !important;
}
.prose table th {
    background: #2d3748 !important;
    color: #e2e8f0 !important;
}
.prose table td {
    border-color: #2d3748 !important;
    color: #cbd5e0 !important;
}

/* ── 스크롤바 ────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #171923; }
::-webkit-scrollbar-thumb { background: #2d3748; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #4a5568; }

/* ── 검색 소스 섹션 제목 ─────────────────────────────────────────── */
.label-badge { font-size: 1.1em; font-weight: bold; color: #f7fafc !important; }

/* ── Accordion ───────────────────────────────────────────────────── */
.gr-accordion > .label-wrap {
    background: #2d3748 !important;
    color: #e2e8f0 !important;
}
"""


def build_app() -> gr.Blocks:
    with gr.Blocks(
        title="🔐 보안 RAG 시스템",
        theme=gr.themes.Base(
            primary_hue="blue",
            secondary_hue="slate",
            neutral_hue="slate",
            font=["Pretendard", "Noto Sans KR", "sans-serif"],
        ),
        css=_DARK_CSS,
    ) as app:

        gr.Markdown(
            """# 🔐 로컬 보안 RAG 시스템
            **개인 문서(PDF/HWPX)를 업로드하고 안전하게 질문하세요.**
            보안 에이전트(Qwen)가 개인정보를 보호하고 위험 요청을 차단합니다."""
        )

        # ── 탭 1: 파일 업로드 ────────────────────────────────────────────────
        with gr.Tab("📁 파일 업로드"):
            gr.Markdown(
                "### PDF / HWPX / 이미지를 업로드하세요\n"
                "파일을 선택한 뒤 **임베딩 시작** 버튼을 눌러주세요.\n"
                "개인정보가 감지된 경우에만 처리 방식을 선택할 수 있습니다."
            )

            upload_input = gr.File(
                label="파일 선택 (복수 가능 — Ctrl/⌘+클릭)",
                file_count="multiple",
                file_types=[".pdf", ".hwpx", ".png", ".jpg", ".jpeg", ".heic", ".webp"],
            )

            embed_btn = gr.Button("📥 임베딩 시작", variant="primary", size="lg")

            # 진행 상태 표시 (단계별 업데이트)
            scan_output = gr.Markdown(label="진행 상태", value="")

            # ── PII 감지 시에만 나타나는 처리 방식 선택 영역 ──────────────
            # 확인 버튼을 modal_group 안에 포함해 visibility 토글을 하나로 통일
            with gr.Group(visible=False) as modal_group:
                gr.Markdown(
                    "---\n"
                    "### ⚠️ 개인정보가 감지된 파일의 처리 방식을 선택하세요\n"
                    "> 💡 어떤 방식이든 원문은 그대로 저장됩니다. "
                    "마스킹은 검색 결과 카드에서만 시각적으로 표시됩니다."
                )
                choice_radio = gr.Radio(
                    choices=[
                        "UI 마스킹 표시 (원문 저장)",
                        "그대로 임베딩",
                        "취소",
                    ],
                    value="UI 마스킹 표시 (원문 저장)",
                    label="처리 방식 선택",
                )
                commit_btn = gr.Button("✅ 확인", variant="primary", size="lg")

            # 임베딩 진행/결과 출력
            commit_output = gr.Markdown(label="임베딩 결과", value="")

            # 임베딩 시작 → 스캔·진행 표시 → PII 없으면 자동 완료, 있으면 모달 표시
            embed_btn.click(
                on_file_change,
                inputs=[upload_input],
                outputs=[scan_output, modal_group, commit_output],
            )
            # PII 감지 후 확인 클릭 → 임베딩 실행
            commit_btn.click(
                on_upload_commit,
                inputs=[choice_radio],
                outputs=[commit_output, modal_group],
            )

        # ── 탭 2: 질문 & 답변 ─────────────────────────────────────────────────
        with gr.Tab("💬 질문 & 답변"):
            gr.Markdown("### 업로드한 문서에서 답을 찾습니다")

            with gr.Row():
                query_input = gr.Textbox(
                    label="질문 입력",
                    placeholder="예: 여권 사진 찾아줘 / 이 계약서의 핵심 조항을 요약해줘",
                    lines=2,
                    scale=4,
                )
                full_view_checkbox = gr.Checkbox(
                    label="전체 보기 (민감 정보 포함)",
                    value=False,
                    scale=1,
                )

            ask_btn = gr.Button("🔎 검색하기", variant="primary")

            label_output  = gr.Markdown(label="보안 분류", elem_classes=["label-badge"])
            policy_output = gr.Markdown(label="정책 정보")

            # ── 검색 소스 카드 ──────────────────────────────────────────────
            gr.Markdown("---")
            gr.Markdown("#### 📑 검색 소스")
            sources_output = gr.HTML(label="검색 소스")

            # ── 경로 열기 ───────────────────────────────────────────────────
            with gr.Accordion("📂 파일 경로 직접 열기", open=False):
                gr.Markdown(
                    "위 검색 소스 카드에서 확인한 파일 경로를 아래에 붙여넣고 버튼을 누르면\n"
                    "파일 탐색기(Finder / 탐색기)에서 해당 파일을 선택하여 열어줍니다.\n"
                    "**원본 파일은 수정되지 않습니다.**"
                )
                with gr.Row():
                    path_input = gr.Textbox(
                        label="파일 경로",
                        placeholder="/Users/.../document.pdf",
                        scale=5,
                    )
                    open_path_btn = gr.Button("📂 경로 열기", scale=1)
                open_path_result = gr.Textbox(
                    label="결과",
                    interactive=False,
                    lines=1,
                )
                open_path_btn.click(
                    on_open_path,
                    inputs=[path_input],
                    outputs=[open_path_result],
                )

            ask_btn.click(
                on_query,
                inputs=[query_input, full_view_checkbox],
                outputs=[label_output, policy_output, sources_output],
            )

        # ── 탭 3: 감사 로그 ───────────────────────────────────────────────────
        with gr.Tab("📋 감사 로그"):
            gr.Markdown("### 최근 활동 기록")
            refresh_btn = gr.Button("🔄 새로고침")

            with gr.Row():
                upload_log_out = gr.Markdown(label="업로드 이벤트")
                query_log_out  = gr.Markdown(label="질문 이벤트")

            refresh_btn.click(
                on_refresh_log,
                inputs=[],
                outputs=[upload_log_out, query_log_out],
            )
            app.load(on_refresh_log, inputs=[], outputs=[upload_log_out, query_log_out])

    return app


def main() -> None:
    app = build_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
