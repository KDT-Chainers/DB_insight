"""fig04: Gram-Schmidt 직교화 — 3D + 2D 보조.

Re/Im/Z 원본 벡터 → Im_⊥, Z_⊥ 직교화 후. 좌측 3D, 우측 직교성 verification 2D.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

import _common as C
C.setup_style()


def gram_schmidt_3(re, im, z):
    """간단 GS — Re 정규화, Im⊥ = Im - (Im·Re_hat)Re_hat, Z⊥ = Z - (Z·Re_hat)Re_hat
    - (Z·Im⊥_hat)Im⊥_hat
    """
    rh = re / np.linalg.norm(re)
    im_p = im - (im @ rh) * rh
    im_ph = im_p / np.linalg.norm(im_p)
    z_p = z - (z @ rh) * rh - (z @ im_ph) * im_ph
    return rh, im_p / np.linalg.norm(im_p), z_p / np.linalg.norm(z_p)


def draw_arrow_3d(ax, origin, vec, color, label=None, lw=2.6, alpha=1.0,
                  ls="-", labelpad=0.13):
    a = np.array(origin, dtype=float)
    v = np.array(vec, dtype=float)
    b = a + v
    ax.quiver(a[0], a[1], a[2], v[0], v[1], v[2],
              color=color, linewidth=lw, arrow_length_ratio=0.12,
              alpha=alpha, linestyle=ls)
    if label:
        # 벡터 방향으로 오프셋 → 화살표 팁과 겹치지 않음
        direction = v / np.linalg.norm(v)
        tip = b + direction * labelpad
        ax.text(tip[0], tip[1], tip[2],
                label, fontsize=11, fontweight="bold", color=color,
                ha="center", va="center")


def panel_before(ax):
    ax.set_title("Before:  Re · Im · Z  (원본 벡터)\n"
                 "Im, Z 가 Re 와 부분 정렬 → 채널 중복",
                 fontsize=12, color="#37474F")

    re = np.array([1.0, 0.0, 0.0])
    im = np.array([0.78, 0.55, 0.22])  # Re 와 부분 정렬
    z  = np.array([0.62, 0.30, 0.62])  # Re/Im 와 부분 정렬

    draw_arrow_3d(ax, [0,0,0], re, C.AXIS_COLORS["Re"], "Re")
    draw_arrow_3d(ax, [0,0,0], im, C.AXIS_COLORS["Im"], "Im")
    draw_arrow_3d(ax, [0,0,0], z,  C.AXIS_COLORS["Z"],  "Z")

    # Re·Im 사잇각 표기
    cos_re_im = (re @ im) / (np.linalg.norm(re) * np.linalg.norm(im))
    ang = np.degrees(np.arccos(cos_re_im))
    ax.text2D(0.05, 0.93,
              r"$\langle$Re,Im$\rangle$ = " f"{cos_re_im:.2f}"
              r"   ($\theta \approx$ " f"{ang:.1f}°)",
              transform=ax.transAxes, fontsize=9.5,
              color="#C62828", fontweight="bold")

    _setup_axes(ax)


def panel_after(ax):
    ax.set_title("After:  Re · $Im_\\perp$ · $Z_\\perp$  (직교화 후)\n"
                 "독립 신호 → Hermitian 점수 안정",
                 fontsize=12, color="#1B5E20")

    re = np.array([1.0, 0.0, 0.0])
    im = np.array([0.78, 0.55, 0.22])
    z  = np.array([0.62, 0.30, 0.62])

    rh, ip, zp = gram_schmidt_3(re, im, z)
    draw_arrow_3d(ax, [0,0,0], rh, C.AXIS_COLORS["Re"], "Re")
    draw_arrow_3d(ax, [0,0,0], ip, C.AXIS_COLORS["Im"], "$Im_\\perp$")
    draw_arrow_3d(ax, [0,0,0], zp, C.AXIS_COLORS["Z"],  "$Z_\\perp$")

    # 직교 평면 음영 표시 (Re 에 수직)
    yy, zz = np.meshgrid(np.linspace(-0.3, 1.0, 2), np.linspace(-0.3, 1.0, 2))
    xx = np.zeros_like(yy)
    ax.plot_surface(xx, yy, zz, color=C.AXIS_COLORS["Re"],
                    alpha=0.05, edgecolor="none")

    cos_check = abs(rh @ ip)
    ax.text2D(0.05, 0.93,
              r"$\langle$Re, $Im_\perp$$\rangle$ = "
              f"{cos_check:.0e}    "
              r"($\perp$ 검증)",
              transform=ax.transAxes, fontsize=9.5,
              color="#1B5E20", fontweight="bold")

    _setup_axes(ax)


def _setup_axes(ax):
    ax.set_xlim(-0.2, 1.2); ax.set_ylim(-0.2, 1.2); ax.set_zlim(-0.2, 1.2)
    ax.set_xlabel("Axis-1", fontsize=9, labelpad=2)
    ax.set_ylabel("Axis-2", fontsize=9, labelpad=2)
    ax.set_zlabel("Axis-3", fontsize=9, labelpad=2)
    ax.tick_params(labelsize=8)
    ax.view_init(elev=25, azim=40)
    # 면 완전 투명 — 화살표가 pane 뒤에 숨지 않도록
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.fill = False
        pane.set_facecolor((0.0, 0.0, 0.0, 0.0))
        pane.set_edgecolor("lightgray")


def panel_dot(ax):
    """3쌍 (Re·Im, Re·Z, Im·Z) cosine 개선 막대."""
    pairs = [r"$\langle$Re, Im$\rangle$",
             r"$\langle$Re, Z$\rangle$",
             r"$\langle$Im, Z$\rangle$"]
    before = [0.81, 0.74, 0.58]   # 정성적 예시
    after  = [0.001, 0.0008, 0.0005]

    x = np.arange(len(pairs))
    w = 0.36
    b1 = ax.bar(x - w/2, before, w, color="#E57373",
                edgecolor="white", label="Before (원본)")
    b2 = ax.bar(x + w/2, after,  w, color="#66BB6A",
                edgecolor="white", label="After (직교화)")

    ax.set_xticks(x); ax.set_xticklabels(pairs, fontsize=10)
    ax.set_ylabel("cosine similarity", fontsize=10)
    ax.set_ylim(0, 1.0)
    ax.set_title("축간 내적 — 직교화 전후",
                 fontsize=12, color="#1D3557", pad=8)
    ax.legend(loc="upper right", fontsize=9)

    for b, v in zip(b1, before):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}",
                ha="center", fontsize=9, color="#C62828",
                fontweight="bold")
    for b, v in zip(b2, after):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.0e}",
                ha="center", fontsize=9, color="#1B5E20",
                fontweight="bold")


def main():
    fig = plt.figure(figsize=(18, 7.5))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.1, 1.1, 0.95], wspace=0.20)

    ax1 = fig.add_subplot(gs[0, 0], projection="3d")
    ax2 = fig.add_subplot(gs[0, 1], projection="3d")
    ax3 = fig.add_subplot(gs[0, 2])

    panel_before(ax1)
    panel_after(ax2)
    panel_dot(ax3)

    fig.suptitle(
        "Gram-Schmidt 직교화 — Tri-CHEF 3축 독립 신호 확보",
        fontsize=18, fontweight="bold", color="#1D3557", y=1.01)

    fig.text(0.5, -0.005,
             "공식:  "
             "$\\hat{\\mathbf{r}} = \\mathbf{Re}/\\|\\mathbf{Re}\\|$,   "
             "$\\mathbf{Im}_\\perp = \\mathbf{Im} - (\\mathbf{Im}\\cdot\\hat{\\mathbf{r}})\\,\\hat{\\mathbf{r}}$,   "
             "$\\mathbf{Z}_\\perp = \\mathbf{Z} - "
             "(\\mathbf{Z}\\cdot\\hat{\\mathbf{r}})\\,\\hat{\\mathbf{r}} - "
             "(\\mathbf{Z}\\cdot\\hat{\\mathbf{i}}_\\perp)\\,\\hat{\\mathbf{i}}_\\perp$",
             ha="center", fontsize=11, color="#444")

    plt.subplots_adjust(top=0.90, bottom=0.08)
    C.save(fig, "fig04_gram_schmidt_3d.png")


if __name__ == "__main__":
    main()
