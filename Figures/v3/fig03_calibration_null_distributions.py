"""Fig 3 - Calibration Null Distribution & tau per Domain (v3.1 no-overlap)."""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm
from _common import setup_style, save, CAL, DOMAIN_COLORS

setup_style()
fig, axes = plt.subplots(2, 2, figsize=(18, 13))
fig.suptitle(r"Fig. 3  Null Distribution & Threshold $\tau$ per Domain",
             fontsize=19, fontweight="bold", y=1.01)

domains = ["Doc", "Img", "Movie", "Rec"]
panel_labels = ["(a)", "(b)", "(c)", "(d)"]
fill_colors = ["#BBDEFB", "#FFCCBC", "#C8E6C9", "#F8BBD0"]
line_colors = ["#1565C0", "#E65100", "#2E7D32", "#C62828"]

# Domain-specific layout tweaks to avoid label overlap
LAYOUT = {
    "Doc":   {"tau_y_frac": 0.80, "tau_ha": "left",  "tau_dx": 0.3,
              "mu_y_frac": 1.05,  "sigma_y_frac": 0.45,
              "legend_loc": "upper left",  "info_pos": (0.97, 0.97), "info_ha": "right"},
    "Img":   {"tau_y_frac": 0.75, "tau_ha": "left",  "tau_dx": 0.8,
              "mu_y_frac": 1.05,  "sigma_y_frac": 0.35,
              "legend_loc": "upper left",  "info_pos": (0.97, 0.97), "info_ha": "right"},
    "Movie": {"tau_y_frac": 0.75, "tau_ha": "left",  "tau_dx": 0.8,
              "mu_y_frac": 1.05,  "sigma_y_frac": 0.35,
              "legend_loc": "upper left",  "info_pos": (0.97, 0.97), "info_ha": "right"},
    "Rec":   {"tau_y_frac": 0.80, "tau_ha": "left",  "tau_dx": 0.3,
              "mu_y_frac": 1.05,  "sigma_y_frac": 0.45,
              "legend_loc": "upper left",  "info_pos": (0.97, 0.97), "info_ha": "right"},
}

for idx, (dom, ax) in enumerate(zip(domains, axes.flat)):
    c = CAL[dom]
    mu, sigma, tau, far = c["mu"], c["sigma"], c["tau"], c["FAR"]
    N = c["N"]
    lo = LAYOUT[dom]

    # x range: extend past tau
    x_lo = mu - 4.5 * sigma
    x_hi = max(tau + 4 * sigma, mu + 5 * sigma)
    x = np.linspace(x_lo, x_hi, 500)
    y = norm.pdf(x, mu, sigma)
    y_peak = y.max()

    # ── Null distribution fill + line ──
    ax.fill_between(x, y, alpha=0.28, color=fill_colors[idx], zorder=2)
    ax.plot(x, y, lw=2.5, color=line_colors[idx], zorder=3)

    # ── FAR shaded area (right of tau) ──
    x_far = x[x >= tau]
    y_far = norm.pdf(x_far, mu, sigma)
    ax.fill_between(x_far, y_far, alpha=0.40, color="#FF8A80",
                    label=f"FAR = {far:.0%}", zorder=3)

    # ── Noise label ──
    x_noise = x[x <= tau]
    y_noise = norm.pdf(x_noise, mu, sigma)
    ax.fill_between(x_noise, y_noise, alpha=0.0)  # invisible, just for legend
    ax.plot([], [], color=fill_colors[idx], alpha=0.5, lw=8,
            label=f"Noise ({1-far:.0%} blocked)")

    # ── tau vertical line ──
    ax.axvline(tau, color="#C62828", lw=2.5, ls="--", zorder=5)

    # ── tau label (positioned to avoid mu) ──
    tau_label_x = tau + sigma * lo["tau_dx"]
    tau_label_y = y_peak * lo["tau_y_frac"]
    ax.annotate(
        r"$\tau$ = " + f"{tau:.4f}",
        xy=(tau, tau_label_y * 0.7), xytext=(tau_label_x, tau_label_y),
        fontsize=14, fontweight="bold", color="#C62828",
        ha=lo["tau_ha"], va="center",
        arrowprops=dict(arrowstyle="-|>", color="#C62828", lw=1.5),
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="#C62828", alpha=0.95, lw=1.5),
        zorder=6)

    # ── mu line + label (always at peak, centered) ──
    ax.axvline(mu, color=line_colors[idx], lw=1.5, ls=":", alpha=0.5, zorder=2)
    ax.text(mu, y_peak * lo["mu_y_frac"],
            r"$\mu$=" + f"{mu:.3f}",
            ha="center", va="bottom", fontsize=12, fontweight="bold",
            color=line_colors[idx])

    # ── sigma bracket (below peak, between mu and mu+sigma) ──
    bracket_y = y_peak * lo["sigma_y_frac"]
    ax.annotate("", xy=(mu + sigma, bracket_y), xytext=(mu, bracket_y),
                arrowprops=dict(arrowstyle="<->", color="#333333", lw=1.5))
    ax.text(mu + sigma / 2, bracket_y * 1.12,
            r"$\sigma$=" + f"{sigma:.4f}",
            ha="center", va="bottom", fontsize=11, fontweight="bold")

    # ── Info box (top-right, in axes coords) ──
    z_star = norm.ppf(1 - far)
    info = (f"N = {N:,}\n"
            r"$z^*$ = " + f"{z_star:.3f}\n"
            r"$\tau = \mu + z^* \cdot \sigma$")
    ix, iy = lo["info_pos"]
    ax.text(ix, iy, info, transform=ax.transAxes,
            fontsize=11, va="top", ha=lo["info_ha"],
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor="#BDBDBD", alpha=0.95))

    # ── Title & axis labels ──
    ax.set_title(f"{panel_labels[idx]}  {dom}  "
                 + r"$-$  $\tau$ = " + f"{tau:.4f}",
                 fontsize=16, fontweight="bold", pad=14,
                 color=DOMAIN_COLORS[dom])
    ax.set_xlabel("Hermitian Score", fontsize=14)
    ax.set_ylabel("Probability Density", fontsize=14)
    ax.legend(fontsize=11, loc=lo["legend_loc"], framealpha=0.9)
    ax.set_ylim(bottom=0)

fig.tight_layout(rect=[0, 0, 1, 0.96])
save(fig, "fig03_calibration_null_distributions.png")
