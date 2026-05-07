"""App/admin_ui/gradio_app.py — TRI-CHEF 관리자용 전수 검사 UI (Gradio).

별도 venv + HTTP 호출 방식. main backend (127.0.0.1:5001) 이 선구동 상태여야 함.

실행:  python gradio_app.py   →  http://127.0.0.1:7860

기능:
  - 쿼리 입력 → 도메인(image / doc_page) 별 전수 per-row 스코어 테이블
  - 선택 행 상세 패널: 원문 텍스트 + 매칭 토큰 하이라이트(형광 배경) + 경로
  - CSV 내보내기 (Pandas → gr.File 다운로드)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import gradio as gr
import pandas as pd
import requests

BACKEND = os.environ.get("TRICHEF_BACKEND", "http://127.0.0.1:5001")
TIMEOUT = 300


# ── HTTP 호출 래퍼 ──────────────────────────────────────────────────
def _api_inspect(query: str, domain: str, top_n: int,
                 use_lexical: bool, use_asf: bool) -> dict:
    r = requests.post(f"{BACKEND}/api/admin/inspect", json={
        "query": query, "domain": domain, "top_n": int(top_n),
        "use_lexical": use_lexical, "use_asf": use_asf,
    }, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _api_doc_text(doc_id: str, query: str, domain: str) -> dict:
    r = requests.get(f"{BACKEND}/api/admin/doc-text",
                     params={"id": doc_id, "query": query, "domain": domain},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _api_domains() -> dict:
    try:
        r = requests.get(f"{BACKEND}/api/admin/domains", timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"_error": str(e)}


# ── 하이라이트용 세그먼트 빌드 ─────────────────────────────────────
def _highlight_segments(text: str, matches: list[str]) -> list[tuple[str, str | None]]:
    """HighlightedText 입력 형태: [(segment, label|None), ...]
    label 이 non-None 이면 색 배경으로 표시.
    """
    if not matches:
        return [(text, None)]
    # 긴 토큰 우선 매칭 (포함관계)
    toks = sorted({m for m in matches if m}, key=len, reverse=True)
    segs: list[tuple[str, str | None]] = []
    cur = text
    # 그리디 스캔
    i = 0
    out: list[tuple[str, str | None]] = []
    buf = []
    while i < len(cur):
        hit = None
        for t in toks:
            if cur.startswith(t, i):
                hit = t
                break
        if hit:
            if buf:
                out.append(("".join(buf), None))
                buf = []
            out.append((hit, "match"))
            i += len(hit)
        else:
            buf.append(cur[i])
            i += 1
    if buf:
        out.append(("".join(buf), None))
    return out


# ── UI 콜백 ─────────────────────────────────────────────────────────
def on_inspect(query, domains, top_n, use_lexical, use_asf):
    if not query.strip():
        return pd.DataFrame(), "", "쿼리를 입력하세요", None
    if isinstance(domains, str):
        domains = [domains]
    if not domains:
        return pd.DataFrame(), "", "도메인을 하나 이상 선택하세요", None

    frames = []
    summaries = []
    errors = []
    for dom in domains:
        try:
            data = _api_inspect(query, dom, top_n, use_lexical, use_asf)
        except Exception as e:
            errors.append(f"[{dom}] {e}")
            continue
        rows = data["rows"]
        sub = pd.DataFrame(rows)
        if not sub.empty:
            sub.insert(0, "domain", data["domain"])
        frames.append(sub)
        summaries.append(
            f"{data['domain']}: 총 {data['total']}개 중 top-{data['returned']} | "
            f"μ={data['calibration']['mu_null']:.3f}, "
            f"σ={data['calibration']['sigma_null']:.3f}, "
            f"abs_thr={data['calibration']['abs_threshold']:.3f}"
        )

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df.empty:
        cols = ["domain", "rank", "filename", "page", "id", "source_path",
                "dense", "lexical", "asf", "rrf", "confidence", "z_score"]
        df = df[[c for c in cols if c in df.columns]]
        for c in ("dense", "lexical", "asf", "rrf", "confidence", "z_score"):
            if c in df:
                df[c] = df[c].astype(float).round(4)
    summary = " \n".join(summaries)
    err_msg = " | ".join(errors) if errors else ""
    # CSV
    tmp = tempfile.NamedTemporaryFile(prefix="trichef_inspect_",
                                      suffix=".csv", delete=False, mode="w",
                                      encoding="utf-8-sig", newline="")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return df, summary, err_msg, tmp.name


def on_select(evt: gr.SelectData, df: pd.DataFrame, query: str):
    empty_img = gr.update(value=None, visible=False)
    if df is None or df.empty or evt.index is None:
        return [("항목을 선택하세요", None)], "", empty_img
    row_idx = evt.index[0] if isinstance(evt.index, list) else evt.index
    try:
        row = df.iloc[row_idx]
        doc_id = row["id"]
        domain = row["domain"] if "domain" in df.columns else "doc_page"
    except Exception:
        return [("선택 오류", None)], "", empty_img
    try:
        data = _api_doc_text(doc_id, query, domain)
    except Exception as e:
        return [(f"오류: {e}", None)], "", empty_img

    segs = _highlight_segments(data.get("text", ""), data.get("matches", []))
    src = data.get("source_path") or ""
    filename = Path(src).name if src else Path(doc_id).name

    if domain == "image":
        info = (
            f"**domain**: `image`\n\n"
            f"**파일명**: `{filename}`\n\n"
            f"**경로**: `{src or '(없음)'}`\n\n"
            f"**id**: `{doc_id}`"
        )
        img_val = None
        if src and Path(src).exists():
            img_val = str(src)
        else:
            try:
                r = requests.get(f"{BACKEND}/api/admin/file",
                                 params={"domain": "image", "id": doc_id},
                                 timeout=30)
                if r.ok:
                    tmp = tempfile.NamedTemporaryFile(
                        prefix="trichef_img_",
                        suffix=Path(doc_id).suffix or ".jpg",
                        delete=False,
                    )
                    tmp.write(r.content)
                    tmp.close()
                    img_val = tmp.name
            except Exception as e:
                info += f"\n\n⚠️ 이미지 로드 실패: {e}"
        img_upd = gr.update(value=img_val, visible=img_val is not None)
    else:
        page = data.get("page", 0)
        info = (
            f"**domain**: `doc_page`\n\n"
            f"**파일명**: `{filename}`\n\n"
            f"**경로**: `{src or '(없음)'}`\n\n"
            f"**페이지**: {page}\n\n"
            f"**id**: `{doc_id}`"
        )
        img_upd = empty_img

    if data.get("matches"):
        info += f"\n\n**매칭 토큰**: {', '.join(data['matches'][:20])}"
    return segs, info, img_upd


# ── UI 빌드 ─────────────────────────────────────────────────────────
CSS = """
.match-highlight { background: #fff176 !important; color: #000 !important;
                   padding: 1px 2px; border-radius: 3px; font-weight: 600; }
"""


def build_ui():
    dom_info = _api_domains()
    if "_error" in dom_info:
        header = f"⚠️ 백엔드 연결 실패: {dom_info['_error']} — {BACKEND}"
    else:
        header = "도메인 현황 | " + " | ".join(
            f"{k}: N={v['count']}, vocab={v['vocab_size']}, "
            f"sparse={'O' if v['has_sparse'] else 'X'}, "
            f"asf={'O' if v['has_asf'] else 'X'}"
            for k, v in dom_info.items()
        )

    with gr.Blocks(title="TRI-CHEF Admin Inspect", css=CSS) as demo:
        gr.Markdown(f"# TRI-CHEF 관리자 전수 검사\n\n{header}")

        with gr.Row():
            with gr.Column(scale=3):
                query = gr.Textbox(label="검색어", placeholder="예: 지역사회 복지정책",
                                   lines=1)
            with gr.Column(scale=1):
                domain = gr.CheckboxGroup(["doc_page", "image"],
                                           value=["doc_page", "image"],
                                           label="도메인 (복수 선택 가능)")
        with gr.Row():
            top_n = gr.Slider(10, 2000, value=30, step=10, label="상위 N 반환")
            use_lexical = gr.Checkbox(value=True, label="Lexical 채널 사용")
            use_asf = gr.Checkbox(value=True, label="ASF 채널 사용")
            run_btn = gr.Button("검색 실행", variant="primary")

        summary = gr.Markdown("")
        err = gr.Markdown("")
        csv_file = gr.File(label="CSV 다운로드", interactive=False)

        with gr.Row():
            table = gr.Dataframe(label="전수 결과 (행 클릭 → 상세)",
                                 interactive=False, wrap=True, height=None)

        with gr.Row():
            with gr.Column(scale=1):
                detail_info = gr.Markdown("")
                detail_image = gr.Image(label="이미지 미리보기", visible=False,
                                        show_label=True, height=360)
            with gr.Column(scale=2):
                detail = gr.HighlightedText(
                    label="원문 / 캡션 (매칭 토큰 하이라이트)",
                    color_map={"match": "#fff176"},
                    show_legend=False,
                )

        run_btn.click(
            on_inspect, [query, domain, top_n, use_lexical, use_asf],
            [table, summary, err, csv_file],
        )
        table.select(on_select, [table, query], [detail, detail_info, detail_image])

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.queue().launch(server_name="127.0.0.1", server_port=7860,
                        inbrowser=True, show_error=True)
