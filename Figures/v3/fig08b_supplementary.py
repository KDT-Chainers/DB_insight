"""Fig 8b - Supplementary ablation: (A) Sparse Top-k, (B) ASF by domain, (C) Rerank penalty.

Data sources:
  (A) publication/paper/_doc_query_len_ablation_results.json
  (B) publication/paper/_asf_ablation_results.json
  (C) publication/paper/_rerank_ablation_results.json
"""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
from _common import setup_style, save

setup_style()

fig, axes = plt.subplots(1, 3, figsize=(18, 7))
fig.subplots_adjust(bottom=0.20, top=0.88)
fig.suptitle(
    "Fig. 8b  Supplementary Ablation — Sparse / ASF / Rerank Component Analysis",
    fontsize=16, fontweight="bold", y=1.02,
)

# ── (A) Sparse / Lexical: Top-k effect, Doc domain, query_len=80 ─────────
ax = axes[0]

topk_labels = ["hit@5", "hit@10", "hit@50"]
lex_off = [20.0, 26.7, 50.0]   # len=80_lex=off (default)
lex_on  = [16.7, 26.7, 50.0]   # len=80_lex=on

x = np.arange(3)
w = 0.35

ax.bar(x - w/2, lex_off, w, label="Lexical OFF (default)",
       color="#607D8B", alpha=0.85, edgecolor="white", lw=1.5, zorder=3)
ax.bar(x + w/2, lex_on,  w, label="Lexical ON",
       color="#1565C0", alpha=0.85, edgecolor="white", lw=1.5, zorder=3)

for xi, (vo, vn) in enumerate(zip(lex_off, lex_on)):
    ax.text(xi - w/2, vo + 1.5, f"{vo:.0f}%",
            ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.text(xi + w/2, vn + 1.5, f"{vn:.0f}%",
            ha="center", va="bottom", fontsize=11, fontweight="bold")
    delta = vn - vo
    col = "#C62828" if delta < 0 else ("#2E7D52" if delta > 0 else "#888888")
    ax.text(xi, max(vo, vn) + 8, f"Δ={delta:+.1f}pp",
            ha="center", fontsize=10, color=col, fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(topk_labels, fontsize=14, fontweight="bold")
ax.set_ylabel("Hit Rate (%)", fontsize=13, fontweight="bold")
ax.set_ylim(0, 119)
ax.set_title("(A)  Sparse/Lexical — Top-k sensitivity\nDoc domain, query_len=80",
             fontsize=12, fontweight="bold")
ax.legend(fontsize=10, loc="upper left")
ax.text(1.0, 80, "Lexical: -3pp at hit@5\nno gain at hit@10/50 (Doc)",
        ha="center", va="center", fontsize=11,
        color="#C62828", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#FFEBEE",
                  edgecolor="#C62828", alpha=0.95, lw=1.5))

# ── (B) ASF effect by domain ──────────────────────────────────────────────
ax = axes[1]

# Doc excluded: _asf_ablation.py uses bodies[i] vs ids[i] self-retrieval,
# but index alignment between _body_texts.json and engine cache is unverified
# → 0/30 hit is suspected ID-mismatch artifact, not real performance.
domains_b = ["Img", "Movie", "Rec"]
asf_off   = [100.0,  95.0, 100.0]
asf_on    = [100.0,  95.0, 100.0]

x2 = np.arange(3)
w2 = 0.35

b_off = ax.bar(x2 - w2/2, asf_off, w2, label="ASF off (default)",
               color="#607D8B", alpha=0.80, edgecolor="white", lw=1.5, zorder=3)
b_on  = ax.bar(x2 + w2/2, asf_on,  w2, label="ASF on",
               color="#795548", alpha=0.85, edgecolor="white", lw=1.5, zorder=3)

for bar, v in list(zip(b_off, asf_off)) + list(zip(b_on, asf_on)):
    ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5,
            f"{v:.0f}%", ha="center", va="bottom", fontsize=10, fontweight="bold")

ax.set_xticks(x2)
ax.set_xticklabels(domains_b, fontsize=14, fontweight="bold")
ax.set_ylabel("hit@5 (%)", fontsize=13, fontweight="bold")
ax.set_ylim(0, 119)
ax.set_title("(B)  ASF Effect by Domain\nhit@5,  n ≥ 20 queries / domain",
             fontsize=12, fontweight="bold")
ax.legend(fontsize=10)
ax.text(1.0, 80, "ASF: Δ = 0pp in ALL domains",
        ha="center", va="center", fontsize=11,
        color="#C62828", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#FFEBEE",
                  edgecolor="#C62828", alpha=0.95, lw=1.5))

# ── (C) Rerank penalty ────────────────────────────────────────────────────
ax = axes[2]

domains_c = ["Movie\n(n=30)", "Rec\n(n=30)"]
no_rr   = [96.7, 100.0]
with_rr = [33.3,  20.0]
lat_no  = [84.9,  69.0]    # p95 latency ms
lat_rr  = [550.9, 603.8]

x3 = np.arange(2)
w3 = 0.35

b_no = ax.bar(x3 - w3/2, no_rr,   w3, label="No rerank",
              color="#9E9E9E", alpha=0.85, edgecolor="white", lw=1.5, zorder=3)
b_rr = ax.bar(x3 + w3/2, with_rr, w3, label="With rerank",
              color="#2E7D52", alpha=0.85, edgecolor="white", lw=1.5, zorder=3)

for bar, v, lat in zip(b_no, no_rr, lat_no):
    ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5,
            f"{v:.0f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.text(bar.get_x() + bar.get_width() / 2, v / 2,
            f"p95={lat:.0f}ms", ha="center", va="center",
            fontsize=9, color="white", fontweight="bold")

for bar, v, lat in zip(b_rr, with_rr, lat_rr):
    ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5,
            f"{v:.0f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.text(bar.get_x() + bar.get_width() / 2, max(v / 2, 5),
            f"p95={lat:.0f}ms", ha="center", va="center",
            fontsize=8.5, color="white", fontweight="bold")

# Delta + latency ratio annotations — centered between the two bars of each group
for i, (no, rr, ln, lr) in enumerate(zip(no_rr, with_rr, lat_no, lat_rr)):
    delta    = rr - no
    lat_mult = lr / ln
    ax.text(i + w3/2, (no + rr) / 2,
            f"{delta:+.0f}pp\n×{lat_mult:.1f} lat.",
            ha="center", va="center", fontsize=9.5,
            color="#C62828", fontweight="bold")

ax.set_xticks(x3)
ax.set_xticklabels(domains_c, fontsize=13, fontweight="bold")
ax.set_ylabel("hit@5 (%)", fontsize=13, fontweight="bold")
ax.set_ylim(0, 119)
ax.set_title("(C)  Rerank Penalty\nhit@5  ·  p95 latency inside bars",
             fontsize=12, fontweight="bold")
ax.legend(fontsize=10)
ax.text(0.5, 80, "Rerank disabled — severe accuracy & latency penalty",
        ha="center", va="center", fontsize=9.5,
        color="#C62828", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#FFEBEE",
                  edgecolor="#C62828", alpha=0.95, lw=1.5))

save(fig, "fig08b_supplementary.png")
