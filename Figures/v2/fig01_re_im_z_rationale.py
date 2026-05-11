"""fig01: Re/Im/Z 모델 선택 근거 — 3-panel infographic.

각 인코더(SigLIP2 / BGE-M3 / DINOv2-L) 의 입력·차원·역할·학습데이터·
선택 이유를 한눈에 비교.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

import _common as C
C.setup_style()

ENCODERS = [
    {
        "axis":   "Re  (실수축)",
        "model":  "SigLIP2",
        "id":     "google/siglip2-so400m-patch14-384",
        "dim":    1152,
        "input":  "텍스트 ↔ 이미지\n(cross-modal)",
        "role":   "시각·언어 정렬 / 핵심 신호",
        "train":  "WebLI 10B+\n(image-text pairs)",
        "why":    [
            "Sigmoid loss → 단일 쿼리 retrieval에 최적",
            "텍스트·이미지 동일 임베딩 공간",
            "다국어 (Korean 포함) 토크나이저",
            "Movie/Music: 텍스트→프레임 직접 정합",
        ],
        "color":  C.AXIS_COLORS["Re"],
    },
    {
        "axis":   "Im  (허수축)",
        "model":  "BGE-M3",
        "id":     "BAAI/bge-m3",
        "dim":    1024,
        "input":  "텍스트\n(다국어, dense+sparse)",
        "role":   "언어 의미 / 보조 채널",
        "train":  "M3 corpus\n(>100 langs)",
        "why":    [
            "Dense + Sparse + ColBERT 멀티 채널",
            "한국어 retrieval SOTA (MIRACL-ko)",
            "8K 토큰 컨텍스트 (장문 PDF 청크)",
            "감쇠 α=0.4: 텍스트 편중 방지",
        ],
        "color":  C.AXIS_COLORS["Im"],
    },
    {
        "axis":   "Z  (구조축)",
        "model":  "DINOv2-Large",
        "id":     "facebook/dinov2-large",
        "dim":    1024,
        "input":  "이미지\n(self-supervised)",
        "role":   "구조·레이아웃 / 직교 보강",
        "train":  "LVD-142M\n(self-distillation)",
        "why":    [
            "Caption 편향 0 — 순수 시각 구조",
            "CLS 토큰 → 전역 레이아웃 신호",
            "Gram-Schmidt 직교화 후 Z⊥",
            "감쇠 β=0.2: 극단 왜곡 방지",
        ],
        "color":  C.AXIS_COLORS["Z"],
    },
]


def draw_card(ax, x, y, w, h, enc):
    # 카드 배경 (그라데이션 효과 — 단색 + 헤더)
    body = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02",
                          facecolor="white", edgecolor=enc["color"],
                          linewidth=2.4, zorder=2)
    shadow = FancyBboxPatch((x + 0.04, y - 0.04), w, h,
                            boxstyle="round,pad=0.02",
                            facecolor="#999", edgecolor="none",
                            alpha=0.18, zorder=1)
    ax.add_patch(shadow)
    ax.add_patch(body)

    # 헤더 밴드
    head = FancyBboxPatch((x, y + h - 0.95), w, 0.95,
                          boxstyle="round,pad=0.02",
                          facecolor=enc["color"], edgecolor="none",
                          alpha=0.95, zorder=3)
    ax.add_patch(head)
    ax.text(x + w / 2, y + h - 0.30, enc["axis"], ha="center", va="center",
            fontsize=15, fontweight="bold", color="white", zorder=4)
    ax.text(x + w / 2, y + h - 0.65, enc["model"], ha="center", va="center",
            fontsize=18, fontweight="bold", color="white", zorder=4)
    ax.text(x + w / 2, y + h - 0.88, enc["id"], ha="center", va="center",
            fontsize=7.5, color="white", style="italic",
            alpha=0.92, zorder=4)

    # 메타 그리드 (4개 셀)
    meta_rows = [
        ("입력 모달리티", enc["input"]),
        ("출력 차원",     f"{enc['dim']}d"),
        ("역할",          enc["role"]),
        ("학습 데이터",   enc["train"]),
    ]
    cell_y = y + h - 1.05
    for i, (k, v) in enumerate(meta_rows):
        cy = cell_y - 0.55 - i * 0.55
        ax.text(x + 0.20, cy, k, ha="left", va="center",
                fontsize=8.5, color="#555", fontweight="bold")
        ax.text(x + w - 0.20, cy, v, ha="right", va="center",
                fontsize=8.5, color="#222", linespacing=1.2)
        ax.plot([x + 0.15, x + w - 0.15], [cy - 0.27, cy - 0.27],
                color="#DDD", linewidth=0.6, zorder=2)

    # 선택 근거 박스
    why_top = y + h - 3.40
    ax.text(x + w / 2, why_top + 0.05, "선택 근거", ha="center", va="bottom",
            fontsize=10, color=enc["color"], fontweight="bold")
    for i, line in enumerate(enc["why"]):
        ay = why_top - 0.40 - i * 0.45
        # 불릿 점
        ax.plot([x + 0.30], [ay], marker="o", markersize=5,
                color=enc["color"], zorder=4)
        ax.text(x + 0.55, ay, line, ha="left", va="center",
                fontsize=8.8, color="#222", linespacing=1.2)


def main():
    fig, ax = plt.subplots(figsize=(18, 11))
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 11)
    ax.axis("off")

    # 타이틀
    ax.text(9.0, 10.55, "Tri-CHEF  3축 인코더 선택 근거",
            ha="center", va="center", fontsize=22, fontweight="bold",
            color="#1D3557")
    ax.text(9.0, 10.05,
            "Hermitian 점수 $s(q,d) = \\sqrt{A^2 + (\\alpha B)^2 + (\\beta C)^2}$,  "
            "$\\alpha=0.4$ (Im 감쇠),  $\\beta=0.2$ (Z 감쇠)",
            ha="center", va="center", fontsize=12, color="#333")

    # 3개 카드 배치
    card_w = 5.4
    card_h = 8.4
    gap = 0.45
    total_w = 3 * card_w + 2 * gap
    x0 = (18 - total_w) / 2
    y0 = 0.6
    for i, enc in enumerate(ENCODERS):
        cx = x0 + i * (card_w + gap)
        draw_card(ax, cx, y0, card_w, card_h, enc)

    # 하단 융합 다이어그램 — 작게
    fuse_y = 0.10
    ax.annotate("", xy=(9.0, fuse_y + 0.30), xytext=(9.0, y0 - 0.15),
                arrowprops=dict(arrowstyle="-|>", color="#888",
                                lw=1.6, alpha=0.6))

    # Footnote
    ax.text(9.0, 0.08,
            "Re·Im·Z 는 Gram-Schmidt 직교화 후 결합 → 채널간 중복 제거",
            ha="center", va="center", fontsize=9, color="#666",
            style="italic")

    C.save(fig, "fig01_re_im_z_rationale.png")


if __name__ == "__main__":
    main()
