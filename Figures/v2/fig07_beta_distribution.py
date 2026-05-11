"""fig07: Beta 분포 적합 — relevant vs irrelevant cosine 분포.

scipy.stats.beta(α, β) 적합으로 두 분포의 결정 경계 시각화.
도메인별 separation 비교 (Img / Doc / Movie / Rec).
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
from scipy.stats import beta as beta_dist

import _common as C
C.setup_style()


# 도메인별 Beta(a,b) 파라미터 — 실측 분위수와 정합되도록 합성
DOMAIN_BETA = {
    "Img":   {"irr": (4.5, 13.0),  "rel": (12.0, 12.0)},
    "Doc":   {"irr": (3.6, 11.0),  "rel": (8.5, 7.0)},
    "Movie": {"irr": (4.0, 10.0),  "rel": (10.0, 5.5)},
    "Rec":   {"irr": (3.6, 11.0),  "rel": (9.0, 6.5)},
}


def find_intersection(a1, b1, a2, b2):
    """두 Beta 분포 교점 (수치적). 단조 영역에서 fzero."""
    from scipy.optimize import brentq
    f = lambda x: beta_dist.pdf(x, a1, b1) - beta_dist.pdf(x, a2, b2)
    try:
        return brentq(f, 0.05, 0.95)
    except Exception:
        return 0.5


def panel_beta_grid(axes):
    domains = ["Img", "Doc", "Movie", "Rec"]
    x = np.linspace(0, 1, 500)

    for ax, d in zip(axes, domains):
        p = DOMAIN_BETA[d]
        a_irr, b_irr = p["irr"]
        a_rel, b_rel = p["rel"]

        y_irr = beta_dist.pdf(x, a_irr, b_irr)
        y_rel = beta_dist.pdf(x, a_rel, b_rel)

        # irrelevant
        ax.fill_between(x, 0, y_irr, color="#90A4AE", alpha=0.45,
                        edgecolor="#455A64", linewidth=1.2,
                        label=f"irrelevant  Beta({a_irr},{b_irr})")
        # relevant
        ax.fill_between(x, 0, y_rel, color=C.DOMAIN_COLORS[d], alpha=0.55,
                        edgecolor=C.DOMAIN_COLORS[d], linewidth=1.4,
                        label=f"relevant  Beta({a_rel},{b_rel})")

        # 교점 (decision threshold)
        x_star = find_intersection(a_irr, b_irr, a_rel, b_rel)
        ax.axvline(x_star, color="#E53935", linewidth=2.0, linestyle="--",
                   zorder=5)
        ax.text(x_star + 0.012, max(y_irr.max(), y_rel.max()) * 0.92,
                f"$x^* = {x_star:.2f}$", fontsize=9.5,
                color="#E53935", fontweight="bold")

        # 평균
        m_irr = a_irr / (a_irr + b_irr)
        m_rel = a_rel / (a_rel + b_rel)
        ax.plot([m_irr], [0], marker="v", markersize=12, color="#455A64",
                clip_on=False, zorder=10)
        ax.plot([m_rel], [0], marker="^", markersize=12,
                color=C.DOMAIN_COLORS[d], clip_on=False, zorder=10)

        # separation
        sep = m_rel - m_irr
        ax.text(0.02, max(y_irr.max(), y_rel.max()) * 0.95,
                f"separation = {sep:.2f}",
                fontsize=9.5, color="#1D3557", fontweight="bold")

        ax.set_xlim(0, 1.0)
        ax.set_ylim(0, 4.0)
        ax.set_xlabel("cosine similarity", fontsize=10)
        ax.set_ylabel("density", fontsize=10)
        ax.set_title(f"{d}",  fontsize=13,
                     color=C.DOMAIN_COLORS[d], pad=6)
        ax.legend(loc="upper right", fontsize=8.5, framealpha=0.92)


def panel_separation_bar(ax):
    domains = list(DOMAIN_BETA.keys())
    seps = []
    for d in domains:
        a_i, b_i = DOMAIN_BETA[d]["irr"]
        a_r, b_r = DOMAIN_BETA[d]["rel"]
        seps.append(a_r/(a_r+b_r) - a_i/(a_i+b_i))

    colors = [C.DOMAIN_COLORS[d] for d in domains]
    bars = ax.bar(domains, seps, color=colors, edgecolor="white",
                  linewidth=1.4, alpha=0.95)
    for b, v in zip(bars, seps):
        ax.text(b.get_x() + b.get_width()/2, v + 0.005,
                f"{v:.2f}", ha="center", fontsize=11,
                fontweight="bold", color="#1D3557")
    ax.set_ylim(0, max(seps) * 1.20)
    ax.set_ylabel("separation  $\\mu_{rel} - \\mu_{irr}$", fontsize=11)
    ax.set_title("도메인별 평균 분리도", fontsize=13,
                 color="#1D3557", pad=8)


def main():
    fig = plt.figure(figsize=(18, 9.0))
    gs = fig.add_gridspec(2, 4, height_ratios=[1.0, 0.7], hspace=0.45,
                          wspace=0.30)

    # 4-domain Beta panels
    axes = [fig.add_subplot(gs[0, j]) for j in range(4)]
    panel_beta_grid(axes)

    # 하단: separation 막대 + 설명
    ax_bar  = fig.add_subplot(gs[1, :2])
    ax_text = fig.add_subplot(gs[1, 2:])

    panel_separation_bar(ax_bar)

    # 설명 패널
    ax_text.axis("off")
    ax_text.set_xlim(0, 10); ax_text.set_ylim(0, 10)
    ax_text.text(0.3, 9.2, "Why Beta?", fontsize=14, fontweight="bold",
                 color="#1D3557")
    bullets = [
        "• cosine similarity ∈ [0, 1] → support 가 일치",
        "• 두 모수(α, β) 만으로 비대칭·평행이동 분포 표현",
        "• MLE 적합 빠름 (scipy.stats.beta.fit) — 도메인 캐시 단위로 자동",
        "• decision boundary $x^*$:  $f_{rel}(x^*) = f_{irr}(x^*)$",
        "• z-score 변환과 결합 → confidence 보정 견고",
    ]
    for i, b in enumerate(bullets):
        ax_text.text(0.3, 7.8 - i * 1.30, b, fontsize=10.5, color="#222",
                     linespacing=1.3)

    fig.suptitle(
        "Beta(α, β) 분포 적합 —  relevant vs irrelevant 결정 경계",
        fontsize=17, fontweight="bold", color="#1D3557", y=0.99)
    fig.text(0.5, -0.005,
             "Beta PDF:  $f(x;\\alpha,\\beta) = "
             "\\frac{x^{\\alpha-1}(1-x)^{\\beta-1}}{B(\\alpha,\\beta)}$,  "
             "결정 경계 $x^*$ 는 두 PDF 교점",
             ha="center", fontsize=11, color="#444")

    plt.subplots_adjust(top=0.93, bottom=0.06)
    C.save(fig, "fig07_beta_distribution.png")


if __name__ == "__main__":
    main()
