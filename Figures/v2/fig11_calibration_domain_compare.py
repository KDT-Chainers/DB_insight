"""fig11 — 도메인별 보정(Calibration) 파라미터 비교 시각화.

τ = μ_null + Φ⁻¹(1 − FAR) · σ_null

실측 데이터 출처:
  Data/embedded_DB/trichef_calibration.json  (2026-05-07 기준)
"""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D
from scipy.stats import norm

from _common import setup_style, save, DOMAIN_COLORS, OUT_DIR

# ─────────────────────────────────────────────
# 1. 실측 보정 파라미터 (trichef_calibration.json)
# ─────────────────────────────────────────────
CAL = {
    "Doc": {
        "mu":    0.7982219457626343,
        "sigma": 0.09672129899263382,
        "tau":   0.9573143250383084,
        "FAR":   0.05,
        "N":     34718,
    },
    "Img": {
        "mu":    0.21973596513271332,
        "sigma": 0.0349915511906147,
        "tau":   0.24918559758077505,
        "FAR":   0.20,
        "N":     2390,
    },
    "Movie": {
        "mu":    0.157612606883049,
        "sigma": 0.04241589829325676,
        "tau":   0.22738055095401466,
        "FAR":   0.05,
        "N":     45647,
    },
    "Rec": {
        "mu":    0.6808651685714722,
        "sigma": 0.06834075599908829,
        "tau":   0.7932757088209501,
        "FAR":   0.05,
        "N":     11039,
    },
    "BGM": None,   # 미보정
}

DOMAINS = ["Doc", "Img", "Movie", "Rec", "BGM"]
CALIBRATED = [d for d in DOMAINS if CAL[d] is not None]

# 파생 값 계산
for d in CALIBRATED:
    c = CAL[d]
    c["one_minus_far"] = 1.0 - c["FAR"]                    # 1 - FAR
    c["z_star"]        = norm.ppf(c["one_minus_far"])       # Φ⁻¹(1-FAR)
    c["phi_z"]         = norm.cdf(c["z_star"])              # Φ(z*) = 1-FAR (검증)
    c["tau_check"]     = c["mu"] + c["z_star"] * c["sigma"]

# ─────────────────────────────────────────────
# 2. 레이아웃
# ─────────────────────────────────────────────
setup_style()
fig = plt.figure(figsize=(18, 14))
fig.suptitle(
    "도메인별 Null 분포 보정 파라미터 비교\n"
    r"$\tau = \mu_{\mathrm{null}} + \Phi^{-1}(1-\mathrm{FAR})\cdot\sigma_{\mathrm{null}}$",
    fontsize=15, fontweight="bold", y=0.98,
)

gs = gridspec.GridSpec(
    3, 3,
    figure=fig,
    hspace=0.52, wspace=0.38,
    left=0.07, right=0.97, top=0.91, bottom=0.06,
)

ax_table  = fig.add_subplot(gs[0, :])      # 상단 전체 — 표
ax_dist   = fig.add_subplot(gs[1, :])      # 중간 전체 — null 분포 곡선
ax_mu     = fig.add_subplot(gs[2, 0])      # 하단 좌 — μ 비교
ax_sigma  = fig.add_subplot(gs[2, 1])      # 하단 중 — σ 비교
ax_zstar  = fig.add_subplot(gs[2, 2])      # 하단 우 — Φ⁻¹ & FAR 비교

# ─────────────────────────────────────────────
# 3. 표 (ax_table)
# ─────────────────────────────────────────────
ax_table.axis("off")

col_labels = [
    "Domain",
    "N",
    r"$\tau$",
    r"$\mu_{\mathrm{null}}$",
    r"$\sigma_{\mathrm{null}}$",
    r"$\Phi^{-1}(1-\mathrm{FAR})$",
    r"$\Phi(z^*)$",
    r"$1-\mathrm{FAR}$",
    "FAR",
]

rows = []
for d in DOMAINS:
    c = CAL[d]
    if c is None:
        rows.append([d, "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a"])
    else:
        rows.append([
            d,
            f"{c['N']:,}",
            f"{c['tau']:.4f}",
            f"{c['mu']:.4f}",
            f"{c['sigma']:.4f}",
            f"{c['z_star']:.4f}",
            f"{c['phi_z']:.4f}",
            f"{c['one_minus_far']:.2f}",
            f"{c['FAR']:.2f}",
        ])

tbl = ax_table.table(
    cellText=rows,
    colLabels=col_labels,
    cellLoc="center",
    loc="center",
    bbox=[0, 0, 1, 1],
)
tbl.auto_set_font_size(False)
tbl.set_fontsize(9)

# 헤더 스타일
for j in range(len(col_labels)):
    tbl[(0, j)].set_facecolor("#2C3E50")
    tbl[(0, j)].set_text_props(color="white", fontweight="bold")

# 행별 색상
row_colors = {
    "Doc":   "#D6E4F7",
    "Img":   "#FCE5D0",
    "Movie": "#D4EDDA",
    "Rec":   "#F8D7DA",
    "BGM":   "#EDE7F6",
}
for i, d in enumerate(DOMAINS, start=1):
    for j in range(len(col_labels)):
        tbl[(i, j)].set_facecolor(row_colors[d])
        if CAL[d] is None:
            tbl[(i, j)].set_text_props(color="#888888", style="italic")

# τ 열(인덱스 2) 강조 / FAR 열(인덱스 8) 강조
TAU_COL = 2   # col_labels 순서: Domain, N, τ, ...
FAR_COL = 8   # ... FAR
for i in range(1, len(DOMAINS) + 1):
    tbl[(i, TAU_COL)].set_text_props(fontweight="bold", color="#B71C1C")
    if CAL[DOMAINS[i - 1]] is not None:
        tbl[(i, FAR_COL)].set_text_props(fontweight="bold")

ax_table.set_title("표 1. 도메인별 보정 파라미터 요약", fontsize=11,
                   fontweight="bold", pad=4, loc="left")

# ─────────────────────────────────────────────
# 4. Null 분포 곡선 (ax_dist)
# ─────────────────────────────────────────────
ax_dist.set_title("그림 A. 도메인별 Null 분포와 보정 임계값 τ", fontsize=11,
                  fontweight="bold", loc="left")
ax_dist.set_xlabel("Hermitian 스코어", fontsize=10)
ax_dist.set_ylabel("확률 밀도 (정규화)", fontsize=10)

legend_handles = []
for d in CALIBRATED:
    c = CAL[d]
    col = DOMAIN_COLORS[d]
    x = np.linspace(c["mu"] - 4 * c["sigma"], c["mu"] + 4 * c["sigma"], 400)
    y = norm.pdf(x, c["mu"], c["sigma"])

    ax_dist.plot(x, y, color=col, lw=2.2, label=d)

    # μ 수직선 (점선)
    ax_dist.axvline(c["mu"], color=col, lw=1.0, ls=":", alpha=0.6)

    # τ 수직선 (실선)
    ax_dist.axvline(c["tau"], color=col, lw=1.8, ls="--", alpha=0.9)

    # τ 오른쪽 FAR 음영
    x_fill = np.linspace(c["tau"], c["mu"] + 4 * c["sigma"], 200)
    y_fill = norm.pdf(x_fill, c["mu"], c["sigma"])
    ax_dist.fill_between(x_fill, y_fill, alpha=0.12, color=col)

    # τ 레이블
    y_at_tau = norm.pdf(c["tau"], c["mu"], c["sigma"])
    ax_dist.annotate(
        f"τ={c['tau']:.3f}\n({d})",
        xy=(c["tau"], y_at_tau),
        xytext=(c["tau"] + 0.004, y_at_tau + 0.3),
        fontsize=7.5, color=col, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color=col, lw=0.8),
    )

    legend_handles.append(
        Line2D([0], [0], color=col, lw=2.2, label=f"{d}  (μ={c['mu']:.3f}, σ={c['sigma']:.3f})")
    )

legend_handles += [
    Line2D([0], [0], color="gray", lw=1.8, ls="--", label="τ (임계값)"),
    Line2D([0], [0], color="gray", lw=1.0, ls=":", label="μ_null"),
]
ax_dist.legend(handles=legend_handles, fontsize=8, loc="upper right", ncol=2)
ax_dist.set_ylim(bottom=0)

# 이중 x축: Doc/Rec는 0.6~1.1, Movie/Img는 0.1~0.4 — 범위가 너무 달라 단일 x축으로 표시
ax_dist.set_xlim(-0.02, 1.12)

# ─────────────────────────────────────────────
# 5. 막대 그래프 — μ_null (ax_mu)
# ─────────────────────────────────────────────
ax_mu.set_title("그림 B. μ_null 비교", fontsize=10, fontweight="bold", loc="left")
ax_mu.set_ylabel("μ_null", fontsize=9)
x_pos = np.arange(len(CALIBRATED))
mu_vals = [CAL[d]["mu"] for d in CALIBRATED]
bars = ax_mu.bar(x_pos, mu_vals,
                 color=[DOMAIN_COLORS[d] for d in CALIBRATED],
                 edgecolor="white", linewidth=0.8, width=0.55)
ax_mu.set_xticks(x_pos)
ax_mu.set_xticklabels(CALIBRATED, fontsize=9)
for bar, v in zip(bars, mu_vals):
    ax_mu.text(bar.get_x() + bar.get_width() / 2, v + 0.008,
               f"{v:.4f}", ha="center", va="bottom", fontsize=7.5, fontweight="bold")
ax_mu.set_ylim(0, 1.05)
ax_mu.axhline(0.5, color="gray", ls="--", lw=0.8, alpha=0.5)
ax_mu.text(len(CALIBRATED) - 0.5, 0.51, "0.5 기준선", fontsize=7, color="gray")

# σ 에러바
sigma_vals = [CAL[d]["sigma"] for d in CALIBRATED]
ax_mu.errorbar(x_pos, mu_vals, yerr=sigma_vals,
               fmt="none", ecolor="black", elinewidth=1.2, capsize=4)

# ─────────────────────────────────────────────
# 6. 막대 그래프 — σ_null (ax_sigma)
# ─────────────────────────────────────────────
ax_sigma.set_title("그림 C. σ_null 비교", fontsize=10, fontweight="bold", loc="left")
ax_sigma.set_ylabel("σ_null", fontsize=9)
bars2 = ax_sigma.bar(x_pos, sigma_vals,
                     color=[DOMAIN_COLORS[d] for d in CALIBRATED],
                     edgecolor="white", linewidth=0.8, width=0.55)
ax_sigma.set_xticks(x_pos)
ax_sigma.set_xticklabels(CALIBRATED, fontsize=9)
for bar, v in zip(bars2, sigma_vals):
    ax_sigma.text(bar.get_x() + bar.get_width() / 2, v + 0.001,
                  f"{v:.4f}", ha="center", va="bottom", fontsize=7.5, fontweight="bold")
ax_sigma.set_ylim(0, max(sigma_vals) * 1.3)

# σ 의미 어노테이션
widest = CALIBRATED[np.argmax(sigma_vals)]
ax_sigma.annotate(
    f"최대 분산\n→ τ가 μ에서\n  멀어짐",
    xy=(np.argmax(sigma_vals), max(sigma_vals)),
    xytext=(np.argmax(sigma_vals) + 0.6, max(sigma_vals) * 0.85),
    fontsize=7, color=DOMAIN_COLORS[widest],
    arrowprops=dict(arrowstyle="->", color=DOMAIN_COLORS[widest], lw=0.8),
)

# ─────────────────────────────────────────────
# 7. Φ⁻¹ & FAR 이중 막대 (ax_zstar)
# ─────────────────────────────────────────────
ax_zstar.set_title(r"그림 D. $\Phi^{-1}(1-\mathrm{FAR})$ & FAR 비교",
                   fontsize=10, fontweight="bold", loc="left")

zstar_vals = [CAL[d]["z_star"] for d in CALIBRATED]
far_vals   = [CAL[d]["FAR"]    for d in CALIBRATED]

width = 0.35
ax_zstar.bar(x_pos - width / 2, zstar_vals,
             width=width, label=r"$\Phi^{-1}(1-\mathrm{FAR})$",
             color=[DOMAIN_COLORS[d] for d in CALIBRATED],
             edgecolor="white", linewidth=0.8, alpha=0.9)

ax_zstar2 = ax_zstar.twinx()
ax_zstar2.bar(x_pos + width / 2, far_vals,
              width=width, label="FAR",
              color=[DOMAIN_COLORS[d] for d in CALIBRATED],
              edgecolor="white", linewidth=0.8, alpha=0.45, hatch="//")
ax_zstar2.set_ylabel("FAR", fontsize=9, color="#555555")
ax_zstar2.set_ylim(0, 0.45)
ax_zstar2.tick_params(axis="y", labelsize=8)

ax_zstar.set_xticks(x_pos)
ax_zstar.set_xticklabels(CALIBRATED, fontsize=9)
ax_zstar.set_ylabel(r"$\Phi^{-1}(1-\mathrm{FAR})$", fontsize=9)
ax_zstar.set_ylim(0, 2.2)

# 값 레이블
for i, (z, f) in enumerate(zip(zstar_vals, far_vals)):
    ax_zstar.text(i - width / 2, z + 0.04, f"{z:.3f}",
                  ha="center", fontsize=7.5, fontweight="bold")
    ax_zstar2.text(i + width / 2, f + 0.005, f"{f:.2f}",
                   ha="center", fontsize=7.5, color="#555555")

# Φ⁻¹ 기준선
ax_zstar.axhline(1.645, color="gray", ls="--", lw=1.0, alpha=0.7)
ax_zstar.text(len(CALIBRATED) - 0.05, 1.66, "Φ⁻¹(0.95)=1.645\n(FAR=0.05)",
              fontsize=6.5, color="gray", ha="right")
ax_zstar.axhline(0.842, color="#AAAAAA", ls=":", lw=1.0, alpha=0.7)
ax_zstar.text(len(CALIBRATED) - 0.05, 0.86, "Φ⁻¹(0.80)=0.842\n(FAR=0.20)",
              fontsize=6.5, color="#AAAAAA", ha="right")

# 범례 통합
h1 = mpatches.Patch(color="gray", alpha=0.9, label=r"$\Phi^{-1}(1-\mathrm{FAR})$")
h2 = mpatches.Patch(color="gray", alpha=0.45, hatch="//", label="FAR")
ax_zstar.legend(handles=[h1, h2], fontsize=7.5, loc="upper right")

# ─────────────────────────────────────────────
# 8. BGM 미보정 안내
# ─────────────────────────────────────────────
for ax in [ax_mu, ax_sigma, ax_zstar]:
    ax.annotate("BGM: 미보정", xy=(1, 0), xycoords="axes fraction",
                xytext=(-2, 6), textcoords="offset points",
                fontsize=7, color=DOMAIN_COLORS["BGM"],
                ha="right", va="bottom", style="italic")

# ─────────────────────────────────────────────
# 9. 저장
# ─────────────────────────────────────────────
save(fig, "fig11_calibration_domain_compare.png")
print("\n=== 보정 파라미터 요약 ===")
print(f"{'Domain':<8} {'N':>8}  {'FAR':>5}  {'mu_null':>8}  {'sig_null':>8}  "
      f"{'Phi-inv':>9}  {'tau':>8}")
print("-" * 68)
for d in DOMAINS:
    c = CAL[d]
    if c is None:
        print(f"{d:<8} {'n/a':>8}  {'n/a':>5}  {'n/a':>8}  {'n/a':>8}  {'n/a':>9}  {'N/A':>8}")
    else:
        print(f"{d:<8} {c['N']:>8,}  {c['FAR']:>5.2f}  {c['mu']:>8.4f}  "
              f"{c['sigma']:>8.4f}  {c['z_star']:>11.4f}  {c['tau']:>8.4f}")
