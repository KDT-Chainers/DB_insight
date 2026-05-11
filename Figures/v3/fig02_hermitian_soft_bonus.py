"""Fig 2 - Hermitian Soft Bonus: Quadratic vs Linear vs Product (PPT square, v3.1)."""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from _common import setup_style, save, AXIS_COLORS

setup_style()
fig = plt.figure(figsize=(14, 13))
gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.38)
fig.suptitle("Fig. 2  Hermitian Soft Bonus: Quadratic vs Linear vs Product",
             fontsize=19, fontweight="bold", y=1.01)

A = np.linspace(0.01, 1.0, 300)
alpha = 0.4

# ── (a) Score vs A (B=0.6 fixed) ──
ax1 = fig.add_subplot(gs[0, 0])
B_fixed = 0.6
quad    = np.sqrt(A**2 + (alpha * B_fixed)**2)
linear  = A + alpha * B_fixed
product = A * (1 + alpha * B_fixed)
aonly   = A.copy()

ax1.plot(A, quad,    lw=3.0, color="#C62828",          label=r"Quadratic $\sqrt{A^2+(\alpha B)^2}$", zorder=5)
ax1.plot(A, linear,  lw=2.5, color=AXIS_COLORS["Im"],  ls="--", label=r"Linear $A+\alpha B$")
ax1.plot(A, product, lw=2.5, color="#E65100",          ls="-.", label=r"Product $A(1+\alpha B)$")
ax1.plot(A, aonly,   lw=2.0, color="#AAAAAA",          ls=":",  label="A only")

ax1.fill_between(A, aonly, quad, alpha=0.09, color="#C62828")
ax1.annotate("Soft bonus\nregion (+B contribution)",
             xy=(0.3, 0.37), fontsize=12, color="#C62828", fontweight="bold",
             ha="center")

ax1.set_xlabel("A  (Re axis score)", fontsize=15, fontweight="bold")
ax1.set_ylabel("Fused Score  s", fontsize=15, fontweight="bold")
ax1.set_title("(a)  Score vs A   (B = 0.6 fixed)", fontsize=15, fontweight="bold", pad=12)
ax1.legend(fontsize=11, loc="upper left", framealpha=0.95)
ax1.set_xlim(0, 1.05)
ax1.set_ylim(0, 1.55)

# ── (b) 2D Contour ──
ax2 = fig.add_subplot(gs[0, 1])
Ag, Bg = np.meshgrid(np.linspace(0.01, 1.0, 150), np.linspace(0.01, 1.0, 150))
SS = np.sqrt(Ag**2 + (alpha * Bg)**2)

cf = ax2.contourf(Ag, Bg, SS, levels=20, cmap="RdYlGn", alpha=0.85)
cs = ax2.contour(Ag, Bg, SS, levels=[0.3, 0.5, 0.7, 0.9, 1.0],
                 colors="black", linewidths=1.0, alpha=0.5)
ax2.clabel(cs, fontsize=11, fmt="%.1f")
cbar = fig.colorbar(cf, ax=ax2, shrink=0.85, pad=0.03)
cbar.set_label("Hermitian Score", fontsize=13)
cbar.ax.tick_params(labelsize=12)

ax2.plot(0.8, 0.6, "o", color="white", markersize=11,
         markeredgecolor="black", markeredgewidth=2, zorder=6)
s_ref = np.sqrt(0.8**2 + (alpha * 0.6)**2)
ax2.annotate(f"A=0.8, B=0.6\ns={s_ref:.3f}",
             xy=(0.8, 0.6), xytext=(0.3, 0.88),
             fontsize=12, fontweight="bold",
             arrowprops=dict(arrowstyle="->", color="black", lw=2),
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                       edgecolor="black", alpha=0.95))

ax2.set_xlabel(r"$A = q_{Re} \cdot d_{Re}$", fontsize=15, fontweight="bold")
ax2.set_ylabel(r"$B = q_{Im} \cdot d_{Im}$", fontsize=15, fontweight="bold")
ax2.set_title(r"(b)  Hermitian Contour ($\alpha=0.4$)", fontsize=15, fontweight="bold", pad=12)

# ── (c) Marginal Contribution ──
ax3 = fig.add_subplot(gs[1, 0])
B_r = np.linspace(0.01, 1.0, 300)
for A_val, color, ls, lbl in [
        (0.3, AXIS_COLORS["Re"], "-",  "A = 0.3"),
        (0.6, AXIS_COLORS["Im"], "--", "A = 0.6"),
        (0.9, "#C62828",          "-.", "A = 0.9")]:
    dsdB = (alpha**2 * B_r) / np.sqrt(A_val**2 + (alpha * B_r)**2)
    ax3.plot(B_r, dsdB, lw=2.8, color=color, ls=ls, label=lbl)

ax3.set_xlabel("B  (Im axis score)", fontsize=15, fontweight="bold")
ax3.set_ylabel(r"$\partial s / \partial B$", fontsize=15, fontweight="bold")
ax3.set_title("(c)  Marginal Contribution of B", fontsize=15, fontweight="bold", pad=12)
ax3.legend(fontsize=13, loc="upper left", framealpha=0.95)
ax3.set_xlim(0, 1.05)
ax3.set_ylim(0, 0.20)

ax3.annotate("A large\n→ B effect\ndiminishes",
             xy=(0.82, 0.024), xytext=(0.55, 0.13),
             fontsize=12, color="#C62828", fontweight="bold",
             arrowprops=dict(arrowstyle="->", color="#C62828", lw=1.8),
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#FFEBEE",
                       edgecolor="#C62828", alpha=0.9))

# ── (d) Alpha sensitivity ──
ax4 = fig.add_subplot(gs[1, 1])
A_fixed = 0.7
B_fixed2 = 0.6
alphas = np.linspace(0, 1.0, 200)
scores = np.sqrt(A_fixed**2 + (alphas * B_fixed2)**2)

ax4.plot(alphas, scores, lw=3.0, color="#1565C0", zorder=5)
ax4.axvline(0.4, color="#C62828", lw=2.5, ls="--")
ax4.text(0.42, 0.72, r"$\alpha=0.4$ (chosen)", fontsize=13,
         color="#C62828", fontweight="bold")
ax4.fill_between(alphas, A_fixed, scores, alpha=0.12, color="#1565C0")

ax4.set_xlabel(r"$\alpha$  (Im weight)", fontsize=15, fontweight="bold")
ax4.set_ylabel("Fused Score  s", fontsize=15, fontweight="bold")
ax4.set_title(r"(d)  Alpha Sensitivity  (A=0.7, B=0.6)", fontsize=15, fontweight="bold", pad=12)
ax4.set_xlim(0, 1.05)
ax4.set_ylim(0.68, 1.08)
ax4.axhline(A_fixed, color="#AAAAAA", lw=1.5, ls=":")
ax4.text(0.85, A_fixed + 0.005, "A only = 0.70", fontsize=12, color="#AAAAAA")

save(fig, "fig02_hermitian_soft_bonus.png")
