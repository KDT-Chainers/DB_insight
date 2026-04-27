"""
MR_TriCHEF/app.py — Movie & Music(Rec) Tri-CHEF Standalone 관리자 UI.

실행:
    cd MR_TriCHEF
    python app.py
접속: http://localhost:7860

특징:
    · App/backend 비의존 (MR_TriCHEF/pipeline 만 사용)
    · 파일 단위 증분 인덱싱 (SHA-256, 파일마다 체크포인트)
    · 출력 경로:
        Movie → Data/embedded_DB/Movie/
        Music → Data/embedded_DB/Rec/
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import gradio as gr
import numpy as np

from pipeline import registry
from pipeline.paths import (
    MOVIE_CACHE_DIR, MOVIE_RAW_DIR, MOVIE_EXTS,
    MUSIC_CACHE_DIR, MUSIC_RAW_DIR, MUSIC_EXTS,
)


# ════════════════════════════════════════════════════════════════════════════
# 공용 헬퍼
# ════════════════════════════════════════════════════════════════════════════

def _npy_rows(p: Path) -> int:
    try:
        return int(np.load(p, mmap_mode="r").shape[0])
    except Exception:
        return 0


def _fmt_time(sec) -> str:
    if sec is None:
        return "--:--"
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


# ════════════════════════════════════════════════════════════════════════════
# Tab 1 — 캐시 상태
# ════════════════════════════════════════════════════════════════════════════

def get_status() -> str:
    def _count_files(root: Path, exts: set[str]) -> int:
        if not root.exists():
            return 0
        return sum(1 for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts)

    m_raw = _count_files(MOVIE_RAW_DIR, MOVIE_EXTS)
    r_raw = _count_files(MUSIC_RAW_DIR, MUSIC_EXTS)

    m_re = MOVIE_CACHE_DIR / "cache_movie_Re.npy"
    r_re = MUSIC_CACHE_DIR / "cache_music_Re.npy"

    m_reg = registry.load(MOVIE_CACHE_DIR / "registry.json")
    r_reg = registry.load(MUSIC_CACHE_DIR / "registry.json")

    lines = [
        "## 📊 캐시 현황\n",
        "| 도메인 | Re축 npy | 세그먼트 수 | 인덱스 파일 수 | Raw 파일 수 |",
        "|--------|:--------:|:-----------:|:--------------:|:-----------:|",
        f"| 🎬 Movie | {'✅' if m_re.exists() else '❌'} | {_npy_rows(m_re):,} | {len(m_reg)} | {m_raw} |",
        f"| 🎵 Music | {'✅' if r_re.exists() else '❌'} | {_npy_rows(r_re):,} | {len(r_reg)} | {r_raw} |",
        "",
        "## 📁 경로\n",
        f"- Movie Raw:  `{MOVIE_RAW_DIR}`",
        f"- Movie 캐시: `{MOVIE_CACHE_DIR}`",
        f"- Music Raw:  `{MUSIC_RAW_DIR}`",
        f"- Music 캐시: `{MUSIC_CACHE_DIR}`",
        "",
        "## 🧠 모델 구성\n",
        "- **Re** (의미 비전)  SigLIP2-so400m (1152d)  ← Movie 만",
        "- **Im** (STT 텍스트) BGE-M3 (1024d)",
        "- **Z**  (구조 비전)  DINOv2-base (768d)  ← Movie 만, Music은 zeros",
        "- **STT**            faster-whisper large-v3 (int8_float16, GPU)",
    ]
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# Tab 2 — 재인덱싱 (스트리밍 로그)
# ════════════════════════════════════════════════════════════════════════════

_reindex_lock = threading.Lock()


def run_reindex(scope: str):
    """Generator: Gradio textbox 로 스트리밍."""
    if not _reindex_lock.acquire(blocking=False):
        yield "⚠️ 이미 인덱싱 진행 중."
        return

    log: list[str] = []
    def emit(m: str):
        log.append(m)

    try:
        if scope in ("movie", "all"):
            emit("═══ 🎬 Movie 인덱싱 ═══")
            yield "\n".join(log)
            from pipeline.movie_runner import run_movie_incremental
            try:
                for res in run_movie_incremental(progress=emit):
                    yield "\n".join(log)
                emit("🎬 완료.")
            except Exception as e:
                import traceback
                emit(f"❌ Movie 실패: {e}")
                emit(traceback.format_exc()[:1200])
            yield "\n".join(log)

        if scope in ("music", "all"):
            emit("\n═══ 🎵 Music 인덱싱 ═══")
            yield "\n".join(log)
            from pipeline.music_runner import run_music_incremental
            try:
                for res in run_music_incremental(progress=emit):
                    yield "\n".join(log)
                emit("🎵 완료.")
            except Exception as e:
                import traceback
                emit(f"❌ Music 실패: {e}")
                emit(traceback.format_exc()[:1200])
            yield "\n".join(log)

        emit("\n🏁 전체 완료.")
        yield "\n".join(log)
    finally:
        _reindex_lock.release()


# ════════════════════════════════════════════════════════════════════════════
# Tab 3 — 검색
# ════════════════════════════════════════════════════════════════════════════

_search_state: dict = {"siglip": None, "bge": None}
_search_lock = threading.Lock()


def _get_search_encoders():
    """검색용 SigLIP2(text) + BGE-M3 — 로드 후 고정 유지."""
    if _search_state["bge"] is None:
        from pipeline.text import BGEM3Encoder
        _search_state["bge"] = BGEM3Encoder()
    if _search_state["siglip"] is None:
        from pipeline.vision import SigLIP2Encoder
        _search_state["siglip"] = SigLIP2Encoder()
    return _search_state["siglip"], _search_state["bge"]


_DOMAIN_MAP = {"🎬 Movie": "movie", "🎵 Music": "music"}


def run_search(query: str, domain_labels: list[str], topk: int) -> tuple[str, str]:
    if not query.strip():
        return "쿼리를 입력하세요.", ""
    if not domain_labels:
        return "도메인을 하나 이상 선택하세요.", ""

    try:
        with _search_lock:
            sig, bge = _get_search_encoders()
    except Exception as e:
        return f"❌ 인코더 로드 실패: {e}", ""

    from pipeline.search import search_movie, search_music
    all_hits = []
    errors: list[str] = []
    for label in domain_labels:
        dom = _DOMAIN_MAP[label]
        try:
            if dom == "movie":
                hits = search_movie(query, topk=int(topk),
                                    siglip_encoder=sig, bge_encoder=bge)
            else:
                hits = search_music(query, topk=int(topk),
                                    siglip_encoder=sig, bge_encoder=bge)
            for h in hits:
                all_hits.append((label, h))
        except Exception as e:
            errors.append(f"{label}: {e}")

    all_hits.sort(key=lambda x: -x[1].score)
    all_hits = all_hits[:int(topk)]

    if not all_hits:
        suffix = ("\n\n" + "\n".join(errors)) if errors else ""
        return f"결과 없음 (캐시가 비어있거나 매칭 부족).{suffix}", ""

    md = [f"## 🔎 `{query}` — {len(all_hits)}건 ({' + '.join(domain_labels)})\n", "---"]
    for e in errors:
        md.append(f"> ⚠️ {e}")

    for rank, (label, h) in enumerate(all_hits, 1):
        conf_pct = round(h.confidence * 100)
        bar = "█" * (conf_pct // 10) + "░" * (10 - conf_pct // 10)
        md.append(f"### #{rank}  [{label}] {h.file_name}")
        md.append(f"점수 `{h.score:.4f}` | 신뢰도 `{bar}` {conf_pct}%")
        md.append(f"경로: `{h.file}`\n")
        if h.segments:
            md.append("**매칭 구간 (상위 3):**")
            for seg in h.segments:
                t0 = _fmt_time(seg.get("t_start"))
                t1 = _fmt_time(seg.get("t_end"))
                s_pct = round(seg.get("score", 0) * 100)
                text = (seg.get("stt_text") or seg.get("caption") or "").strip()
                preview = text[:140] + ("…" if len(text) > 140 else "")
                md.append(f"  - `{t0} ~ {t1}` ({s_pct}%) {preview}")
        md.append("\n---")

    raw = [
        {
            "rank":       i + 1,
            "domain":     lbl,
            "file":       h.file,
            "file_name":  h.file_name,
            "score":      h.score,
            "confidence": h.confidence,
            "segments":   h.segments,
        }
        for i, (lbl, h) in enumerate(all_hits)
    ]
    return "\n".join(md), json.dumps(raw, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════════════════════
# Tab 4 — Raw 파일 목록
# ════════════════════════════════════════════════════════════════════════════

def list_raw_files(domain_label: str) -> str:
    if domain_label == "🎬 Movie":
        root, exts, cache_dir = MOVIE_RAW_DIR, MOVIE_EXTS, MOVIE_CACHE_DIR
    else:
        root, exts, cache_dir = MUSIC_RAW_DIR, MUSIC_EXTS, MUSIC_CACHE_DIR

    if not root.exists():
        return f"디렉터리 없음: `{root}`"
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts)
    if not files:
        return f"파일 없음 (`{root}`)"

    reg = registry.load(cache_dir / "registry.json")
    lines = [f"## {domain_label} — {len(files)}개 (`{root}`)\n"]
    for p in files:
        rel = str(p.relative_to(root)).replace("\\", "/")
        mark = "✅" if rel in reg else "⬜"
        size_mb = round(p.stat().st_size / 1024 / 1024, 1)
        lines.append(f"- {mark} `{rel}` ({size_mb} MB)")
    lines.append("\n✅=인덱스됨  ⬜=미인덱스")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════════════════════════

with gr.Blocks(title="MM Tri-CHEF Admin", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        "# 🎬🎵 MM Tri-CHEF (Standalone)\n"
        "> SigLIP2(Re) + BGE-M3(Im) + DINOv2(Z) 3축 Hermitian 검색 · "
        "Whisper STT · 파일 단위 증분 인덱싱"
    )

    with gr.Tabs():
        with gr.Tab("📊 캐시 상태"):
            status_md = gr.Markdown()
            refresh_btn = gr.Button("🔄 새로고침", size="sm")
            refresh_btn.click(fn=get_status, outputs=status_md)
            demo.load(fn=get_status, outputs=status_md)

        with gr.Tab("⚙️ 재인덱싱"):
            gr.Markdown(
                "### 파일별 증분 인덱싱\n"
                "각 파일마다 처리 후 캐시에 append + SHA-256 체크포인트. "
                "중단 후 재개해도 이미 처리된 파일은 skip."
            )
            with gr.Row():
                btn_m = gr.Button("🎬 Movie", variant="primary")
                btn_r = gr.Button("🎵 Music", variant="primary")
                btn_a = gr.Button("🔄 전체",  variant="stop")
            log_box = gr.Textbox(label="진행 로그", lines=20, interactive=False,
                                 placeholder="버튼을 누르면 실시간 로그 출력.")
            btn_m.click(fn=lambda: run_reindex("movie"), outputs=log_box)
            btn_r.click(fn=lambda: run_reindex("music"), outputs=log_box)
            btn_a.click(fn=lambda: run_reindex("all"),   outputs=log_box)

        with gr.Tab("🔍 검색"):
            with gr.Row():
                q_in = gr.Textbox(label="쿼리",
                                  placeholder="예: 조던 덩크 / 상담 신청", scale=5)
                d_in = gr.CheckboxGroup(
                    choices=["🎬 Movie", "🎵 Music"],
                    value=["🎬 Movie", "🎵 Music"],
                    label="도메인 (복수 선택)", scale=1,
                )
            with gr.Row():
                k_in = gr.Slider(1, 20, value=5, step=1, label="Top-K")
                btn_s = gr.Button("🔍 검색", variant="primary", scale=1)
            result_md = gr.Markdown()
            show_json = gr.Checkbox(label="JSON 원본 보기", value=False)
            result_json = gr.Code(language="json", visible=False)
            show_json.change(fn=lambda v: gr.update(visible=v),
                             inputs=show_json, outputs=result_json)
            btn_s.click(fn=run_search, inputs=[q_in, d_in, k_in],
                        outputs=[result_md, result_json])
            q_in.submit(fn=run_search, inputs=[q_in, d_in, k_in],
                        outputs=[result_md, result_json])

        with gr.Tab("📂 파일 목록"):
            f_in = gr.Radio(choices=["🎬 Movie", "🎵 Music"], value="🎬 Movie", label="도메인")
            f_btn = gr.Button("📂 조회")
            f_md = gr.Markdown()
            f_btn.click(fn=list_raw_files, inputs=f_in, outputs=f_md)
            f_in.change(fn=list_raw_files, inputs=f_in, outputs=f_md)


if __name__ == "__main__":
    print("=" * 60)
    print("MM Tri-CHEF Standalone Admin")
    print(f"Movie raw:  {MOVIE_RAW_DIR}")
    print(f"Music raw:  {MUSIC_RAW_DIR}")
    print(f"Movie out:  {MOVIE_CACHE_DIR}")
    print(f"Music out:  {MUSIC_CACHE_DIR}")
    print("=" * 60)
    demo.launch(server_name="0.0.0.0", server_port=7860,
                share=False, inbrowser=True)
