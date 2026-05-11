"""fig10: 위상 분리도 polar (2D + 3D 변종).

Match θ vs Null θ 분포 — q05/q50/q95 동심원.
도메인별 separation 시각화 + 3D 회전 표면.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from mpl_toolkits.mplot3d import Axes3D  # noqa
import numpy as np

import _common as C
C.setup_style()


def panel_polar(ax, domain):
    """단일 도메인 polar — match q05/50/95, null q05/50/95."""
    p = C.PHASE_RIDGE[domain]

    # 360° 전체로 펼침 (대칭) — semicircle 풀
    theta = np.linspace(0, 2*np.pi, 360)

    # match radial profile (작을수록 좋음)
    match_q05 = 0.06; match_q50 = p["match_q50"]; match_q95 = p["match_q90"] * 1.35
    null_q05  = 0.20; null_q50  = p["null_q50"];  null_q95  = p["null_q50"] * 2.5

    # match 영역 (안쪽 disk)
    ax.fill_between(theta, 0, np.full_like(theta, match_q95),
                    color=C.DOMAIN_COLORS[domain], alpha=0.30,
                    edgecolor="none")
    ax.fill_between(theta, 0, np.full_like(theta, match_q50),
                    color=C.DOMAIN_COLORS[domain], alpha=0.55,
                    edgecolor="none")
    ax.fill_between(theta, 0, np.full_like(theta, match_q05),
                    color=C.DOMAIN_COLORS[domain], alpha=0.85,
                    edgecolor="none")

    # null 영역 (바깥 ring)
    ax.fill_between(theta, null_q50, null_q95,
                    color="#888", alpha=0.20)
    ax.fill_between(theta, null_q05, null_q50,
                    color="#888", alpha=0.30)

    # quantile labels
    ax.plot(theta, np.full_like(theta, match_q50),
            color=C.DOMAIN_COLORS[domain], linewidth=1.4, alpha=0.9)
    ax.plot(theta, np.full_like(theta, null_q50),
            color="#444", linewidth=1.4, linestyle="--", alpha=0.85)

    ax.set_rmax(null_q95 * 1.05)
    ax.set_rticks(np.round(np.linspace(0, null_q95, 4), 1))
    ax.tick_params(labelsize=7, colors="#666")
    ax.set_thetagrids(np.arange(0, 360, 60), fontsize=7)
    ax.set_title(f"{domain}\n"
                 f"sep = {p['sep']:.1f}°",
                 fontsize=10, color=C.DOMAIN_COLORS[domain],
                 fontweight="bold", pad=6)


def panel_separation_3d(ax):
    """도메인별 match q50 vs null q50 vs separation 3D."""
    domains = list(C.PHASE_RIDGE.keys())
    match  = [C.PHASE_RIDGE[d]["match_q50"] for d in domains]
    null   = [C.PHASE_RIDGE[d]["null_q50"]  for d in domains]
    sep    = [C.PHASE_RIDGE[d]["sep"]       for d in domains]

    x = np.arange(len(domains))
    width = 0.35

    # 막대를 3D 직육면체로
    for i, d in enumerate(domains):
        c = C.DOMAIN_COLORS[d]
        # match
        ax.bar3d(x[i] - width, 0, 0, width*0.9, 0.5, match[i],
                 color=c, alpha=0.95, edgecolor="white", linewidth=0.6)
        # null
        ax.bar3d(x[i],         0, 0, width*0.9, 0.5, null[i],
                 color=c, alpha=0.45, edgecolor=c, linewidth=1.2)
        # separation arrow
        ax.plot([x[i] + width/2, x[i] + width/2],
                [0.25, 0.25],
                [match[i], null[i]],
                color="#222", linewidth=1.6)
        ax.text(x[i] + width/2, 0.25, (match[i]+null[i])/2 + 0.3,
                f"Δ={sep[i]:.1f}°",
                fontsize=8, color="#222", fontweight="bold",
                ha="center")

    ax.set_xticks(x)
    ax.set_xticklabels(domains, fontsize=10)
    ax.set_yticks([])
    ax.set_zlabel("위상 θ (deg)", fontsize=10)
    ax.set_title("도메인별 match (실) vs null (반투명) — q50",
                 fontsize=12, color="#1D3557", pad=6)
    ax.view_init(elev=22, azim=-42)


def panel_legend(ax):
    """좌측 범례 + 설명."""
    ax.axis("off")
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)

    ax.text(0.3, 9.5, "Phase Ridge Polar",
            fontsize=14, fontweight="bold", color="#1D3557")
    ax.text(0.3, 9.0,
            "각 도메인 polar 차트는 match/null 위상 분포를 동심원 형태로 표시.",
            fontsize=9.5, color="#444", linespacing=1.3)

    # ring 범례
    items = [
        ("match  q05  (≤ 0.06°)", C.DOMAIN_COLORS["Movie"], 0.85),
        ("match  q50  (median)",  C.DOMAIN_COLORS["Movie"], 0.55),
        ("match  q90/95",         C.DOMAIN_COLORS["Movie"], 0.30),
        ("null   q50  (median)",  "#888", 0.30),
        ("null   q95  (outer)",   "#888", 0.20),
    ]
    for i, (lbl, col, a) in enumerate(items):
        y = 7.6 - i * 0.85
        ax.add_patch(plt.Rectangle((0.3, y - 0.20), 0.7, 0.40,
                                   facecolor=col, alpha=a, edgecolor="none"))
        ax.text(1.20, y, lbl, ha="left", va="center",
                fontsize=9.5, color="#222")

    # 데이터 출처
    ax.text(0.3, 2.3, "데이터 출처:", fontsize=9.5, fontweight="bold",
            color="#1D3557")
    ax.text(0.3, 1.7, "publication/paper/_phase_ridge_results.json",
            fontsize=8.8, color="#555", style="italic")
    ax.text(0.3, 1.1,
            "ridge regression 으로 match/null 분포의 q05/q10/.../q95 측정",
            fontsize=8.8, color="#555", linespacing=1.3)


def main():
    fig = plt.figure(figsize=(20, 9))
    gs = fig.add_gridspec(2, 5, width_ratios=[1.0, 1.0, 1.0, 1.0, 1.4],
                          height_ratios=[1.0, 1.0],
                          hspace=0.45, wspace=0.40)

    # 4개 도메인 polar
    domains = ["Img", "Doc", "Movie", "Rec"]
    for i, d in enumerate(domains):
        ax = fig.add_subplot(gs[0, i], projection="polar")
        panel_polar(ax, d)

    # 하단 좌측: 3D 막대
    ax_3d = fig.add_subplot(gs[1, :3], projection="3d")
    panel_separation_3d(ax_3d)

    # 우측: 범례
    ax_lg = fig.add_subplot(gs[:, 4])
    panel_legend(ax_lg)

    fig.suptitle(
        "Phase Ridge Polar  —  Match vs Null  위상 분리도",
        fontsize=17, fontweight="bold", color="#1D3557", y=0.99)
    fig.text(0.5, -0.005,
             "분리도 separation = $\\theta_{null,q50} - \\theta_{match,q50}$.  "
             "값이 클수록 match/null 구분이 뚜렷",
             ha="center", fontsize=10.5, color="#444")

    plt.subplots_adjust(top=0.93, bottom=0.06, left=0.04, right=0.98)
    C.save(fig, "fig10_phase_polar_3d.png")


if __name__ == "__main__":
    main()
