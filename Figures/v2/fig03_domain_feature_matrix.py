"""fig03: 도메인×기능 적용 매트릭스 + 우측 hit@5 막대.

상태:  N/A · 적용(효과있음) · 적용(효과없음) · 성능저하  4단계 색상.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
import numpy as np

import _common as C
C.setup_style()


STATE_COLOR = {
    0: "#ECEFF1",  # N/A
    1: "#43A047",  # 적용 효과있음
    2: "#FBC02D",  # 적용 효과없음
    3: "#E53935",  # 성능저하
}
STATE_LABEL = {
    0: "N/A",
    1: "적용 · 효과 있음",
    2: "적용 · 효과 없음",
    3: "적용 · 성능 저하",
}
# matplotlib mathtext (always renders) — Malgun Gothic 글리프 누락 회피
STATE_TEXT = {
    0: r"$-$",
    1: r"$\checkmark$",
    2: r"$\approx$",
    3: r"$\downarrow$",
}


def main():
    fig = plt.figure(figsize=(17, 8.5))
    gs = fig.add_gridspec(1, 2, width_ratios=[3.4, 1.0], wspace=0.18)
    ax = fig.add_subplot(gs[0, 0])
    axb = fig.add_subplot(gs[0, 1])

    # ---- 매트릭스 ----
    features = list(C.APPLICATION_MATRIX.keys())
    domains  = C.DOMAIN_ORDER

    M = np.zeros((len(features), len(domains)), dtype=int)
    for i, feat in enumerate(features):
        for j, dom in enumerate(domains):
            M[i, j] = C.APPLICATION_MATRIX[feat][dom]

    # 색상 매트릭스
    color_grid = np.empty(M.shape, dtype=object)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            color_grid[i, j] = STATE_COLOR[M[i, j]]

    # 그리기 (수동 셀)
    cell_w, cell_h = 1.0, 1.0
    for i in range(len(features)):
        for j in range(len(domains)):
            x = j * cell_w
            y = (len(features) - 1 - i) * cell_h
            ax.add_patch(plt.Rectangle((x, y), cell_w, cell_h,
                                       facecolor=color_grid[i, j],
                                       edgecolor="white", linewidth=2,
                                       zorder=2))
            txt_color = "white" if M[i, j] in (1, 3) else "#222"
            ax.text(x + cell_w / 2, y + cell_h / 2, STATE_TEXT[M[i, j]],
                    ha="center", va="center", fontsize=18,
                    fontweight="bold", color=txt_color, zorder=3)

    ax.set_xlim(-0.05, len(domains) * cell_w + 0.05)
    ax.set_ylim(-0.05, len(features) * cell_h + 0.05)

    # 축 라벨
    ax.set_xticks([j * cell_w + cell_w / 2 for j in range(len(domains))])
    ax.set_xticklabels(domains, fontsize=12, fontweight="bold")
    for j, dom in enumerate(domains):
        ax.get_xticklabels()[j].set_color(C.DOMAIN_COLORS[dom])

    ax.set_yticks([(len(features) - 1 - i) * cell_h + cell_h / 2
                   for i in range(len(features))])
    ax.set_yticklabels(features, fontsize=11)

    # X-axis label 위로
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")

    ax.tick_params(axis="both", which="both", length=0)
    ax.set_aspect("equal")
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.set_title("Tri-CHEF  도메인 × 기능 적용 매트릭스",
                 fontsize=15, pad=14, color="#1D3557")

    # ---- 우측 hit@5 막대 ----
    hits = [C.HIT_AT_5[d] for d in domains]
    colors = [C.DOMAIN_COLORS[d] for d in domains]
    y_pos = np.arange(len(domains))[::-1]

    # Doc 만 hit@50 까지의 ghost bar 추가 (self-retrieval 코퍼스 한계 시각화)
    doc_idx = domains.index("Doc")
    doc_y = y_pos[doc_idx]
    h50 = C.HIT_DOC_EXTENDED["hit_at_50"]
    h10 = C.HIT_DOC_EXTENDED["hit_at_10"]
    axb.barh([doc_y], [h50], color=C.DOMAIN_COLORS["Doc"], alpha=0.18,
             edgecolor=C.DOMAIN_COLORS["Doc"], linewidth=1.0,
             hatch="////", height=0.62, zorder=1)
    axb.barh([doc_y], [h10], color=C.DOMAIN_COLORS["Doc"], alpha=0.40,
             edgecolor="none", height=0.78, zorder=2)

    bars = axb.barh(y_pos, hits, color=colors, edgecolor="white",
                    linewidth=1.4, alpha=0.95, zorder=3)
    axb.set_yticks(y_pos)
    axb.set_yticklabels(domains, fontsize=11)
    for i, (b, v) in enumerate(zip(bars, hits)):
        d = domains[i]
        marker = "*" if d == "Doc" else ""
        # Doc 만 hit@5 라벨 + hit@50 ghost label
        if d == "Doc":
            axb.text(v + 0.012, b.get_y() + b.get_height() / 2,
                     f"{v:.2f}*", ha="left", va="center",
                     fontsize=11, fontweight="bold", color="#222")
            axb.text(h50 + 0.012, b.get_y() + b.get_height() / 2 - 0.10,
                     f"hit@50={h50:.2f}",
                     ha="left", va="center", fontsize=8.0,
                     color=C.DOMAIN_COLORS["Doc"], style="italic")
        else:
            axb.text(min(v + 0.02, 0.96), b.get_y() + b.get_height() / 2,
                     f"{v:.2f}", ha="left", va="center",
                     fontsize=11, fontweight="bold", color="#222")

    axb.set_xlim(0, 1.1)
    axb.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    axb.set_xlabel("hit@5  (실측 ablation 기준)", fontsize=10)
    axb.set_title("도메인 성능", fontsize=13, pad=12, color="#1D3557")
    axb.grid(axis="x", linestyle="--", alpha=0.3)
    for spine in ("top", "right"):
        axb.spines[spine].set_visible(False)
    axb.invert_yaxis()  # Doc 위로

    # Doc caveat 박스
    axb.text(0.04, -0.18,
             "* Doc: 34.7k 청크 self-retrieval bench (n=30, 80-char query).\n"
             "   진한색=hit@5, 중간=hit@10, hatch=hit@50. "
             "운영 검색은 별개로 정상.",
             transform=axb.transAxes, ha="left", va="top",
             fontsize=7.8, color="#555", linespacing=1.35,
             style="italic")

    # 범례 (상단)
    handles = [mpatches.Patch(facecolor=STATE_COLOR[s], edgecolor="white",
                              label=STATE_LABEL[s]) for s in [1, 2, 3, 0]]
    fig.legend(handles=handles, loc="upper center",
               bbox_to_anchor=(0.5, 0.04),
               ncol=4, frameon=True, framealpha=0.95,
               fontsize=10, edgecolor="#CCC")

    # 푸터 메모
    fig.text(0.5, -0.005,
             "ASF=Attention-Similarity Filter (한글 bigram IDF) ·  "
             "Lexical=BM25-style 토큰 매칭 ·  "
             "Rerank=BGE-Reranker (post)  ·  "
             "LangGraph=AI-Mode flow",
             ha="center", va="bottom", fontsize=8.8, color="#666",
             style="italic")

    fig.suptitle("", y=0.98)
    plt.subplots_adjust(top=0.92, bottom=0.10)

    C.save(fig, "fig03_domain_feature_matrix.png")


if __name__ == "__main__":
    main()
