"""fig05: Hermitian Score 지형 — 3D 곡면 + 등고선.

s(q,d) = √(A² + (αB)² + (βC)²),  α=0.4, β=0.2.
A = q_Re·d_Re,  B = q_Im·d_Im,  C = q_Z·d_Z

좌측: A·B 평면 (C=0.5 고정) 3D 곡면.
우측: A·B 평면 등고선 + α 변화 비교.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa
import matplotlib.cm as cm
from matplotlib.colors import LightSource
import numpy as np

import _common as C
C.setup_style()


def hermitian_score(A, B, C_fixed, alpha=0.4, beta=0.2):
    return np.sqrt(A**2 + (alpha * B)**2 + (beta * C_fixed)**2)


def panel_3d(ax, alpha=0.4, beta=0.2, c_fixed=0.5):
    A = np.linspace(0, 1, 60)
    B = np.linspace(0, 1, 60)
    AA, BB = np.meshgrid(A, B)
    SS = hermitian_score(AA, BB, c_fixed, alpha, beta)

    # 음영 추가
    ls = LightSource(azdeg=315, altdeg=45)
    rgb = ls.shade(SS, cmap=cm.viridis, vert_exag=1, blend_mode="overlay")
    ax.plot_surface(AA, BB, SS, facecolors=rgb, rstride=1, cstride=1,
                    linewidth=0, antialiased=True, alpha=0.95)
    # 바닥에 등고선 투영
    ax.contour(AA, BB, SS, zdir="z", offset=0.0,
               levels=10, cmap="viridis", linewidths=0.7, alpha=0.9)

    # 도메인 위치 마커 (가상 score points)
    domain_pts = {
        "Img":   (0.85, 0.30),
        "Movie": (0.78, 0.55),
        "Doc":   (0.45, 0.82),
        "Rec":   (0.55, 0.92),
        "BGM":   (0.72, 0.68),
    }
    for d, (a, b) in domain_pts.items():
        s = hermitian_score(a, b, c_fixed, alpha, beta)
        ax.scatter([a], [b], [s], s=120, color=C.DOMAIN_COLORS[d],
                   edgecolors="white", linewidth=1.5, zorder=10)
        ax.text(a + 0.03, b + 0.03, s + 0.04, d, fontsize=9,
                fontweight="bold", color=C.DOMAIN_COLORS[d])

    ax.set_xlabel("$A = \\langle q_{Re}, d_{Re}\\rangle$", fontsize=10)
    ax.set_ylabel("$B = \\langle q_{Im}, d_{Im}\\rangle$", fontsize=10)
    ax.set_zlabel("Hermitian score  $s$", fontsize=10)
    ax.set_zlim(0, 1.2)
    ax.view_init(elev=22, azim=-58)
    ax.set_title(f"3D 곡면  ($C={c_fixed}$, $\\alpha={alpha}$, $\\beta={beta}$)",
                 fontsize=12, pad=8, color="#1D3557")


def panel_contour_alpha(ax):
    A = np.linspace(0, 1, 200)
    B = np.linspace(0, 1, 200)
    AA, BB = np.meshgrid(A, B)
    c_fixed = 0.5

    alphas = [0.2, 0.4, 0.6, 1.0]
    colors = ["#1565C0", "#43A047", "#FB8C00", "#E53935"]
    levels = [0.4, 0.6, 0.8]

    for alpha, color in zip(alphas, colors):
        SS = hermitian_score(AA, BB, c_fixed, alpha=alpha, beta=0.2)
        cs = ax.contour(AA, BB, SS, levels=levels, colors=[color],
                        linewidths=1.6, alpha=0.85, linestyles="-")
        # 0.6 등고선만 라벨
        ax.clabel(cs, inline=True, fontsize=7, fmt="%.1f", colors=color)

    # 운영값 α=0.4 강조
    SS_op = hermitian_score(AA, BB, c_fixed, alpha=0.4, beta=0.2)
    ax.contourf(AA, BB, SS_op, levels=20, cmap="viridis", alpha=0.18)

    # 범례
    from matplotlib.lines import Line2D
    handles = [Line2D([0], [0], color=c, lw=2.0,
                      label=f"α = {a}{' (운영)' if abs(a-0.4)<1e-9 else ''}")
               for c, a in zip(colors, alphas)]
    ax.legend(handles=handles, loc="lower right", fontsize=9,
              framealpha=0.9)

    ax.set_xlabel("A = ⟨$q_{Re}$, $d_{Re}$⟩", fontsize=10)
    ax.set_ylabel("B = ⟨$q_{Im}$, $d_{Im}$⟩", fontsize=10)
    ax.set_title("α (Im 감쇠) 변화에 따른 등고선",
                 fontsize=12, color="#1D3557", pad=8)
    ax.set_aspect("equal")


def panel_alpha_beta_grid(ax):
    """α-β 격자에서 score 변화율 (∂s/∂B at B=0.5, A=0.5, C=0.5)."""
    alpha = np.linspace(0.1, 1.0, 60)
    beta  = np.linspace(0.1, 1.0, 60)
    AA, BB = np.meshgrid(alpha, beta)

    A0, B0, C0 = 0.5, 0.5, 0.5
    score = np.sqrt(A0**2 + (AA*B0)**2 + (BB*C0)**2)

    cf = ax.contourf(AA, BB, score, levels=18, cmap="plasma", alpha=0.92)
    cs = ax.contour (AA, BB, score, levels=8, colors="white",
                     linewidths=0.6, alpha=0.7)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%.2f", colors="white")

    # 운영점 (α=0.4, β=0.2)
    ax.scatter([0.4], [0.2], s=200, color="white",
               edgecolors="#E53935", linewidth=2.5, zorder=10,
               label="운영점 (α=0.4, β=0.2)")
    ax.annotate("운영점", xy=(0.4, 0.2), xytext=(0.62, 0.42),
                fontsize=9.5, fontweight="bold", color="#E53935",
                arrowprops=dict(arrowstyle="->", color="#E53935", lw=1.6))

    cb = plt.colorbar(cf, ax=ax, fraction=0.046, pad=0.03)
    cb.set_label("$s$ at $A=B=C=0.5$", fontsize=9)

    ax.set_xlabel("α  (Im 감쇠)", fontsize=10)
    ax.set_ylabel("β  (Z 감쇠)",  fontsize=10)
    ax.set_title("α-β 그리드  (감쇠 계수 sensitivity)",
                 fontsize=12, color="#1D3557", pad=8)
    ax.set_aspect("equal")


def main():
    fig = plt.figure(figsize=(19, 7.0))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.2, 1.0, 1.0], wspace=0.22)

    ax1 = fig.add_subplot(gs[0, 0], projection="3d")
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[0, 2])

    panel_3d(ax1)
    panel_contour_alpha(ax2)
    panel_alpha_beta_grid(ax3)

    fig.suptitle(
        "Hermitian Score 지형  $s(q,d)=\\sqrt{A^2 + (\\alpha B)^2 + (\\beta C)^2}$",
        fontsize=17, fontweight="bold", color="#1D3557", y=1.02)
    fig.text(0.5, -0.01,
             r"$A = \langle q_{Re},\, d_{Re} \rangle$  (SigLIP2),  "
             r"$B = \langle q_{Im},\, d_{Im} \rangle$  (BGE-M3),  "
             r"$C = \langle q_{Z},\, d_{Z} \rangle$  (DINOv2)  —  "
             r"운영값 $\alpha=0.4$ (Im 감쇠), $\beta=0.2$ (Z 감쇠)",
             ha="center", fontsize=10.5, color="#444")

    plt.subplots_adjust(top=0.88, bottom=0.10)
    C.save(fig, "fig05_hermitian_landscape_3d.png")


if __name__ == "__main__":
    main()
