"""fig02: DI_TriCHEF vs MR_TriCHEF 파이프라인 좌우 비교.

DI = Document/Image  (BGE-M3 + SigLIP2 + DINOv2)
MR = Movie/Rec/BGM   (SigLIP2-text + BGE-M3 + Whisper STT + LangGraph)
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
import numpy as np

import _common as C
C.setup_style()


def shadow_box(ax, x, y, w, h, label, color, fontsize=9.5,
               text_color="white", bold=True, alpha=1.0, sublabel=None,
               style="round,pad=0.06"):
    sh = FancyBboxPatch((x + 0.04, y - 0.04), w, h, boxstyle=style,
                        facecolor="#888", edgecolor="none",
                        alpha=0.18, zorder=1)
    box = FancyBboxPatch((x, y), w, h, boxstyle=style,
                         facecolor=color, edgecolor="white",
                         linewidth=1.0, alpha=alpha, zorder=2)
    ax.add_patch(sh); ax.add_patch(box)
    weight = "bold" if bold else "normal"
    if sublabel:
        ax.text(x + w/2, y + h/2 + 0.10, label, ha="center", va="center",
                fontsize=fontsize, color=text_color, fontweight=weight,
                zorder=3, linespacing=1.15)
        ax.text(x + w/2, y + h/2 - 0.16, sublabel, ha="center", va="center",
                fontsize=fontsize - 1.5, color=text_color, alpha=0.88,
                zorder=3, linespacing=1.15)
    else:
        ax.text(x + w/2, y + h/2, label, ha="center", va="center",
                fontsize=fontsize, color=text_color, fontweight=weight,
                zorder=3, linespacing=1.15)


def arrow(ax, p1, p2, color="#444", lw=1.5, style="->",
          rad=0.0, alpha=1.0):
    ax.annotate("", xy=p2, xytext=p1,
                arrowprops=dict(arrowstyle=style, color=color, lw=lw,
                                alpha=alpha,
                                connectionstyle=f"arc3,rad={rad}"),
                zorder=4)


def panel_di(ax):
    ax.set_xlim(0, 10); ax.set_ylim(0, 12); ax.axis("off")

    # 타이틀
    ax.text(5.0, 11.55, "DI_TriCHEF", ha="center", va="center",
            fontsize=18, fontweight="bold", color="#1D3557")
    ax.text(5.0, 11.15,
            "Document  &  Image  도메인",
            ha="center", va="center", fontsize=11, color="#333")

    # 입력 도메인
    shadow_box(ax, 1.4, 9.95, 3.0, 0.85, "Doc",
               C.DOMAIN_COLORS["Doc"], fontsize=12,
               sublabel="PDF · DOCX · TXT · HWP")
    shadow_box(ax, 5.6, 9.95, 3.0, 0.85, "Img",
               C.DOMAIN_COLORS["Img"], fontsize=12,
               sublabel="JPG · PNG · WEBP")

    # 전처리
    shadow_box(ax, 1.4, 8.65, 3.0, 0.7,
               "텍스트 청크 분할", "#5E8FBF", fontsize=9,
               sublabel="≤512 tok, stride 128")
    shadow_box(ax, 5.6, 8.65, 3.0, 0.7,
               "Qwen2-VL 캡션 (KO)", "#5E8FBF", fontsize=9,
               sublabel="OCR fallback")
    arrow(ax, (2.9, 9.95), (2.9, 9.35))
    arrow(ax, (7.1, 9.95), (7.1, 9.35))

    # 3축 인코더
    ax.text(5.0, 7.95, "Tri-CHEF 3-axis Encoders", ha="center",
            fontsize=11, fontweight="bold", color="#1D3557")

    enc_y = 6.95
    shadow_box(ax, 0.7, enc_y, 2.7, 0.85, "Re : SigLIP2",
               C.AXIS_COLORS["Re"], fontsize=10,
               sublabel="1152d · img+text")
    shadow_box(ax, 3.65, enc_y, 2.7, 0.85, "Im : BGE-M3",
               C.AXIS_COLORS["Im"], fontsize=10,
               sublabel="1024d · multilingual")
    shadow_box(ax, 6.6, enc_y, 2.7, 0.85, "Z : DINOv2-L",
               C.AXIS_COLORS["Z"], fontsize=10,
               sublabel="1024d · structure")
    # 위쪽 분배 화살표
    arrow(ax, (2.9, 8.65), (2.05, 7.80), rad=0.15, color="#888", lw=1.0)
    arrow(ax, (2.9, 8.65), (5.00, 7.80), color="#888", lw=1.0)
    arrow(ax, (2.9, 8.65), (7.95, 7.80), rad=-0.15, color="#888", lw=1.0)
    arrow(ax, (7.1, 8.65), (2.05, 7.80), rad=0.20, color="#888", lw=1.0)
    arrow(ax, (7.1, 8.65), (5.00, 7.80), color="#888", lw=1.0)
    arrow(ax, (7.1, 8.65), (7.95, 7.80), rad=-0.05, color="#888", lw=1.0)

    # Gram-Schmidt
    shadow_box(ax, 1.5, 5.65, 7.0, 0.85,
               "Gram-Schmidt 직교화  →  $Im_\\perp$,  $Z_\\perp$",
               "#37474F", fontsize=11)
    arrow(ax, (5.0, 6.95), (5.0, 6.50))

    # 캐시
    shadow_box(ax, 1.5, 4.40, 7.0, 0.80,
               "positional .npy  cache  +  ChromaDB collection",
               "#546E7A", fontsize=10,
               sublabel="cache_{kind}_Re/Im/Z.npy  +  segments.json")
    arrow(ax, (5.0, 5.65), (5.0, 5.20))

    # Hermitian score
    shadow_box(ax, 1.5, 3.10, 7.0, 0.90,
               "Hermitian Score  $s = \\sqrt{A^2 + (\\alpha B)^2 + (\\beta C)^2}$",
               "#1D3557", fontsize=12, sublabel="$\\alpha=0.4,\\;\\beta=0.2$")
    arrow(ax, (5.0, 4.40), (5.0, 4.00))

    # ASF + Lexical (Doc only)
    shadow_box(ax, 0.7, 1.85, 3.7, 0.75,
               "ASF (한글 bigram IDF)", C.MOD_COLORS["ASF"], fontsize=9.5,
               sublabel="γ = 0.25  (현재 default off)")
    shadow_box(ax, 5.6, 1.85, 3.7, 0.75,
               "Lexical Channel (Doc)", C.MOD_COLORS["Lexical"], fontsize=9.5,
               sublabel="β = 0.0   (Doc 한정 ON)")
    arrow(ax, (5.0, 3.10), (2.55, 2.60), rad=0.10, color="#888", lw=1.0)
    arrow(ax, (5.0, 3.10), (7.45, 2.60), rad=-0.10, color="#888", lw=1.0)

    # 출력
    shadow_box(ax, 2.5, 0.55, 5.0, 0.85,
               "Domain Calibration  →  z-score  →  Top-K", "#1D3557",
               fontsize=11)
    arrow(ax, (2.55, 1.85), (4.0, 1.40), rad=0.10, color="#888", lw=1.0)
    arrow(ax, (7.45, 1.85), (6.0, 1.40), rad=-0.10, color="#888", lw=1.0)


def panel_mr(ax):
    ax.set_xlim(0, 10); ax.set_ylim(0, 12); ax.axis("off")

    ax.text(5.0, 11.55, "MR_TriCHEF", ha="center", va="center",
            fontsize=18, fontweight="bold", color="#1D3557")
    ax.text(5.0, 11.15, "Movie  ·  Rec(Voice)  ·  BGM(Music)",
            ha="center", va="center", fontsize=11, color="#333")

    # 입력 3 도메인
    shadow_box(ax, 0.4, 9.95, 2.9, 0.85, "Movie",
               C.DOMAIN_COLORS["Movie"], fontsize=11,
               sublabel="MP4 · MKV · AVI")
    shadow_box(ax, 3.55, 9.95, 2.9, 0.85, "Rec",
               C.DOMAIN_COLORS["Rec"], fontsize=11,
               sublabel="MP3 · WAV (voice)")
    shadow_box(ax, 6.7, 9.95, 2.9, 0.85, "BGM",
               C.DOMAIN_COLORS["BGM"], fontsize=11,
               sublabel="FLAC · MP3 (music)")

    # 전처리 3
    shadow_box(ax, 0.4, 8.55, 2.9, 0.85,
               "Scene 분할 + frame", "#5E8FBF", fontsize=9,
               sublabel="ffmpeg · 1 fps")
    shadow_box(ax, 3.55, 8.55, 2.9, 0.85,
               "Whisper STT", "#5E8FBF", fontsize=9,
               sublabel="large-v3 · KO")
    shadow_box(ax, 6.7, 8.55, 2.9, 0.85,
               "CLAP + librosa", "#5E8FBF", fontsize=9,
               sublabel="audio embedding")
    arrow(ax, (1.85, 9.95), (1.85, 9.40))
    arrow(ax, (5.00, 9.95), (5.00, 9.40))
    arrow(ax, (8.15, 9.95), (8.15, 9.40))

    # 3축 인코더 (Re=SigLIP2-text, Im=BGE-M3)
    ax.text(5.0, 7.85,
            "Cross-modal Hermitian Encoders",
            ha="center", fontsize=11, fontweight="bold",
            color="#1D3557")

    shadow_box(ax, 1.0, 6.85, 3.6, 0.85, "Re : SigLIP2-text",
               C.AXIS_COLORS["Re"], fontsize=10,
               sublabel="1152d · text→frame 정합")
    shadow_box(ax, 5.4, 6.85, 3.6, 0.85, "Im : BGE-M3",
               C.AXIS_COLORS["Im"], fontsize=10,
               sublabel="1024d · STT/lyrics 텍스트")
    # Movie Re 는 frame 측, Im 은 STT 측. 화살표 각각.
    arrow(ax, (1.85, 8.55), (2.80, 7.70), rad=0.10, color="#888", lw=1.0)
    arrow(ax, (5.00, 8.55), (7.20, 7.70), color="#888", lw=1.0)
    arrow(ax, (8.15, 8.55), (2.80, 7.70), rad=0.30, color="#888", lw=1.0)

    # Cross-modal score
    shadow_box(ax, 1.5, 5.50, 7.0, 0.85,
               "$\\sqrt{A^2 + (0.4 B)^2}$  (Movie/Music cross-modal)",
               "#37474F", fontsize=11.5)
    arrow(ax, (5.0, 6.85), (5.0, 6.35))

    # 캐시
    shadow_box(ax, 1.5, 4.20, 7.0, 0.85,
               "MOVIE_CACHE_DIR  /  MUSIC_CACHE_DIR",
               "#546E7A", fontsize=10,
               sublabel="cache_movie_Re/Im.npy  ·  segments.json  ·  vocab")
    arrow(ax, (5.0, 5.50), (5.0, 5.05))

    # ASF + Calibration
    shadow_box(ax, 0.7, 2.95, 3.7, 0.80,
               "ASF (한글 bigram)", C.MOD_COLORS["ASF"], fontsize=9.5,
               sublabel="γ = 0.25  ON  (Movie/Music)")
    shadow_box(ax, 5.6, 2.95, 3.7, 0.80,
               "Crossmodal Calibration", C.MOD_COLORS["LangGraph"],
               fontsize=9.5, sublabel="μ_null + 1.645·σ_null")
    arrow(ax, (5.0, 4.20), (2.55, 3.75), rad=0.10, color="#888", lw=1.0)
    arrow(ax, (5.0, 4.20), (7.45, 3.75), rad=-0.10, color="#888", lw=1.0)

    # LangGraph
    shadow_box(ax, 0.7, 1.65, 8.6, 0.80,
               "LangGraph  Flow  :  Intent → Search → Scan → Select → Generate",
               C.MOD_COLORS["LangGraph"], fontsize=10,
               sublabel="MemorySaver · thread_id · 멀티턴")
    arrow(ax, (2.55, 2.95), (5.0, 2.45), rad=0.05, color="#888", lw=1.0)
    arrow(ax, (7.45, 2.95), (5.0, 2.45), rad=-0.05, color="#888", lw=1.0)

    # 출력
    shadow_box(ax, 2.5, 0.40, 5.0, 0.85,
               "Top-K  +  per-segment timestamps", "#1D3557", fontsize=11)
    arrow(ax, (5.0, 1.65), (5.0, 1.25))


def main():
    fig, axes = plt.subplots(1, 2, figsize=(20, 12))
    fig.suptitle("DI_TriCHEF  vs  MR_TriCHEF  파이프라인 비교",
                 fontsize=20, fontweight="bold", color="#1D3557", y=0.99)

    panel_di(axes[0])
    panel_mr(axes[1])

    # 가운데 구분선
    fig.subplots_adjust(wspace=0.04)

    C.save(fig, "fig02_di_mr_pipeline.png")


if __name__ == "__main__":
    main()
