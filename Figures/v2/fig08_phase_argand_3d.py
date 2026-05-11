"""fig08: Argand 위상 필터  —  2D 게이팅 + 3D 신뢰도 표면.

z = ρ·e^{iθ}  여기서 ρ=|cosθ_RE-Im|, θ=arctan2(Im_perp·q, Re·q).
신뢰영역  |θ|<30°  / 의심  30~80°  / 거부  ≥80°
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.patches import Wedge, Circle, FancyArrowPatch
from mpl_toolkits.mplot3d import Axes3D  # noqa
import numpy as np

import _common as C
C.setup_style()


TRUST_DEG = 30
SUSPECT_DEG = 80


def panel_argand_2d(ax):
    ax.set_xlim(-1.5, 1.5); ax.set_ylim(-1.5, 1.5)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)

    # 전체 원 (외곽)
    circ = Circle((0, 0), 1.4, color="#FFCDD2", alpha=0.55, zorder=1)
    ax.add_patch(circ)

    # 신뢰 sector (양쪽 ±30°)
    for sgn in (+1, -1):
        w = Wedge(center=(0, 0), r=1.4,
                  theta1=-TRUST_DEG, theta2=TRUST_DEG,
                  color="#A5D6A7", alpha=0.85, zorder=2)
        ax.add_patch(w)
        break

    # 의심 sector  ±(30 ~ 80)
    for ang in [(TRUST_DEG, SUSPECT_DEG), (-SUSPECT_DEG, -TRUST_DEG)]:
        w = Wedge(center=(0, 0), r=1.4, theta1=ang[0], theta2=ang[1],
                  color="#FFE082", alpha=0.85, zorder=2)
        ax.add_patch(w)

    # 단위원
    unit = Circle((0, 0), 1.0, fill=False, edgecolor="#666",
                  linewidth=0.8, linestyle="--", zorder=3)
    ax.add_patch(unit)

    # 좌표축
    ax.axhline(0, color="#444", linewidth=0.8, zorder=3)
    ax.axvline(0, color="#444", linewidth=0.8, zorder=3)

    # 예시 벡터
    rho = 1.05; theta = np.deg2rad(15)
    x = rho * np.cos(theta); y = rho * np.sin(theta)
    ax.add_patch(FancyArrowPatch((0, 0), (x, y),
                                  arrowstyle="-|>", mutation_scale=18,
                                  color="#1565C0", linewidth=2.0, zorder=10))
    ax.text(x + 0.04, y + 0.04, r"$z=\rho\,e^{i\theta}$",
            fontsize=11, color="#1565C0", fontweight="bold")

    # θ 호 + ρ 라벨
    arc_t = np.linspace(0, theta, 30)
    ax.plot(0.32 * np.cos(arc_t), 0.32 * np.sin(arc_t),
            color="#1565C0", linewidth=1.5)
    ax.text(0.40, 0.10, r"$\theta$", fontsize=12, color="#1565C0")
    ax.text(0.55, 0.55, r"$\rho$", fontsize=12, color="#1565C0",
            fontweight="bold")

    # sector 라벨
    ax.text(1.05, 0.0, "신뢰\n|θ|<30°", ha="left", va="center",
            fontsize=10, color="#1B5E20", fontweight="bold",
            linespacing=1.1)
    ax.text(0.55, 0.95, "의심\n30~80°", ha="left", va="center",
            fontsize=10, color="#E65100", fontweight="bold",
            linespacing=1.1)
    ax.text(-1.10, 0.55, "거부\n|θ|≥80°", ha="right", va="center",
            fontsize=10, color="#B71C1C", fontweight="bold",
            linespacing=1.1)

    ax.set_xlabel("Re  (실수부)", fontsize=11)
    ax.set_ylabel("Im  (허수부)", fontsize=11)
    ax.set_title("Argand 평면  —  위상 게이팅",
                 fontsize=13, color="#1D3557", pad=8)


def panel_confidence_3d(ax):
    """3D 표면: confidence(ρ, θ) = ρ · cos(θ)·sigmoid(...)"""
    rho = np.linspace(0.0, 1.0, 80)
    theta = np.linspace(-np.pi/2, np.pi/2, 80)
    R, T = np.meshgrid(rho, theta)

    # confidence = ρ * (1 - |θ|/(π/2))^2  → 직관적 게이팅
    conf = R * np.clip(1 - (np.abs(T) / (np.pi/2))**1.6, 0, 1)
    # 30°/80° 영역에 컬러 단계 부여
    X = R * np.cos(T)
    Y = R * np.sin(T)

    surf = ax.plot_surface(X, Y, conf, cmap="RdYlGn",
                           rstride=2, cstride=2, alpha=0.92,
                           linewidth=0, antialiased=True,
                           edgecolor="none")
    # 등고선 투영
    ax.contour(X, Y, conf, zdir="z", offset=0.0,
               levels=10, cmap="RdYlGn", linewidths=0.6, alpha=0.7)

    # 임계 angle 평면 (30°/80°)
    for ang_deg, col in [(30, "#43A047"), (80, "#E53935")]:
        a = np.deg2rad(ang_deg)
        rr = np.linspace(0, 1.0, 30)
        # +ang
        xs = rr * np.cos(a); ys = rr * np.sin(a)
        ax.plot(xs, ys, np.zeros_like(rr), color=col, lw=2.0,
                alpha=0.9, zorder=20)
        ax.plot(xs, -ys, np.zeros_like(rr), color=col, lw=2.0,
                alpha=0.9, zorder=20)

    cb = plt.colorbar(surf, ax=ax, fraction=0.045, pad=0.04, shrink=0.7)
    cb.set_label("Confidence", fontsize=9)

    ax.set_xlabel("Re", fontsize=10, labelpad=2)
    ax.set_ylabel("Im", fontsize=10, labelpad=2)
    ax.set_zlabel("conf", fontsize=10, labelpad=2)
    ax.view_init(elev=24, azim=-58)
    ax.set_title("Confidence  $C(\\rho,\\theta)$  3D 표면",
                 fontsize=13, color="#1D3557", pad=8)


def panel_theta_dist(ax):
    """도메인별 θ 분포 (match vs null)."""
    domains = ["Img", "Doc", "Movie", "Rec"]
    rng = np.random.default_rng(2026)

    width = 0.35
    x = np.arange(len(domains))

    match_q90 = [C.PHASE_RIDGE[d]["match_q90"] for d in domains]
    null_q10  = [C.PHASE_RIDGE[d]["null_q10"]  for d in domains]
    match_q50 = [C.PHASE_RIDGE[d]["match_q50"] for d in domains]
    null_q50  = [C.PHASE_RIDGE[d]["null_q50"]  for d in domains]

    # 박스플롯 형태로
    for i, d in enumerate(domains):
        c = C.DOMAIN_COLORS[d]
        # match (왼쪽)
        ax.bar(i - width/2, match_q90[i] - 0.0, width=width,
               bottom=0, color=c, alpha=0.85, edgecolor="white")
        ax.plot([i - width/2 - width*0.4, i - width/2 + width*0.4],
                [match_q50[i], match_q50[i]], color="white", linewidth=2.0,
                solid_capstyle="round")
        # null (오른쪽)
        ax.bar(i + width/2, C.PHASE_RIDGE[d]["null_q50"] * 2.5, width=width,
               bottom=0, color=c, alpha=0.30, edgecolor=c, linewidth=1.5,
               hatch="////")
        ax.plot([i + width/2 - width*0.4, i + width/2 + width*0.4],
                [null_q50[i], null_q50[i]], color="#222", linewidth=2.0,
                solid_capstyle="round")

        # separation 표시
        sep = C.PHASE_RIDGE[d]["sep"]
        ax.annotate("", xy=(i, null_q50[i]),
                    xytext=(i, match_q50[i]),
                    arrowprops=dict(arrowstyle="<->", color="#555",
                                    lw=1.2, alpha=0.7))
        ax.text(i + 0.05, (match_q50[i] + null_q50[i]) / 2,
                f"Δ={sep:.1f}°", fontsize=8, color="#555",
                fontweight="bold")

    ax.set_xticks(x); ax.set_xticklabels(domains, fontsize=11)
    ax.set_ylabel("위상 θ  (degrees)", fontsize=11)
    ax.set_title("도메인별 match vs null  위상 분포  (q50 / q90)",
                 fontsize=12, color="#1D3557", pad=8)
    ax.set_ylim(0, max(C.PHASE_RIDGE[d]["null_q50"] * 2.6 for d in domains))

    # 범례
    from matplotlib.patches import Patch
    handles = [
        Patch(facecolor="#888", alpha=0.85, label="match  (q90 height, q50 line)"),
        Patch(facecolor="#888", alpha=0.30, hatch="////",
              label="null   (q50×2.5 height, q50 line)"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=8.5,
              framealpha=0.92)


def main():
    fig = plt.figure(figsize=(19, 8.0))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.1, 1.0], wspace=0.22)

    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1], projection="3d")
    ax3 = fig.add_subplot(gs[0, 2])

    panel_argand_2d(ax1)
    panel_confidence_3d(ax2)
    panel_theta_dist(ax3)

    fig.suptitle(
        "Phase Filter  —  Argand 평면 신뢰도 게이팅 (2D + 3D)",
        fontsize=17, fontweight="bold", color="#1D3557", y=0.99)
    fig.text(0.5, -0.005,
             r"$z = \rho \cdot e^{i\theta}$,   "
             r"$\rho = |\langle q,d \rangle|$,   "
             r"$\theta = \mathrm{arctan2}(Im_\perp \cdot q,\, Re \cdot q)$   "
             r"  —  신뢰 $|\theta|<30°$,  의심 30~80°,  거부 $\geq 80°$",
             ha="center", fontsize=11, color="#444")

    plt.subplots_adjust(top=0.92, bottom=0.06)
    C.save(fig, "fig08_phase_argand_3d.png")


if __name__ == "__main__":
    main()
