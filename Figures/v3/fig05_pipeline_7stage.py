"""Fig 5 - 7-Stage Search Pipeline Flow Diagram (PPT square, v3.1)."""
from __future__ import annotations
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from _common import setup_style, save, STAGE_COLORS

setup_style()
fig, ax = plt.subplots(figsize=(13, 17))
ax.set_xlim(0, 13)
ax.set_ylim(0, 17)
ax.axis("off")
fig.suptitle("Fig. 5  DB_insight  7-Stage Search Pipeline",
             fontsize=20, fontweight="bold", y=0.99)


def stage_box(ax, x, y, w, h, title, detail, color,
              title_fs=14, detail_fs=11):
    r = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.22",
                       facecolor=color, edgecolor="white", lw=2.5,
                       alpha=0.93, zorder=3)
    ax.add_patch(r)
    ax.text(x + w/2, y + h*0.70, title,
            ha="center", va="center",
            fontsize=title_fs, fontweight="bold", color="white", zorder=4)
    if detail:
        ax.text(x + w/2, y + h*0.28, detail,
                ha="center", va="center",
                fontsize=detail_fs, color="#FFFFFFDD",
                linespacing=1.55, zorder=4)


def arrow_down(ax, x, y1, y2, lw=2.5):
    ax.annotate("", xy=(x, y2), xytext=(x, y1),
                arrowprops=dict(arrowstyle="-|>", color="#444444", lw=lw),
                zorder=2)


XC, W = 6.5, 11.0   # center x, box width
X0 = XC - W/2

# ── User Query ──
ax.text(XC, 16.55, "User Query", fontsize=17, fontweight="bold",
        ha="center", va="center",
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#ECEFF1",
                  edgecolor="#90A4AE", lw=2.5))
arrow_down(ax, XC, 16.15, 15.60)

# ── Stage 1 ──
stage_box(ax, X0, 14.30, W, 1.30,
          "Stage 1    Preprocess & Query Expansion",
          'Noise removal ("찾아줘", "알려줘" …)  +  KO↔EN bilingual expand (×3 variants)',
          STAGE_COLORS["preprocess"], title_fs=15, detail_fs=11)
arrow_down(ax, XC, 14.30, 13.70)

# ── Stage 2 outer ──
stage_box(ax, X0 - 0.2, 11.70, W + 0.4, 2.00,
          "Stage 2    5-Domain Parallel Search  (ThreadPoolExecutor, 5 workers)",
          "", "#37474F", title_fs=15)

# Sub-boxes
sub_data = [
    ("Dense\n(Hermitian)", r"$\sqrt{A^2+(0.4B)^2+(0.2C)^2}$", STAGE_COLORS["dense"]),
    ("Sparse\n(BGE-M3)",   "BM25-style\nexact token",           STAGE_COLORS["sparse"]),
    ("ASF\n(IDF overlap)", r"$\Sigma$ IDF(t) / |Q|",            STAGE_COLORS["asf"]),
]
sub_w, sub_h, sub_y = 3.0, 1.10, 11.85
for i, (title, detail, col) in enumerate(sub_data):
    bx = X0 + 0.3 + i * 3.65
    r = FancyBboxPatch((bx, sub_y), sub_w, sub_h,
                       boxstyle="round,pad=0.15",
                       facecolor=col, edgecolor="white", lw=1.8,
                       alpha=0.90, zorder=4)
    ax.add_patch(r)
    ax.text(bx + sub_w/2, sub_y + sub_h*0.68, title,
            ha="center", va="center",
            fontsize=13, fontweight="bold", color="white", zorder=5)
    ax.text(bx + sub_w/2, sub_y + sub_h*0.25, detail,
            ha="center", va="center",
            fontsize=10, color="#FFFFFFCC", zorder=5)

arrow_down(ax, XC, 11.70, 11.10)

# ── Stage 2b ──
stage_box(ax, X0, 9.55, W, 1.55,
          "Stage 2b   Fusion + Threshold + Confidence",
          "Weighted min-max fusion  (Dense 0.60 / Sparse 0.25 / ASF 0.15)\n"
          r"$\tau$ gate: s < $\tau$ → blocked   |   conf = $\Phi\!\left(\frac{s-\mu_q}{\sigma_q}\right)$",
          STAGE_COLORS["tau"], title_fs=15, detail_fs=11)
arrow_down(ax, XC, 9.55, 8.95)

# ── Stage 3 ──
stage_box(ax, X0, 7.60, W, 1.35,
          "Stage 3   MPLC Re-scoring",
          r"sigmoid(bias + $\Sigma w_i f_i$)   ·   7 features: dense, sparse, asf, rerank, keyword, filename, z_dense",
          STAGE_COLORS["mplc"], title_fs=15, detail_fs=11)
arrow_down(ax, XC, 7.60, 7.00)

# ── Stage 4 ──
stage_box(ax, X0, 5.75, W, 1.25,
          "Stage 4   Query Intent Boost",
          'Domain keyword match  →  boost ×1.0 ~ ×2.0   (e.g. "카페 배경음악" → BGM ×1.9)',
          STAGE_COLORS["boost"], title_fs=15, detail_fs=11)
arrow_down(ax, XC, 5.75, 5.15)

# ── Stage 5 ──
stage_box(ax, X0, 3.90, W, 1.25,
          "Stage 5   Adaptive Quota Allocation",
          "conf≥0.80 → 20 slots  |  conf≥0.50 → 10  |  conf≥0.30 → 5  |  conf<0.30 → 1 slot",
          STAGE_COLORS["quota"], title_fs=15, detail_fs=11)
arrow_down(ax, XC, 3.90, 3.30)

# ── Stage 6 ──
stage_box(ax, X0, 2.05, W, 1.25,
          "Stage 6   Cross-Encoder Reranker",
          "Sort signal only (not confidence)  |  BGM/Image/AV: exempt  |  Doc floor: −5.0",
          STAGE_COLORS["rerank"], title_fs=15, detail_fs=11)
arrow_down(ax, XC, 2.05, 1.45)

# ── Stage 7 ──
stage_box(ax, X0, 0.20, W, 1.25,
          "Stage 7   Multi-Signal Floor Filter + Final Sort",
          "3-way floor: min_conf + min_sim + min_raw_dense  →  sort(dense, rerank, conf)",
          STAGE_COLORS["floor"], title_fs=15, detail_fs=11)

# ── Top-K Results ──
ax.text(XC, -0.35, "Top-K  Results", fontsize=17, fontweight="bold",
        ha="center", va="center",
        bbox=dict(boxstyle="round,pad=0.45", facecolor="#E8F5E9",
                  edgecolor="#4CAF50", lw=2.5))

save(fig, "fig05_pipeline_7stage.png")
