"""Fig 8 - Ablation Study: Waterfall only, Sparse/ASF split (PPT square, v3.1)."""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
from _common import setup_style, save, ABLATION

setup_style()
fig, ax = plt.subplots(figsize=(13, 12))
fig.suptitle("Fig. 8  Ablation Study: Incremental Component Contribution",
             fontsize=19, fontweight="bold", y=1.01)

# Build deltas from ABLATION dict (7 items with Sparse/ASF split)
configs = list(ABLATION.keys())
values  = list(ABLATION.values())

deltas = [values[0]]
for i in range(1, len(values)):
    deltas.append(values[i] - values[i - 1])

labels = [
    "Re only\n(base)",
    "+ Im\n(+13pp)",
    "+ Z\n(+7pp)",
    "+ Gram-\nSchmidt\n(+7pp)",
    "+ Sparse\n(+0pp)",
    "+ ASF\n(+0pp)",
    "+ Calib.\n(+6pp)",
]

bottoms = [0]
for i in range(1, len(deltas)):
    bottoms.append(sum(deltas[:i]))

# Color scheme: axis colors → pipeline channels → calibration
colors = [
    "#2E7D52",   # Re only — green
    "#1565C0",   # + Im    — blue
    "#8E24AA",   # + Z     — purple
    "#E65100",   # + GS    — orange
    "#607D8B",   # + Sparse — slate
    "#795548",   # + ASF   — brown
    "#C62828",   # + Calib — red
]

n = len(deltas)
x = np.arange(n)
bar_w = 0.60

for i, (d, b, col) in enumerate(zip(deltas, bottoms, colors)):
    ax.bar(i, d, bar_w, bottom=b, color=col, edgecolor="white", lw=2.0, zorder=3)

    # Delta label inside bar (skip zero-height bars)
    if d > 0:
        ax.text(i, b + d/2, f"+{d}%",
                ha="center", va="center",
                fontsize=15, fontweight="bold", color="white", zorder=4)
    elif d == 0:
        ax.text(i, b + 1.5, "0%",
                ha="center", va="bottom",
                fontsize=13, color=col, fontweight="bold", zorder=4)

    # Cumulative label above bar
    top = b + d
    ax.text(i, top + 1.8, f"{top}%",
            ha="center", va="bottom",
            fontsize=14, fontweight="bold", color="#222222", zorder=4)

# Connector lines between bars
for i in range(n - 1):
    top = bottoms[i] + deltas[i]
    ax.plot([i + bar_w/2, i + 1 - bar_w/2], [top, top],
            color="#AAAAAA", lw=1.5, ls="--", zorder=2)

# 90% target line
ax.axhline(90, color="#AAAAAA", ls="--", lw=1.8, alpha=0.7, zorder=1)
ax.text(n - 0.5, 91.5, "90% target", fontsize=13, color="#AAAAAA",
        ha="right", fontweight="bold")

# Axis formatting
ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=13, fontweight="bold")
ax.set_ylabel("Top-1 Confidence ≥ 0.90  (%)", fontsize=16, fontweight="bold")
ax.set_ylim(0, 108)
ax.set_xlim(-0.55, n - 0.45)

# Category separators
ax.axvspan(-0.5,  3.5, alpha=0.04, color="#2E7D52", zorder=0)  # axis phase
ax.axvspan(3.5,   5.5, alpha=0.04, color="#607D8B", zorder=0)  # channel phase
ax.axvspan(5.5,   6.5, alpha=0.04, color="#C62828", zorder=0)  # calibration

# Category labels
ax.text(1.5,  105, "Embedding Axes", ha="center", fontsize=13,
        color="#2E7D52", fontweight="bold")
ax.text(4.5,  105, "Fusion\nChannels", ha="center", fontsize=13,
        color="#607D8B", fontweight="bold")
ax.text(6.0,  105, "Calib.", ha="center", fontsize=13,
        color="#C62828", fontweight="bold")
ax.axvline(3.5, color="#CCCCCC", lw=1.2, ls=":", zorder=1)
ax.axvline(5.5, color="#CCCCCC", lw=1.2, ls=":", zorder=1)

# Summary box — bottom-left (below the bars, avoids category labels)
summary = ("Total gain:  60% → 93%  (+33pp)\n"
           "Largest contributor:  +Im  (+13pp)\n"
           "Calibration:  +6pp  (final stage)\n"
           "Sparse & ASF:  +0pp  (on this metric)")
ax.text(0.02, 0.28, summary, transform=ax.transAxes,
        fontsize=12, va="top", ha="left",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#E8F5E9",
                  edgecolor="#4CAF50", alpha=0.95, lw=1.5))

save(fig, "fig08_ablation_study.png")
