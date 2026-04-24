"""
MM_TriCHEF/app.py — Movie & Music Tri-CHEF 관리자 테스트 UI (Gradio)

실행:
    cd MM_TriCHEF
    python app.py

접속: http://localhost:7860
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import numpy as np

# ── backend sys.path 등록 ─────────────────────────────────────────────────────
_REPO    = Path(__file__).resolve().parents[1]
_BACKEND = _REPO / "App" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import gradio as gr
from config import PATHS, TRICHEF_CFG


# ════════════════════════════════════════════════════════════════════════════
# 헬퍼
# ════════════════════════════════════════════════════════════════════════════

def _npy_rows(path: Path) -> int:
    try:
        return int(np.load(str(path), mmap_mode="r").shape[0])
    except Exception:
        return 0


def _fmt_time(sec) -> str:
    if sec is None:
        return "--:--"
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def _reg_count(reg_path: Path) -> int:
    try:
        return len(json.loads(reg_path.read_text(encoding="utf-8")))
    except Exception:
        return 0


# ════════════════════════════════════════════════════════════════════════════
# 엔진 싱글턴
# ════════════════════════════════════════════════════════════════════════════

_engine      = None
_engine_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from services.trichef.unified_engine import TriChefEngine
                _engine = TriChefEngine()
    return _engine


# ════════════════════════════════════════════════════════════════════════════
# Tab 1 — 상태
# ════════════════════════════════════════════════════════════════════════════

def get_status() -> str:
    mdir  = Path(PATHS["TRICHEF_MOVIE_CACHE"])
    mudir = Path(PATHS["TRICHEF_MUSIC_CACHE"])
    raw   = Path(PATHS["RAW_DB"])

    vid_dir = raw / "Movie"
    rec_dir = raw / "Rec"
    vid_n = sum(1 for p in vid_dir.rglob("*.*") if p.is_file()) if vid_dir.exists() else 0
    rec_n = sum(1 for p in rec_dir.rglob("*.*") if p.is_file()) if rec_dir.exists() else 0

    movie_re    = mdir  / "cache_movie_Re.npy"
    music_re    = mudir / "cache_music_Re.npy"
    movie_cached = movie_re.exists()
    music_cached = music_re.exists()
    movie_segs   = _npy_rows(movie_re) if movie_cached else 0
    music_segs   = _npy_rows(music_re) if music_cached else 0
    movie_reg    = _reg_count(mdir  / "registry.json")
    music_reg    = _reg_count(mudir / "registry.json")

    # calibration 현황
    from services.trichef.calibration import get_thresholds
    try:
        mc = get_thresholds("movie")
        mc_str = f"μ={mc['mu_null']:.4f} σ={mc['sigma_null']:.4f} thr={mc['abs_threshold']:.4f}"
    except Exception:
        mc_str = "미보정"
    try:
        muc = get_thresholds("music")
        muc_str = f"μ={muc['mu_null']:.4f} σ={muc['sigma_null']:.4f} thr={muc['abs_threshold']:.4f}"
    except Exception:
        muc_str = "미보정"

    lines = [
        "## 📊 캐시 현황\n",
        "| 도메인 | 캐시 | 세그먼트 수 | 인덱스 파일 수 | Raw 파일 수 |",
        "|--------|:----:|:-----------:|:--------------:|:-----------:|",
        f"| 🎬 동영상 | {'✅' if movie_cached else '❌'} | {movie_segs:,} | {movie_reg} | {vid_n} |",
        f"| 🎵 음원   | {'✅' if music_cached else '❌'} | {music_segs:,} | {music_reg} | {rec_n} |",
        "",
        "## 📐 Calibration 현황\n",
        "| 도메인 | Null 분포 파라미터 |",
        "|--------|-------------------|",
        f"| 🎬 동영상 | {mc_str} |",
        f"| 🎵 음원   | {muc_str} |",
        "",
        "## 📁 경로\n",
        f"- Raw 동영상: `{vid_dir}`",
        f"- Raw 음원:   `{rec_dir}`",
        f"- Movie 캐시: `{mdir}`",
        f"- Music 캐시: `{mudir}`",
    ]
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# Tab 2 — 재인덱싱 (스트리밍 로그)
# ════════════════════════════════════════════════════════════════════════════

_reindex_lock = threading.Lock()


def run_reindex(scope: str):
    """Generator: Gradio 스트리밍 출력용."""
    if not _reindex_lock.acquire(blocking=False):
        yield "⚠️ 재인덱싱이 이미 진행 중입니다. 완료 후 다시 시도하세요."
        return

    log: list[str] = []

    def emit(msg: str):
        log.append(msg)

    try:
        from embedders.trichef.incremental_runner import (
            run_movie_incremental, run_music_incremental,
        )

        if scope in ("movie", "all"):
            emit("🎬 동영상 인덱싱 시작...")
            yield "\n".join(log)
            try:
                r = run_movie_incremental()
                emit(f"  ✅ 완료 — 신규={r.new_count}  기존={r.existing_count}  전체={r.total_count}")
            except Exception as e:
                emit(f"  ❌ 오류: {e}")
            yield "\n".join(log)

        if scope in ("music", "all"):
            emit("🎵 음원 인덱싱 시작...")
            yield "\n".join(log)
            try:
                r = run_music_incremental()
                emit(f"  ✅ 완료 — 신규={r.new_count}  기존={r.existing_count}  전체={r.total_count}")
            except Exception as e:
                emit(f"  ❌ 오류: {e}")
            yield "\n".join(log)

        emit("🔄 검색 엔진 재로드 중...")
        yield "\n".join(log)
        try:
            eng = _get_engine()
            eng.reload()
            emit("  ✅ 엔진 재로드 완료.")
        except Exception as e:
            emit(f"  ⚠️ 엔진 재로드 실패: {e}")
        emit("\n🏁 모든 작업 완료.")
        yield "\n".join(log)

    finally:
        _reindex_lock.release()


# ════════════════════════════════════════════════════════════════════════════
# Tab 3 — 검색
# ════════════════════════════════════════════════════════════════════════════

_DOMAIN_MAP = {"🎬 동영상": "movie", "🎵 음원": "music"}


def run_search(query: str, domain_labels: list[str], topk: int) -> tuple[str, str]:
    if not query.strip():
        return "쿼리를 입력하세요.", ""
    if not domain_labels:
        return "도메인을 하나 이상 선택하세요.", ""

    try:
        engine = _get_engine()
    except Exception as e:
        return f"❌ 엔진 로드 실패: {e}", ""

    all_results = []
    errors = []
    for label in domain_labels:
        domain = _DOMAIN_MAP.get(label, "movie")
        try:
            res = engine.search_av(query, domain=domain, topk=int(topk))
            all_results.extend(res)
        except Exception as e:
            errors.append(f"❌ {label} 검색 실패: {e}")

    all_results.sort(key=lambda r: -r.score)
    all_results = all_results[:int(topk)]

    if not all_results:
        err_str = ("\n" + "\n".join(errors)) if errors else ""
        return f"임계값 이상의 결과가 없습니다. (캐시가 비어 있거나 쿼리와 매칭 없음){err_str}", ""

    domain_str = " + ".join(domain_labels)

    # ── Markdown 결과 ──
    md: list[str] = [
        f"## 검색 결과 — `{query}`  ({domain_str}, {len(all_results)}건)\n",
        "---",
    ]
    if errors:
        for e in errors:
            md.append(f"> ⚠️ {e}\n")

    results = all_results
    for rank, r in enumerate(results, 1):
        conf_pct = round(r.confidence * 100)
        bar = "█" * (conf_pct // 10) + "░" * (10 - conf_pct // 10)
        md.append(f"### #{rank}  {r.file_name}")
        md.append(f"점수 `{r.score:.4f}` | 신뢰도 `{bar}` {conf_pct}%")
        md.append(f"경로: `{r.file_path}`\n")
        if r.segments:
            md.append("**매칭 구간:**")
            for seg in r.segments:
                t_start = _fmt_time(seg.get("start"))
                t_end   = _fmt_time(seg.get("end"))
                s_pct   = round((seg.get("score", 0)) * 100)
                text    = (seg.get("text") or seg.get("caption") or "").strip()
                preview = text[:150] + ("…" if len(text) > 150 else "")
                md.append(f"  - `{t_start} ~ {t_end}` ({s_pct}%) {preview}")
        md.append("\n---")

    # ── JSON 원본 ──
    raw_list = []
    for i, r in enumerate(results):
        raw_list.append({
            "rank":       i + 1,
            "file_name":  r.file_name,
            "file_path":  r.file_path,
            "score":      round(r.score, 4),
            "confidence": round(r.confidence, 4),
            "segments": [
                {
                    "start":   seg.get("start"),
                    "end":     seg.get("end"),
                    "score":   round(seg.get("score", 0), 4),
                    "text":    seg.get("text", ""),
                    "caption": seg.get("caption", ""),
                }
                for seg in r.segments
            ],
        })
    raw_json = json.dumps(raw_list, ensure_ascii=False, indent=2)
    return "\n".join(md), raw_json


# ════════════════════════════════════════════════════════════════════════════
# Tab 4 — 파일 목록 점검
# ════════════════════════════════════════════════════════════════════════════

def list_raw_files(domain_label: str) -> str:
    raw = Path(PATHS["RAW_DB"])
    if domain_label == "🎬 동영상":
        d = raw / "Movie"
        exts = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".webm"}
    else:
        d = raw / "Rec"
        exts = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".mp4"}

    if not d.exists():
        return f"디렉터리 없음: `{d}`\n\nRaw DB 경로: `{raw}`"

    files = sorted(p for p in d.rglob("*.*") if p.suffix.lower() in exts)
    if not files:
        return f"파일 없음 (경로: `{d}`)"

    lines = [f"## {domain_label} Raw 파일 목록 ({len(files)}개)\n"]
    mdir  = Path(PATHS["TRICHEF_MOVIE_CACHE"]) if "동영상" in domain_label else Path(PATHS["TRICHEF_MUSIC_CACHE"])
    try:
        reg = json.loads((mdir / "registry.json").read_text(encoding="utf-8"))
    except Exception:
        reg = {}

    for p in files:
        key = str(p.relative_to(d)).replace("\\", "/")
        indexed = "✅" if key in reg else "⬜"
        size_mb = round(p.stat().st_size / 1024 / 1024, 1)
        lines.append(f"- {indexed} `{p.name}` ({size_mb} MB)")

    lines.append(f"\n✅=인덱스됨  ⬜=미인덱스")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# Gradio UI 조립
# ════════════════════════════════════════════════════════════════════════════

_CSS = """
.tab-nav button { font-size: 1rem; }
.result-json { font-size: 0.8rem; }
"""

with gr.Blocks(title="MM Tri-CHEF Admin", theme=gr.themes.Soft(), css=_CSS) as demo:
    gr.Markdown(
        "# 🎬🎵 MM Tri-CHEF — Movie / Music 관리자 테스트 UI\n"
        "> **3축 복소수 검색** · Re(SigLIP2/BGE-M3) + Im(BGE-M3) + Z(BGE-M3/zeros) "
        "· Whisper STT · 구간 하이라이트"
    )

    with gr.Tabs():

        # ── Tab 1: 상태 ────────────────────────────────────────────────────────
        with gr.Tab("📊 캐시 상태"):
            status_md  = gr.Markdown(value="로딩 중...")
            refresh_btn = gr.Button("🔄 새로고침", variant="secondary", size="sm")
            refresh_btn.click(fn=get_status, outputs=status_md)
            demo.load(fn=get_status, outputs=status_md)

        # ── Tab 2: 재인덱싱 ────────────────────────────────────────────────────
        with gr.Tab("⚙️ 재인덱싱"):
            gr.Markdown(
                "### 증분 인덱싱\n"
                "변경된 파일만 처리합니다 (SHA-256 레지스트리). "
                "`raw_DB/Video` 및 `raw_DB/Rec` 폴더를 스캔합니다."
            )
            with gr.Row():
                btn_movie = gr.Button("🎬 동영상 재인덱싱", variant="primary")
                btn_music = gr.Button("🎵 음원 재인덱싱",   variant="primary")
                btn_all   = gr.Button("🔄 전체 재인덱싱",   variant="stop")
            log_box = gr.Textbox(
                label="진행 로그", lines=14, interactive=False,
                placeholder="재인덱싱 버튼을 누르면 로그가 출력됩니다."
            )
            btn_movie.click(fn=lambda: run_reindex("movie"), outputs=log_box)
            btn_music.click(fn=lambda: run_reindex("music"), outputs=log_box)
            btn_all.click(  fn=lambda: run_reindex("all"),   outputs=log_box)

        # ── Tab 3: 검색 ────────────────────────────────────────────────────────
        with gr.Tab("🔍 검색"):
            with gr.Row():
                query_in = gr.Textbox(
                    label="검색 쿼리",
                    placeholder="예: 로봇이 기계를 조립하는 장면 / 인터뷰 중 웃음 소리",
                    scale=5,
                )
                domain_in = gr.CheckboxGroup(
                    choices=["🎬 동영상", "🎵 음원"],
                    value=["🎬 동영상", "🎵 음원"],
                    label="도메인 (복수 선택 가능)",
                    scale=1,
                )
            with gr.Row():
                topk_in   = gr.Slider(1, 20, value=5, step=1, label="Top-K 결과 수")
                search_btn = gr.Button("🔍 검색", variant="primary", scale=1)

            result_md   = gr.Markdown(label="결과")
            show_json   = gr.Checkbox(label="JSON 원본 보기", value=False)
            result_json = gr.Code(label="JSON 원본", language="json", visible=False)

            show_json.change(
                fn=lambda v: gr.update(visible=v),
                inputs=show_json, outputs=result_json,
            )
            search_btn.click(
                fn=run_search,
                inputs=[query_in, domain_in, topk_in],
                outputs=[result_md, result_json],
            )
            query_in.submit(
                fn=run_search,
                inputs=[query_in, domain_in, topk_in],
                outputs=[result_md, result_json],
            )

        # ── Tab 4: 파일 목록 ───────────────────────────────────────────────────
        with gr.Tab("📂 파일 목록"):
            gr.Markdown("Raw DB에 있는 파일과 인덱스 상태를 확인합니다.")
            file_domain = gr.Radio(
                choices=["🎬 동영상", "🎵 음원"],
                value="🎬 동영상",
                label="도메인",
            )
            file_list_btn = gr.Button("📂 목록 조회", variant="secondary")
            file_list_md  = gr.Markdown()
            file_list_btn.click(fn=list_raw_files, inputs=file_domain, outputs=file_list_md)
            file_domain.change(fn=list_raw_files, inputs=file_domain, outputs=file_list_md)

# ════════════════════════════════════════════════════════════════════════════
# 실행
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("MM Tri-CHEF Admin UI")
    print(f"Backend: {_BACKEND}")
    print(f"Data:    {PATHS['DATA_ROOT']}")
    print("=" * 60)
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
    )
