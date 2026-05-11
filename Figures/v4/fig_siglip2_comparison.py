"""Figures/v4/fig_siglip2_comparison.py — SigLIP2 SO400M vs Large 시각화.

입력: DI_TriCHEF/results/*_siglip2_bench.json
출력:
  - fig_siglip2_comparison.png  (종합 비교: 막대 + violin + 사양 표)
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import setup_style, save, load_latest_result, MODEL_COLORS


def plot_comparison(data: dict) -> None:
    setup_style()

    models = data["models"]
    so = models["SO400M"]
    lg = models["Large"]

    fig = plt.figure(figsize=(16, 10))
    gs = gridspec.GridSpec(2, 2, hspace=0.35, wspace=0.30)
    fig.suptitle("SigLIP2 Model Comparison: SO400M (1152d) vs Large (1024d)",
                 fontsize=16, fontweight="bold")

    # ── (1) Cross-modal R@1/R@5/MRR 막대 비교 ────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    metrics = ["r1", "r5", "mrr"]
    labels = ["R@1", "R@5", "MRR"]
    x = np.arange(len(metrics))
    w = 0.30

    so_vals = [so["cross_modal"][m] for m in metrics]
    lg_vals = [lg["cross_modal"][m] for m in metrics]

    bars1 = ax1.bar(x - w/2, so_vals, w, label="SO400M (1152d)",
                    color=MODEL_COLORS["SO400M"], alpha=0.85)
    bars2 = ax1.bar(x + w/2, lg_vals, w, label="Large (1024d)",
                    color=MODEL_COLORS["Large"], alpha=0.85)

    # 값 표시
    for bars in (bars1, bars2):
        for bar in bars:
            h = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2, h + 0.01,
                     f"{h:.3f}", ha="center", va="bottom", fontsize=9)

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("Score")
    ax1.set_ylim(0, 1.15)
    ax1.set_title("Cross-modal Retrieval (Caption -> Image)")
    ax1.legend(loc="upper right")

    # ── (2) Pairwise cosine similarity 분포 비교 ──────────────
    ax2 = fig.add_subplot(gs[0, 1])

    pw_data = {
        "SO400M": so["pairwise"],
        "Large": lg["pairwise"],
    }

    model_names = list(pw_data.keys())
    means = [pw_data[m]["mean"] for m in model_names]
    stds = [pw_data[m]["std"] for m in model_names]
    mins = [pw_data[m]["min"] for m in model_names]
    maxs = [pw_data[m]["max"] for m in model_names]
    medians = [pw_data[m]["median"] for m in model_names]

    x2 = np.arange(len(model_names))
    colors = [MODEL_COLORS[m] for m in model_names]

    # Mean +/- Std 막대
    ax2.bar(x2, means, 0.5, yerr=stds, capsize=8,
            color=colors, alpha=0.7, edgecolor="black", linewidth=0.5)

    # Min/Max/Median 점 표시
    for i, m in enumerate(model_names):
        ax2.plot(i, mins[i], "v", color="black", markersize=6)
        ax2.plot(i, maxs[i], "^", color="black", markersize=6)
        ax2.plot(i, medians[i], "D", color="white", markersize=5,
                 markeredgecolor="black", markeredgewidth=1.5)

    ax2.set_xticks(x2)
    ax2.set_xticklabels(model_names)
    ax2.set_ylabel("Cosine Similarity")
    ax2.set_title("Pairwise Image Similarity Distribution")

    # 범례
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker="D", color="w", markerfacecolor="white",
               markeredgecolor="black", markersize=6, label="Median"),
        Line2D([0], [0], marker="v", color="w", markerfacecolor="black",
               markersize=6, label="Min"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="black",
               markersize=6, label="Max"),
    ]
    ax2.legend(handles=legend_elements, loc="upper right", fontsize=9)

    # 낮은 mean = 더 나은 discrimination 주석
    better = "SO400M" if means[0] < means[1] else "Large"
    ax2.annotate(
        f"Lower mean = Better discrimination\n-> {better} 우수",
        xy=(0.02, 0.98), xycoords="axes fraction",
        ha="left", va="top", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#F5F5F5",
                  edgecolor="#CCCCCC", alpha=0.9),
    )

    # ── (3) Effective Dimensionality 비교 ─────────────────────
    ax3 = fig.add_subplot(gs[1, 0])

    ed_metrics = ["total_dim", "eff_dim_95", "eff_dim_99"]
    ed_labels = ["Total Dim", "Eff Dim (95%)", "Eff Dim (99%)"]
    x3 = np.arange(len(ed_metrics))

    so_ed = [so["effective_dim"][m] for m in ed_metrics]
    lg_ed = [lg["effective_dim"][m] for m in ed_metrics]

    bars3 = ax3.bar(x3 - w/2, so_ed, w, label="SO400M",
                    color=MODEL_COLORS["SO400M"], alpha=0.85)
    bars4 = ax3.bar(x3 + w/2, lg_ed, w, label="Large",
                    color=MODEL_COLORS["Large"], alpha=0.85)

    for bars in (bars3, bars4):
        for bar in bars:
            h = bar.get_height()
            ax3.text(bar.get_x() + bar.get_width()/2, h + 5,
                     f"{int(h)}", ha="center", va="bottom", fontsize=9)

    ax3.set_xticks(x3)
    ax3.set_xticklabels(ed_labels)
    ax3.set_ylabel("Dimensions")
    ax3.set_title("Effective Dimensionality (PCA)")
    ax3.legend(loc="upper left")

    # ── (4) 모델 사양 요약 테이블 ─────────────────────────────
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.axis("off")

    # Cross-modal delta 계산
    cm_delta_r1 = lg["cross_modal"]["r1"] - so["cross_modal"]["r1"]
    cm_delta_r5 = lg["cross_modal"]["r5"] - so["cross_modal"]["r5"]

    table_data = [
        ["", "SO400M", "Large", "Delta"],
        ["Model ID", "so400m-naflex", "large-p16-256", "-"],
        ["Parameters", "~400M", "~303M", "-97M"],
        ["Output Dim", "1152d", "1024d", "-128d"],
        ["Gram-Schmidt", "N/A (dim mismatch)", "Possible", "-"],
        ["Cross-modal R@1", f"{so['cross_modal']['r1']:.3f}",
         f"{lg['cross_modal']['r1']:.3f}", f"{cm_delta_r1:+.3f}"],
        ["Cross-modal R@5", f"{so['cross_modal']['r5']:.3f}",
         f"{lg['cross_modal']['r5']:.3f}", f"{cm_delta_r5:+.3f}"],
        ["Pairwise Mean", f"{so['pairwise']['mean']:.4f}",
         f"{lg['pairwise']['mean']:.4f}",
         f"{lg['pairwise']['mean'] - so['pairwise']['mean']:+.4f}"],
        ["Eff Dim (95%)", f"{so['effective_dim']['eff_dim_95']}",
         f"{lg['effective_dim']['eff_dim_95']}",
         f"{lg['effective_dim']['eff_dim_95'] - so['effective_dim']['eff_dim_95']:+d}"],
    ]

    table = ax4.table(
        cellText=table_data[1:],
        colLabels=table_data[0],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.6)

    # 헤더 스타일
    for j in range(4):
        table[0, j].set_facecolor("#37474F")
        table[0, j].set_text_props(color="white", fontweight="bold")

    # 행 색상 교차
    for i in range(1, len(table_data)):
        color = "#FAFAFA" if i % 2 == 0 else "white"
        for j in range(4):
            table[i, j].set_facecolor(color)

    # Delta 열 색상 (양수=녹색, 음수=빨간)
    for i in range(1, len(table_data)):
        cell = table[i, 3]
        text = table_data[i][3]
        if text.startswith("+"):
            cell.set_text_props(color="#2E7D32")
        elif text.startswith("-") and text != "-":
            cell.set_text_props(color="#C62828")

    ax4.set_title("Model Specification Summary", fontsize=14,
                  fontweight="bold", pad=15)

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    save(fig, "fig_siglip2_comparison.png")


def main() -> None:
    data = load_latest_result("siglip2_bench")
    plot_comparison(data)

    # 결론 출력
    so = data["models"]["SO400M"]
    lg = data["models"]["Large"]
    d = lg["cross_modal"]["r5"] - so["cross_modal"]["r5"]
    print(f"\nCross-modal R@5 delta (Large - SO400M): {d:+.3f}")
    if d > 0:
        print("  -> Large가 cross-modal 검색에서 우수")
    elif d < 0:
        print("  -> SO400M이 cross-modal 검색에서 우수")
    else:
        print("  -> 동등")


if __name__ == "__main__":
    main()
