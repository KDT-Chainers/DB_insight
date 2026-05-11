"""Fig 7 - Weighted Min-Max Fusion + Multi-Signal Floor Filter (PPT square, v3.1).

Corrected fusion weights:
  DI path (Doc/Img): Dense=0.60, Sparse=0.25, ASF=0.15
  AV path (Movie/Rec): Dense=0.60, Sparse=0.15, ASF=0.25  ← swapped from DI
  BGM/Img single-channel: Dense=1.00
"""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from _common import setup_style, save, DOMAIN_COLORS, FLOOR, FUSION_WEIGHTS

setup_style()
fig = plt.figure(figsize=(13, 14))
gs = gridspec.GridSpec(2, 1, figure=fig, hspace=0.42)
fig.suptitle("Fig. 7  Score Fusion Weights & Multi-Signal Floor Filter",
             fontsize=19, fontweight="bold", y=1.01)

domains = ["Doc", "Img", "Movie", "Rec", "BGM"]

# ── (a) Fusion Weights stacked bar ──
ax_f = fig.add_subplot(gs[0])

channel_labels = ["Dense\n(Hermitian)", "Sparse\n(BGE-M3)", "ASF\n(IDF)"]
ch_colors      = ["#2E7D52",            "#1565C0",           "#8E24AA"]
x = np.arange(len(domains))
W = 0.55

bottom = np.zeros(len(domains))
for ch_idx, (ch_label, ch_color) in enumerate(zip(channel_labels, ch_colors)):
    vals = [FUSION_WEIGHTS[d][["dense", "sparse", "asf"][ch_idx]] for d in domains]
    bars = ax_f.bar(x, vals, W, bottom=bottom,
                    color=ch_color, edgecolor="white", lw=1.5,
                    label=ch_label, alpha=0.90)
    for i, v in enumerate(vals):
        if v > 0.05:
            ax_f.text(x[i], bottom[i] + v/2, f"{v:.2f}",
                      ha="center", va="center",
                      fontsize=13, fontweight="bold", color="white")
    bottom += np.array(vals)

ax_f.set_xticks(x)
ax_f.set_xticklabels(domains, fontsize=15, fontweight="bold")
for i, d in enumerate(domains):
    ax_f.get_xticklabels()[i].set_color(DOMAIN_COLORS[d])
ax_f.set_ylabel("Effective Weight", fontsize=15, fontweight="bold")
ax_f.set_ylim(0, 1.25)
ax_f.set_title("(a)  Weighted Min-Max Fusion per Domain",
               fontsize=16, fontweight="bold", pad=14)
ax_f.legend(fontsize=13, loc="upper right", ncol=3, framealpha=0.95)

# Annotations for single-channel domains (no overlap risk)
ax_f.annotate("Img & BGM:\nSingle-channel\n(Dense only)",
              xy=(1, 1.02), xytext=(2.5, 1.10),
              fontsize=12, color="#E07B39",
              arrowprops=dict(arrowstyle="->", color="#E07B39", lw=2),
              bbox=dict(boxstyle="round,pad=0.35", facecolor="#FFF3E0",
                        edgecolor="#E07B39", alpha=0.95))

# AV path note
ax_f.text(3.0, 0.05,
          "AV path (Movie/Rec):\nDense 0.60 · ASF 0.25 · Sparse 0.15",
          ha="center", va="bottom", fontsize=11, color="#8E24AA",
          bbox=dict(boxstyle="round,pad=0.3", facecolor="#F3E5F5",
                    edgecolor="#8E24AA", alpha=0.9))

# ── (b) Floor Thresholds heatmap ──
ax_floor = fig.add_subplot(gs[1])
floor_domains = ["Img", "Doc", "Movie", "Rec", "BGM"]
floor_col_labels = ["min_conf", "min_sim\n(dense)", "min_raw\n_dense"]
matrix = np.array([
    [FLOOR[d]["min_conf"], FLOOR[d]["min_sim"], FLOOR[d]["min_dense"]]
    for d in floor_domains
])

im = ax_floor.imshow(matrix, cmap="RdYlGn_r", aspect="auto",
                     vmin=0.25, vmax=0.90)
cbar = fig.colorbar(im, ax=ax_floor, shrink=0.80, pad=0.03)
cbar.set_label("Threshold", fontsize=14)
cbar.ax.tick_params(labelsize=13)

for i in range(len(floor_domains)):
    for j in range(3):
        v = matrix[i, j]
        color = "white" if v >= 0.70 else "black"
        ax_floor.text(j, i, f"{v:.2f}", ha="center", va="center",
                      fontsize=15, fontweight="bold", color=color)

ax_floor.set_xticks(range(3))
ax_floor.set_xticklabels(floor_col_labels, fontsize=14, fontweight="bold")
ax_floor.set_yticks(range(len(floor_domains)))
ax_floor.set_yticklabels(floor_domains, fontsize=15, fontweight="bold")
for i, d in enumerate(floor_domains):
    ax_floor.get_yticklabels()[i].set_color(DOMAIN_COLORS[d])

ax_floor.set_title("(b)  Multi-Signal Floor Thresholds",
                   fontsize=16, fontweight="bold", pad=14)

ax_floor.text(0.5, -0.15,
              "Any signal below its threshold  →  result is removed from output",
              transform=ax_floor.transAxes, fontsize=13, ha="center",
              style="italic", color="#555555")

fig.tight_layout(rect=[0, 0.02, 1, 0.97])
save(fig, "fig07_fusion_and_floor.png")
