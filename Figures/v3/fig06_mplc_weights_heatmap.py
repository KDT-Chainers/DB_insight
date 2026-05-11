"""Fig 6 - MPLC Feature Weights Heatmap + AUC (PPT square, v3.1)."""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import Normalize
from _common import setup_style, save, MPLC_WEIGHTS, DOMAIN_COLORS

setup_style()
fig = plt.figure(figsize=(14, 13))
gs = gridspec.GridSpec(1, 2, figure=fig,
                       width_ratios=[3, 1], wspace=0.22)
fig.suptitle("Fig. 6  MPLC Logistic Regression Weights by Domain",
             fontsize=19, fontweight="bold", y=1.01)

domains  = ["Doc", "Img", "Movie", "Rec", "BGM"]
features = ["dense", "sparse", "asf", "keyword", "filename", "z_dense"]
feat_labels = ["dense", "sparse", "asf", "keyword\n_count", "filename\n_substr", "z_dense"]

# ── (a) Heatmap ──
ax_h = fig.add_subplot(gs[0])
matrix = np.array([[MPLC_WEIGHTS[d][f] for f in features] for d in domains])

im = ax_h.imshow(matrix, cmap="YlOrRd", aspect="auto",
                 norm=Normalize(vmin=0, vmax=18))
cbar = fig.colorbar(im, ax=ax_h, shrink=0.80, pad=0.03)
cbar.set_label("Weight magnitude", fontsize=14)
cbar.ax.tick_params(labelsize=13)

# Cell values
for i in range(len(domains)):
    for j in range(len(features)):
        v = matrix[i, j]
        color = "#CCCCCC" if v == 0 else ("white" if v > 10 else "black")
        txt = f"{v:.2f}" if v > 0 else "—"
        ax_h.text(j, i, txt, ha="center", va="center",
                  fontsize=14, fontweight="bold", color=color)

ax_h.set_xticks(range(len(features)))
ax_h.set_xticklabels(feat_labels, fontsize=13, fontweight="bold", ha="center")
ytick_labels = [f"{d}  (bias={MPLC_WEIGHTS[d]['bias']:.1f})"
                for d in domains]
ax_h.set_yticks(range(len(domains)))
ax_h.set_yticklabels(ytick_labels, fontsize=13, fontweight="bold")
for i, d in enumerate(domains):
    ax_h.get_yticklabels()[i].set_color(DOMAIN_COLORS[d])
ax_h.invert_yaxis()
ax_h.set_title("(a)  Feature Weights  (MPLC Logistic Regression)",
               fontsize=16, fontweight="bold", pad=14)

# ── (b) AUC bars ──
ax_a = fig.add_subplot(gs[1])
auc_vals = [MPLC_WEIGHTS[d]["auc"] for d in domains]
bars = ax_a.barh(range(len(domains)), auc_vals,
                 color=[DOMAIN_COLORS[d] for d in domains],
                 edgecolor="white", lw=2, height=0.6)

for b, v in zip(bars, auc_vals):
    ax_a.text(v + 0.002, b.get_y() + b.get_height()/2,
              f"{v:.3f}", va="center", fontsize=14, fontweight="bold")

ax_a.set_yticks(range(len(domains)))
ax_a.set_yticklabels(domains, fontsize=15, fontweight="bold")
for i, d in enumerate(domains):
    ax_a.get_yticklabels()[i].set_color(DOMAIN_COLORS[d])
ax_a.invert_yaxis()
ax_a.set_xlim(0.88, 1.02)
ax_a.set_xlabel("CV-AUC", fontsize=15, fontweight="bold")
ax_a.set_title("(b)  CV-AUC", fontsize=16, fontweight="bold", pad=14)
ax_a.axvline(0.95, color="#AAAAAA", ls="--", lw=1.5, alpha=0.7)
ax_a.text(0.952, 4.5, "0.95", fontsize=12, color="#AAAAAA")

fig.tight_layout(rect=[0, 0, 1, 0.97])
save(fig, "fig06_mplc_weights_heatmap.png")
