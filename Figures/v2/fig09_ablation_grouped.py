"""fig09: Ablation 종합 비교 — ASF, Rerank, LangGraph 의 hit@5 / latency.

핵심 발견:
- ASF: 도메인 무관 거의 효과 없음 (Img·Movie·Rec hit@5 동일).
- Rerank: Movie/Rec 에서 hit@5 폭락 (0.97→0.33,  1.0→0.2).
- LangGraph: rewrite_fired=0 → 효과 없음.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

import _common as C
C.setup_style()


def panel_asf(ax):
    domains = ["Doc", "Img", "Movie", "Rec"]
    off = [C.ABLATION["ASF"][d]["off"] for d in domains]
    on  = [C.ABLATION["ASF"][d]["on"]  for d in domains]
    x = np.arange(len(domains))
    w = 0.36

    b1 = ax.bar(x - w/2, off, w, color="#90A4AE",
                label="ASF off", edgecolor="white")
    b2 = ax.bar(x + w/2, on,  w,
                color=[C.DOMAIN_COLORS[d] for d in domains],
                label="ASF on", edgecolor="white", alpha=0.95)

    for bs, vs in [(b1, off), (b2, on)]:
        for b, v in zip(bs, vs):
            ax.text(b.get_x() + b.get_width()/2, v + 0.02, f"{v:.2f}",
                    ha="center", fontsize=9, fontweight="bold", color="#222")

    ax.set_xticks(x); ax.set_xticklabels(domains)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("hit@5", fontsize=10)
    ax.set_title("ASF on/off  —  도메인별 hit@5",
                 fontsize=12, color="#1D3557", pad=8)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.92)
    ax.text(0.98, 0.04,
            "결론: ASF 는 모든 도메인에서 hit@5 변화 없음",
            transform=ax.transAxes, fontsize=8.5,
            color="#666", style="italic", ha="right")


def panel_rerank(ax):
    domains = ["Movie", "Rec"]
    off = [C.ABLATION["Rerank"][d]["off"] for d in domains]
    on  = [C.ABLATION["Rerank"][d]["on"]  for d in domains]
    p95_off = [C.ABLATION["Rerank"][d]["p95_off"] for d in domains]
    p95_on  = [C.ABLATION["Rerank"][d]["p95_on"]  for d in domains]

    x = np.arange(len(domains))
    w = 0.30

    b1 = ax.bar(x - w/2, off, w, color="#66BB6A",
                label="Rerank off", edgecolor="white")
    b2 = ax.bar(x + w/2, on,  w, color="#E53935",
                label="Rerank on",  edgecolor="white")

    for b, v in zip(b1, off):
        ax.text(b.get_x() + b.get_width()/2, v + 0.02, f"{v:.2f}",
                ha="center", fontsize=9, fontweight="bold", color="#1B5E20")
    for b, v in zip(b2, on):
        ax.text(b.get_x() + b.get_width()/2, v + 0.02, f"{v:.2f}",
                ha="center", fontsize=9, fontweight="bold", color="#B71C1C")

    # 폭락 화살표
    for i in range(len(domains)):
        ax.annotate("", xy=(x[i] + w/2, on[i] + 0.03),
                    xytext=(x[i] - w/2, off[i] + 0.03),
                    arrowprops=dict(arrowstyle="-|>", color="#E53935",
                                    lw=2.0))
        drop = (off[i] - on[i]) / off[i] * 100
        ax.text(x[i], (off[i] + on[i]) / 2 + 0.10,
                f"−{drop:.0f}%", ha="center", fontsize=11,
                fontweight="bold", color="#E53935")

    ax.set_xticks(x); ax.set_xticklabels(domains)
    ax.set_ylim(0, 1.20)
    ax.set_ylabel("hit@5", fontsize=10)
    ax.set_title("Rerank on/off  —  성능 폭락 사례",
                 fontsize=12, color="#1D3557", pad=8)
    ax.legend(loc="upper right", fontsize=9)

    # latency 비교 보조 (oright axis)
    ax2 = ax.twinx()
    ax2.plot(x - w/2, p95_off, "o-", color="#1565C0", markersize=8,
             linewidth=2, label="p95 (off)")
    ax2.plot(x + w/2, p95_on, "s-", color="#FF6F00", markersize=8,
             linewidth=2, label="p95 (on)")
    for i in range(len(domains)):
        ax2.text(x[i] + w/2 + 0.05, p95_on[i] + 5, f"{p95_on[i]:.0f}ms",
                 fontsize=8, color="#FF6F00", fontweight="bold")
        ax2.text(x[i] - w/2 - 0.20, p95_off[i] + 5, f"{p95_off[i]:.0f}ms",
                 fontsize=8, color="#1565C0", fontweight="bold")
    ax2.set_ylabel("p95 latency (ms)", fontsize=10, color="#444")
    ax2.set_ylim(0, max(p95_on) * 1.20)
    ax2.legend(loc="lower right", fontsize=8.5)
    ax2.grid(False)


def panel_langgraph(ax):
    domains = ["Movie", "Rec"]
    off = [C.ABLATION["LangGraph"][d]["off"] for d in domains]
    on  = [C.ABLATION["LangGraph"][d]["on"]  for d in domains]
    p95_off = [C.ABLATION["LangGraph"][d]["p95_off"] for d in domains]
    p95_on  = [C.ABLATION["LangGraph"][d]["p95_on"]  for d in domains]

    x = np.arange(len(domains))
    w = 0.30

    b1 = ax.bar(x - w/2, off, w, color="#90A4AE",
                label="LangGraph off", edgecolor="white")
    b2 = ax.bar(x + w/2, on,  w, color="#5E8FBF",
                label="LangGraph on",  edgecolor="white")

    for bs, vs in [(b1, off), (b2, on)]:
        for b, v in zip(bs, vs):
            ax.text(b.get_x() + b.get_width()/2, v + 0.02, f"{v:.2f}",
                    ha="center", fontsize=9, fontweight="bold", color="#222")

    # rewrite_fired = 0 표시
    for i in range(len(domains)):
        ax.text(x[i], 1.10,
                "rewrite_fired = 0",
                ha="center", fontsize=8.5, color="#666",
                style="italic")

    ax.set_xticks(x); ax.set_xticklabels(domains)
    ax.set_ylim(0, 1.20)
    ax.set_ylabel("hit@5", fontsize=10)
    ax.set_title("LangGraph rewrite on/off",
                 fontsize=12, color="#1D3557", pad=8)
    ax.legend(loc="upper right", fontsize=9)


def panel_summary(ax):
    """우측 결론 박스."""
    ax.axis("off")
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)

    # 헤더
    head = FancyBboxPatch((0.2, 8.6), 9.6, 1.2,
                          boxstyle="round,pad=0.08",
                          facecolor="#1D3557", edgecolor="none")
    ax.add_patch(head)
    ax.text(5.0, 9.2, "Ablation 결론", ha="center", va="center",
            fontsize=15, fontweight="bold", color="white")

    findings = [
        (r"$\checkmark$", "ASF 는 hit@5 영향 없음 — 한글 bigram 매칭이 dense 점수와 중복",
         "#43A047", "유지 (γ=0.25, 의도된 안전망)"),
        (r"$\times$",     "Rerank (BGE-Reranker post) — Movie/Rec 에서 −66%, −80% 폭락",
         "#E53935", "비활성 (off 가 default)"),
        (r"$\approx$",    "LangGraph rewrite — z<1 트리거 0회, 효과 측정 불가",
         "#FBC02D", "조건 완화 또는 제거"),
        (r"$\checkmark$", r"Calibration $\mu_{null} + 1.645\sigma$ — FAR=0.05 안정",
         "#43A047", "운영 default"),
        (r"$\checkmark$", r"Gram-Schmidt 직교화 — 채널 중복 제거, $Im_\perp$/$Z_\perp$ 독립",
         "#43A047", "운영 default"),
    ]
    for i, (m, txt, col, action) in enumerate(findings):
        y = 7.7 - i * 1.45
        # marker
        circ = plt.Circle((0.55, y), 0.32, facecolor=col,
                          edgecolor="white", linewidth=2, zorder=3)
        ax.add_patch(circ)
        ax.text(0.55, y, m, ha="center", va="center", fontsize=14,
                fontweight="bold", color="white", zorder=4)
        ax.text(1.20, y + 0.20, txt, ha="left", va="center",
                fontsize=10.2, color="#222")
        ax.text(1.20, y - 0.38, action, ha="left", va="center",
                fontsize=9, color=col, fontweight="bold", style="italic")


def main():
    fig = plt.figure(figsize=(20, 10))
    gs = fig.add_gridspec(2, 3, width_ratios=[1.0, 1.0, 1.05],
                          height_ratios=[1.0, 1.0],
                          hspace=0.40, wspace=0.30)

    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, 0])
    ax4 = fig.add_subplot(gs[:, 2])

    panel_asf(ax1)
    panel_rerank(ax2)
    panel_langgraph(ax3)
    panel_summary(ax4)

    fig.suptitle(
        "Ablation 종합  —  ASF · Rerank · LangGraph  실측 비교",
        fontsize=18, fontweight="bold", color="#1D3557", y=0.99)
    fig.text(0.5, -0.005,
             "데이터 출처:  publication/paper/_asf_ablation_results.json,  "
             "_rerank_ablation_results.json,  _langgraph_ablation_results.json",
             ha="center", fontsize=9.5, color="#666")

    plt.subplots_adjust(top=0.93, bottom=0.06, left=0.05, right=0.98)
    C.save(fig, "fig09_ablation_grouped.png")


if __name__ == "__main__":
    main()
