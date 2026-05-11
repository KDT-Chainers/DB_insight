"""Fig 4 - Calibration Parameters Comparison by Domain (PPT square, v3.1)."""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm
from _common import setup_style, save, DOMAIN_COLORS, CAL

setup_style()
fig, axes = plt.subplots(2, 2, figsize=(13, 13))
fig.suptitle("Fig. 4  Calibration Parameters Comparison by Domain",
             fontsize=19, fontweight="bold", y=1.01)

domains = ["Doc", "Img", "Movie", "Rec"]
colors = [DOMAIN_COLORS[d] for d in domains]
x = np.arange(len(domains))
W = 0.55

def label_bars(ax, bars, vals, fmt="{:.4f}", offset_frac=0.03, fs=13, col=None):
    ylim = ax.get_ylim()
    offset = (ylim[1] - ylim[0]) * offset_frac
    for b, v in zip(bars, vals):
        c = col or b.get_facecolor()
        ax.text(b.get_x() + b.get_width()/2, v + offset, fmt.format(v),
                ha="center", va="bottom", fontsize=fs, fontweight="bold", color=c)

# ── (a) mu_null ──
ax = axes[0, 0]
vals = [CAL[d]["mu"] for d in domains]
bars = ax.bar(x, vals, W, color=colors, edgecolor="white", lw=2)
ax.set_ylim(0, 1.10)
label_bars(ax, bars, vals, "{:.4f}", 0.02, 13)
ax.errorbar(x, vals, yerr=[CAL[d]["sigma"] for d in domains],
            fmt="none", ecolor="#333333", elinewidth=2, capsize=9, capthick=2)
ax.axhline(0.5, color="#AAAAAA", ls="--", lw=1.5, alpha=0.6)
ax.text(3.48, 0.515, "0.5", fontsize=11, color="#AAAAAA", ha="right")
ax.set_title(r"(a)  $\mu_{\mathrm{null}}$  (±$\sigma$ error bars)",
             fontsize=16, fontweight="bold", pad=14)
ax.set_ylabel(r"$\mu_{\mathrm{null}}$", fontsize=16, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(domains, fontsize=15, fontweight="bold")
for i, d in enumerate(domains):
    ax.get_xticklabels()[i].set_color(DOMAIN_COLORS[d])

# ── (b) sigma_null ──
ax = axes[0, 1]
vals = [CAL[d]["sigma"] for d in domains]
bars = ax.bar(x, vals, W, color=colors, edgecolor="white", lw=2)
ax.set_ylim(0, max(vals) * 1.55)
label_bars(ax, bars, vals, "{:.4f}", 0.02, 13)
ax.set_title(r"(b)  $\sigma_{\mathrm{null}}$",
             fontsize=16, fontweight="bold", pad=14)
ax.set_ylabel(r"$\sigma_{\mathrm{null}}$", fontsize=16, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(domains, fontsize=15, fontweight="bold")
for i, d in enumerate(domains):
    ax.get_xticklabels()[i].set_color(DOMAIN_COLORS[d])

# ── (c) z* = Phi^{-1}(1 - FAR) ──
ax = axes[1, 0]
z_vals  = [norm.ppf(1 - CAL[d]["FAR"]) for d in domains]
far_vals = [CAL[d]["FAR"] for d in domains]
bars = ax.bar(x, z_vals, W, color=colors, edgecolor="white", lw=2)
ax.set_ylim(0, 2.3)
for b, v, far, d in zip(bars, z_vals, far_vals, domains):
    ax.text(b.get_x() + b.get_width()/2, v + 0.05,
            f"{v:.3f}", ha="center", va="bottom", fontsize=13, fontweight="bold",
            color=DOMAIN_COLORS[d])
    ax.text(b.get_x() + b.get_width()/2, v / 2,
            f"FAR={far:.0%}", ha="center", va="center",
            fontsize=12, fontweight="bold", color="white")
ax.axhline(1.645, color="#AAAAAA", ls="--", lw=1.5, alpha=0.7)
ax.text(3.48, 1.68, r"$z^*$=1.645 (FAR=5%)", fontsize=11,
        color="#AAAAAA", ha="right")
ax.set_title(r"(c)  $z^* = \Phi^{-1}(1-\mathrm{FAR})$",
             fontsize=16, fontweight="bold", pad=14)
ax.set_ylabel(r"$z^*$  (quantile)", fontsize=16, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(domains, fontsize=15, fontweight="bold")
for i, d in enumerate(domains):
    ax.get_xticklabels()[i].set_color(DOMAIN_COLORS[d])

# ── (d) tau ──
ax = axes[1, 1]
vals = [CAL[d]["tau"] for d in domains]
bars = ax.bar(x, vals, W, color=colors, edgecolor="white", lw=2)
ax.set_ylim(0, 1.15)
for b, v, d in zip(bars, vals, domains):
    ax.text(b.get_x() + b.get_width()/2, v + 0.02,
            f"{v:.4f}", ha="center", va="bottom", fontsize=13,
            fontweight="bold", color="#C62828")
ax.set_title(r"(d)  $\tau = \mu + z^* \cdot \sigma$",
             fontsize=16, fontweight="bold", pad=14)
ax.set_ylabel(r"$\tau$  (abs_threshold)", fontsize=16, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(domains, fontsize=15, fontweight="bold")
for i, d in enumerate(domains):
    ax.get_xticklabels()[i].set_color(DOMAIN_COLORS[d])

ax.text(0.50, 0.93,
        r"$\tau = \mu_{\mathrm{null}} + \Phi^{-1}(1-\mathrm{FAR}) \cdot \sigma_{\mathrm{null}}$",
        transform=ax.transAxes, fontsize=13, ha="center", va="top",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#FFF3E0",
                  edgecolor="#E65100", alpha=0.95))

fig.tight_layout(rect=[0, 0, 1, 0.97])
save(fig, "fig04_calibration_params_comparison.png")
