"""Fig 1 - Tri-CHEF 3-Axis Architecture (PPT square, v3.1)."""
from __future__ import annotations
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
from _common import setup_style, save, AXIS_COLORS, DOMAIN_COLORS

setup_style()
fig, ax = plt.subplots(figsize=(13, 13))
ax.set_xlim(0, 13)
ax.set_ylim(0, 13)
ax.axis("off")
fig.suptitle("Fig. 1  Tri-CHEF 3-Axis Architecture",
             fontsize=20, fontweight="bold", y=0.98)


def rbox(ax, x, y, w, h, color, alpha=0.93):
    r = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.22",
                       facecolor=color, edgecolor="white", lw=2.5,
                       alpha=alpha, zorder=3)
    ax.add_patch(r)

def arrow(ax, x1, y1, x2, y2, color="#555555", lw=2.2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw), zorder=2)


# ── Raw Input ──
rbox(ax, 0.5, 11.2, 3.5, 1.2, "#607D8B")
ax.text(2.25, 11.8, "Raw Input", ha="center", va="center",
        fontsize=15, fontweight="bold", color="white", zorder=4)
ax.text(2.25, 11.35, "(Image / Doc / Video / Audio)", ha="center", va="center",
        fontsize=12, color="white", alpha=0.9, zorder=4)

# ── Preprocessors ──
rbox(ax, 5.2, 11.6, 3.5, 0.8, "#795548")
ax.text(6.95, 12.0, "Qwen2-VL Caption  (NF4, 1.2 GB)", ha="center", va="center",
        fontsize=12, fontweight="bold", color="white", zorder=4)

rbox(ax, 5.2, 10.6, 3.5, 0.8, "#5D4037")
ax.text(6.95, 11.0, "Whisper STT  (INT8, 1.5 GB)", ha="center", va="center",
        fontsize=12, fontweight="bold", color="white", zorder=4)

arrow(ax, 4.0, 11.8, 5.2, 12.0)
arrow(ax, 4.0, 11.5, 5.2, 11.0)

# ── 3 Axis Encoders ──
AX_W, AX_H = 3.2, 1.8
AX_Y = 7.8

# Re
rbox(ax, 0.3, AX_Y, AX_W, AX_H, AXIS_COLORS["Re"])
ax.text(1.9, AX_Y + 1.3, "Re  Axis", ha="center", va="center",
        fontsize=15, fontweight="bold", color="white", zorder=4)
ax.text(1.9, AX_Y + 0.8, "SigLIP2-SO400M", ha="center", va="center",
        fontsize=13, fontweight="bold", color="white", zorder=4)
ax.text(1.9, AX_Y + 0.35, "1152d  |  FP16", ha="center", va="center",
        fontsize=12, color="#FFFFFFCC", zorder=4)

# Im
rbox(ax, 4.9, AX_Y, AX_W, AX_H, AXIS_COLORS["Im"])
ax.text(6.5, AX_Y + 1.3, "Im  Axis", ha="center", va="center",
        fontsize=15, fontweight="bold", color="white", zorder=4)
ax.text(6.5, AX_Y + 0.8, "BGE-M3", ha="center", va="center",
        fontsize=13, fontweight="bold", color="white", zorder=4)
ax.text(6.5, AX_Y + 0.35, "1024d  |  FP16", ha="center", va="center",
        fontsize=12, color="#FFFFFFCC", zorder=4)

# Z
rbox(ax, 9.5, AX_Y, AX_W, AX_H, AXIS_COLORS["Z"])
ax.text(11.1, AX_Y + 1.3, "Z  Axis", ha="center", va="center",
        fontsize=15, fontweight="bold", color="white", zorder=4)
ax.text(11.1, AX_Y + 0.8, "DINOv2-large", ha="center", va="center",
        fontsize=13, fontweight="bold", color="white", zorder=4)
ax.text(11.1, AX_Y + 0.35, "1024d  |  INT8", ha="center", va="center",
        fontsize=12, color="#FFFFFFCC", zorder=4)

# Arrows: input → encoders
arrow(ax, 2.25, 11.2, 1.9,  AX_Y + AX_H, AXIS_COLORS["Re"])
arrow(ax, 6.95, 10.6, 6.5,  AX_Y + AX_H, AXIS_COLORS["Im"])
arrow(ax, 2.25, 11.2, 11.1, AX_Y + AX_H, AXIS_COLORS["Z"])

# ── Role + weight labels ──
roles = [
    (1.9,  AX_Y - 0.35, "Cross-modal  (Image ↔ Text)",     r"$\alpha=1.0$  (primary)",    AXIS_COLORS["Re"]),
    (6.5,  AX_Y - 0.35, "Multilingual  Semantics (KO/EN)", r"$\alpha=0.4$  (soft bonus)", AXIS_COLORS["Im"]),
    (11.1, AX_Y - 0.35, "Label-free  Visual Structure",     r"$\beta=0.2$  (structural)",  AXIS_COLORS["Z"]),
]
for rx, ry, role, weight, col in roles:
    ax.text(rx, ry,        role,   ha="center", va="top", fontsize=11, color=col, style="italic")
    ax.text(rx, ry - 0.55, weight, ha="center", va="top", fontsize=13, color=col, fontweight="bold")

# ── Hermitian Score Box ──
SCORE_Y = 5.0
rbox(ax, 2.0, SCORE_Y, 9.0, 1.4, "#37474F")
ax.text(6.5, SCORE_Y + 0.7,
        r"Hermitian Score:   $s = \sqrt{A^2 + (0.4\,B)^2 + (0.2\,C)^2}$",
        ha="center", va="center",
        fontsize=16, fontweight="bold", color="white", zorder=4)

arrow(ax, 1.9,  AX_Y - 1.2, 3.5,  SCORE_Y + 1.4, AXIS_COLORS["Re"])
arrow(ax, 6.5,  AX_Y - 1.2, 6.5,  SCORE_Y + 1.4, AXIS_COLORS["Im"])
arrow(ax, 11.1, AX_Y - 1.2, 9.5,  SCORE_Y + 1.4, AXIS_COLORS["Z"])

# ── Domain Coverage Table ──
dom_data = [
    ("Doc",   [True,  True,  True]),
    ("Img",   [True,  True,  True]),
    ("Movie", [True,  True,  False]),
    ("Rec",   [True,  True,  False]),
    ("BGM",   [True,  False, False]),
]
col_labels = ["Re", "Im", "Z"]
col_x = [5.5, 7.2, 8.9]
row_y_start = 3.8

ax.text(0.5, 3.9, "Domain\nCoverage", ha="left", va="top",
        fontsize=14, fontweight="bold", color="#333333")

for j, (label, col) in enumerate(zip(col_labels, [AXIS_COLORS["Re"], AXIS_COLORS["Im"], AXIS_COLORS["Z"]])):
    ax.text(col_x[j], 4.2, label, ha="center", va="center",
            fontsize=14, fontweight="bold", color=col)

for i, (dom, active) in enumerate(dom_data):
    row_y = row_y_start - i * 0.7
    ax.text(3.8, row_y, dom, ha="center", va="center",
            fontsize=14, fontweight="bold", color=DOMAIN_COLORS[dom])
    for j, (is_on, label) in enumerate(zip(active, col_labels)):
        color = AXIS_COLORS[label] if is_on else "#E0E0E0"
        ax.plot(col_x[j], row_y, "o", markersize=16 if is_on else 12,
                color=color, markeredgecolor="white" if is_on else "#BDBDBD",
                markeredgewidth=1.5, zorder=4)

# ── VRAM note ──
ax.text(10.5, 3.0,
        "Sequential VRAM\nOrchestration\n5 models · 12 GB\nRTX 4070",
        ha="center", va="top", fontsize=11, color="#555555", linespacing=1.7,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#F5F5F5",
                  edgecolor="#BDBDBD", alpha=0.9))

# ── Legend ──
handles = [
    mpatches.Patch(facecolor=AXIS_COLORS["Re"], label="Re: SigLIP2 (cross-modal)"),
    mpatches.Patch(facecolor=AXIS_COLORS["Im"], label="Im: BGE-M3 (multilingual)"),
    mpatches.Patch(facecolor=AXIS_COLORS["Z"],  label="Z: DINOv2 (visual structure)"),
]
ax.legend(handles=handles, loc="lower right", fontsize=12,
          framealpha=0.95, edgecolor="#CCCCCC")

save(fig, "fig01_trichef_3axis_architecture.png")
