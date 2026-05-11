"""fig11 — 도메인별 보정(Calibration) 파라미터 비교 시각화.

τ = μ_null + Φ⁻¹(1 − FAR) · σ_null

실측 데이터 출처:
  Data/embedded_DB/trichef_calibration.json  (2026-05-09 기준)
"""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator
from scipy.stats import norm

from _common import setup_style, save, DOMAIN_COLORS

RNG   = np.random.default_rng(42)
N_RUG = 150   # rug plot 샘플 수 (도메인당)

# ─────────────────────────────────────────────
# 1. 실측 보정 파라미터 (trichef_calibration.json, 2026-05-09)
# ─────────────────────────────────────────────
CAL = {
    "Doc": {
        "mu":     0.3001,
        "sigma":  0.0439,
        "tau":    0.3724,
        "FAR":    0.05,
        "N":      34718,
        "method": "crossmodal_v2_α=0.8",
        "capped": False,
    },
    "Img": {
        "mu":     0.2857,
        "sigma":  0.02567,
        "tau":    0.2992,
        "FAR":    0.30,
        "N":      2390,
        "method": "standard",
        "capped": False,
    },
    "Movie": {
        "mu":     0.2668,
        "sigma":  0.01931,
        "tau":    0.29853,
        "FAR":    0.05,
        "N":      46497,
        "method": "standard",
        "capped": False,
    },
    "Rec": {
        "mu":     0.8226,
        "sigma":  0.0533,
        "tau":    0.85,          # capped (theoretical: ~0.9103)
        "FAR":    0.05,
        "N":      11039,
        "method": "standard (τ capped)",
        "capped": True,
    },
    "BGM": None,   # 미보정
}

DOMAINS    = ["Doc", "Img", "Movie", "Rec", "BGM"]
CALIBRATED = [d for d in DOMAINS if CAL[d] is not None]

# 파생 값 계산
for d in CALIBRATED:
    c = CAL[d]
    c["one_minus_far"]   = 1.0 - c["FAR"]
    c["z_star"]          = norm.ppf(c["one_minus_far"])
    c["phi_z"]           = norm.cdf(c["z_star"])
    c["tau_check"]       = c["mu"] + c["z_star"] * c["sigma"]
    if c.get("capped"):
        c["tau_theoretical"] = c["tau_check"]

# ─────────────────────────────────────────────
# 2. 레이아웃
# ─────────────────────────────────────────────
setup_style()
fig = plt.figure(figsize=(18, 14))
fig.suptitle(
    "도메인별 Null 분포 보정 파라미터 비교\n"
    r"$\tau = \mu_{\mathrm{null}} + \Phi^{-1}(1-\mathrm{FAR})\cdot\sigma_{\mathrm{null}}$",
    fontsize=22, fontweight="bold", y=0.98,
)

gs = gridspec.GridSpec(
    3, 3,
    figure=fig,
    hspace=0.55, wspace=0.40,
    left=0.07, right=0.97, top=0.91, bottom=0.06,
)

ax_table  = fig.add_subplot(gs[0, :])
ax_dist   = fig.add_subplot(gs[1, :])
ax_mu     = fig.add_subplot(gs[2, 0])
ax_sigma  = fig.add_subplot(gs[2, 1])
ax_zstar  = fig.add_subplot(gs[2, 2])

# ─────────────────────────────────────────────
# 3. 표 (ax_table)
# ─────────────────────────────────────────────
ax_table.axis("off")

# 도메인별 실제 파일(인덱스 아이템) 수 — N_null 과 동일하나 명시적 표기
FILE_COUNTS = {
    "Doc":   34718,
    "Img":   2390,
    "Movie": 46497,
    "Rec":   11039,
    "BGM":   None,   # 미보정 — 파일 수 미기입
}

col_labels = [
    "Domain",
    "파일 수",
    "N",
    "Method",
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
    c  = CAL[d]
    fc = FILE_COUNTS[d]
    if c is None:
        rows.append([d, f"{fc:,}" if fc else "n/a", "n/a", "미보정",
                     "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a"])
    else:
        tau_str = f"{c['tau']:.4f}"
        if c.get("capped"):
            tau_str += " *"
        rows.append([
            d,
            f"{fc:,}" if fc else "n/a",
            f"{c['N']:,}",
            c["method"],
            tau_str,
            f"{c['mu']:.4f}",
            f"{c['sigma']:.4f}",
            f"{c['z_star']:.4f}",
            f"{c['phi_z']:.4f}",
            f"{c['one_minus_far']:.2f}",
            f"{c['FAR']:.2f}",
        ])

# 열 너비: Method 넓게, N·파일수 좁게 (합≈1.0)
# Domain  파일수  N    Method  τ     μ     σ     Φ⁻¹   Φ(z*) 1-FAR FAR
COL_W = [0.07,  0.06, 0.05,  0.20, 0.07, 0.08, 0.08, 0.10, 0.08, 0.08, 0.06]

tbl = ax_table.table(
    cellText=rows,
    colLabels=col_labels,
    colWidths=COL_W,
    cellLoc="center",
    loc="center",
    bbox=[0, 0, 1, 1],
)
tbl.auto_set_font_size(False)
tbl.set_fontsize(14)

# 헤더 스타일
for j in range(len(col_labels)):
    tbl[(0, j)].set_facecolor("#2C3E50")
    tbl[(0, j)].set_text_props(color="white", fontweight="bold", fontsize=14)

# 행별 색상 + 숫자 굵게
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
            tbl[(i, j)].set_text_props(color="#888888", style="italic", fontsize=14)
        else:
            tbl[(i, j)].set_text_props(fontweight="bold", fontsize=14)

# τ 열(인덱스 3) 강조 / FAR 열(인덱스 9) 강조
TAU_COL = 4
FAR_COL = 10
for i in range(1, len(DOMAINS) + 1):
    tbl[(i, TAU_COL)].set_text_props(fontweight="bold", color="#B71C1C", fontsize=14)
    if CAL[DOMAINS[i - 1]] is not None:
        tbl[(i, FAR_COL)].set_text_props(fontweight="bold", fontsize=14)

# * 각주
rec_tau_th = CAL["Rec"]["tau_theoretical"]
ax_table.text(
    0.0, -0.08,
    f"*  Rec: τ capped at 0.85  "
    f"(이론값 τ = μ + Φ⁻¹(0.95)·σ = {rec_tau_th:.4f},  실제 스코어 분포 상한으로 강제 제한)",
    transform=ax_table.transAxes,
    fontsize=11, fontweight="bold", color="#B71C1C", va="top",
)

ax_table.set_title("표 1. 도메인별 보정 파라미터 요약", fontsize=14,
                   fontweight="bold", pad=4, loc="left")

# ─────────────────────────────────────────────
# 4. Null 분포 곡선 + rug plot (ax_dist)
# ─────────────────────────────────────────────
ax_dist.set_title(
    "그림 A. 도메인별 Null Score 분포와 보정 임계값 τ"
    "  (peak-normalized density, 형태 비교용)",
    fontsize=14, fontweight="bold", loc="left",
)
ax_dist.set_xlabel("Hermitian 스코어", fontsize=13, fontweight="bold")
ax_dist.set_ylabel("정규화 밀도  (peak = 1, 형태 비교용)", fontsize=13, fontweight="bold")
ax_dist.tick_params(axis="both", labelsize=12)

# τ 텍스트 위치: x=0.45 근방에 집결 (절대 data 좌표), y는 겹침 방지용 분산
TAU_POSITIONS = {
    "Img":   (0.45, 1.04),   # 가장 위
    "Movie": (0.45, 0.80),
    "Rec":   (0.86, 1.10),   # Rec: 우측 상단
    "Doc":   (0.45, 0.56),   # 가장 아래
}

legend_handles = []
rug_y = -0.07

for d in CALIBRATED:
    c   = CAL[d]
    col = DOMAIN_COLORS[d]

    x      = np.linspace(c["mu"] - 4.5 * c["sigma"], c["mu"] + 4.5 * c["sigma"], 500)
    y_raw  = norm.pdf(x, c["mu"], c["sigma"])
    y_peak = norm.pdf(c["mu"],    c["mu"], c["sigma"])
    y      = y_raw / y_peak

    ax_dist.plot(x, y, color=col, lw=2.5)

    # μ 수직선 (점선)
    ax_dist.axvline(c["mu"], color=col, lw=1.2, ls=":", alpha=0.6)

    # τ 수직선 — capped는 dash-dot
    ls_tau = "-." if c.get("capped") else "--"
    ax_dist.axvline(c["tau"], color=col, lw=2.0, ls=ls_tau, alpha=0.9)

    # τ 오른쪽 FAR 음영
    x_fill = np.linspace(c["tau"], c["mu"] + 4.5 * c["sigma"], 200)
    y_fill = norm.pdf(x_fill, c["mu"], c["sigma"]) / y_peak
    ax_dist.fill_between(x_fill, y_fill, alpha=0.12, color=col)

    # τ 레이블 — x≈0.45 고정, 화살표로 τ 수직선 가리킴
    y_at_tau = norm.pdf(c["tau"], c["mu"], c["sigma"]) / y_peak
    xt, yt   = TAU_POSITIONS[d]
    tau_label = f"τ={c['tau']:.3f}"
    if c.get("capped"):
        tau_label += " *"
    tau_label += f"\n({d})"
    ax_dist.annotate(
        tau_label,
        xy=(c["tau"], y_at_tau),
        xytext=(xt, yt),
        fontsize=11, fontweight="bold", color=col,
        arrowprops=dict(arrowstyle="->", color=col, lw=1.0),
    )

    # rug plot: x축 아래 막대기 심벌
    samples = RNG.normal(c["mu"], c["sigma"], N_RUG)
    ax_dist.plot(
        samples, np.full_like(samples, rug_y),
        "|", color=col, alpha=0.45, markersize=8,
        markeredgewidth=1.0, clip_on=False,
    )

    # 동일 샘플의 가우시안 곡선 위 위치 — 빈 원형 심벌 (hollow circle)
    y_circles = norm.pdf(samples, c["mu"], c["sigma"]) / y_peak
    ax_dist.scatter(
        samples, y_circles,
        s=50, facecolors="none", edgecolors=col,
        alpha=0.6, linewidths=1.2, zorder=2,
    )

    legend_handles.append(
        Line2D([0], [0], color=col, lw=2.5,
               label=f"{d}  μ={c['mu']:.4f}  σ={c['sigma']:.4f}")
    )

# Rec 이론값 τ_th 수직선 (capped 전 이론값)
_rec_th = CAL["Rec"]["tau_theoretical"]
_rec_col = DOMAIN_COLORS["Rec"]
ax_dist.axvline(_rec_th, color=_rec_col, lw=1.4, ls=(0, (3, 2, 1, 2)), alpha=0.65)
ax_dist.text(
    0.91, 0.00,
    f"τ_th={_rec_th:.4f}\n(Rec 이론값)",
    fontsize=10, fontweight="bold", color=_rec_col, alpha=0.80,
    ha="left", va="bottom",
)

legend_handles += [
    Line2D([0], [0], color="gray", lw=2.0, ls="--",  label="τ (임계값)"),
    Line2D([0], [0], color="gray", lw=2.0, ls="-.",  label="τ (capped *)"),
    Line2D([0], [0], color="gray", lw=1.4, ls=(0, (3, 2, 1, 2)), alpha=0.65, label="τ_th (이론값, Rec)"),
    Line2D([0], [0], color="gray", lw=1.2, ls=":",   label="μ_null"),
    Line2D([0], [0], marker="|",   color="gray", lw=0,
           markersize=9, alpha=0.6, label="null score 샘플 (rug)"),
    Line2D([0], [0], marker="o",   color="gray", lw=0,
           markersize=7, markerfacecolor="none", markeredgewidth=0.8,
           alpha=0.6, label="null score 샘플 (density 위)"),
]
# 범례: 우측 상단
ax_dist.legend(handles=legend_handles, fontsize=11, loc="upper right", ncol=1)
ax_dist.set_ylim(bottom=-0.12, top=1.22)
ax_dist.set_xlim(0.10, 1.10)
ax_dist.xaxis.set_major_locator(MultipleLocator(0.1))
ax_dist.xaxis.set_minor_locator(MultipleLocator(0.05))
ax_dist.tick_params(axis="x", which="minor", length=4, color="gray")

# ─────────────────────────────────────────────
# 5. 막대 그래프 — μ_null (ax_mu)
# ─────────────────────────────────────────────
ax_mu.set_title("그림 B. μ_null 비교", fontsize=13, fontweight="bold", loc="left")
ax_mu.set_ylabel("μ_null", fontsize=12, fontweight="bold")
ax_mu.tick_params(axis="both", labelsize=11)

x_pos      = np.arange(len(CALIBRATED))
mu_vals    = [CAL[d]["mu"]    for d in CALIBRATED]
sigma_vals = [CAL[d]["sigma"] for d in CALIBRATED]

bars = ax_mu.bar(x_pos, mu_vals,
                 color=[DOMAIN_COLORS[d] for d in CALIBRATED],
                 edgecolor="white", linewidth=0.8, width=0.55)
ax_mu.set_xticks(x_pos)
ax_mu.set_xticklabels(CALIBRATED, fontsize=12, fontweight="bold")
for bar, v in zip(bars, mu_vals):
    ax_mu.text(bar.get_x() + bar.get_width() / 2, v + 0.062,
               f"{v:.4f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
ax_mu.set_ylim(0, 1.08)
ax_mu.axhline(0.5, color="gray", ls="--", lw=0.9, alpha=0.5)
# 세로축 바로 오른쪽: transAxes x=0, y=0.5/ylim 비율
ax_mu.text(0.01, 0.5 / 1.08 + 0.01, "0.5 기준선",
           transform=ax_mu.transAxes,
           fontsize=10, fontweight="bold", color="gray",
           ha="left", va="bottom")

ax_mu.errorbar(x_pos, mu_vals, yerr=sigma_vals,
               fmt="none", ecolor="black", elinewidth=1.3, capsize=5)

# ─────────────────────────────────────────────
# 6. 막대 그래프 — σ_null (ax_sigma)
# ─────────────────────────────────────────────
ax_sigma.set_title("그림 C. σ_null 비교", fontsize=13, fontweight="bold", loc="left")
ax_sigma.set_ylabel("σ_null", fontsize=12, fontweight="bold")
ax_sigma.tick_params(axis="both", labelsize=11)

bars2 = ax_sigma.bar(x_pos, sigma_vals,
                     color=[DOMAIN_COLORS[d] for d in CALIBRATED],
                     edgecolor="white", linewidth=0.8, width=0.55)
ax_sigma.set_xticks(x_pos)
ax_sigma.set_xticklabels(CALIBRATED, fontsize=12, fontweight="bold")
for bar, v in zip(bars2, sigma_vals):
    ax_sigma.text(bar.get_x() + bar.get_width() / 2, v + 0.001,
                  f"{v:.4f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
ax_sigma.set_ylim(0, max(sigma_vals) * 1.38)

widest_idx = int(np.argmax(sigma_vals))
widest     = CALIBRATED[widest_idx]
ax_sigma.annotate(
    "최대 분산\n→ τ가 μ에서\n  멀어짐",
    xy=(widest_idx, max(sigma_vals)),
    xytext=(widest_idx - 0.7, 0.06),
    fontsize=10, fontweight="bold", color=DOMAIN_COLORS[widest],
    ha="right",
    arrowprops=dict(arrowstyle="->", color=DOMAIN_COLORS[widest], lw=1.0),
)

# ─────────────────────────────────────────────
# 7. Φ⁻¹ & FAR 이중 막대 (ax_zstar)
# ─────────────────────────────────────────────
ax_zstar.set_title(r"그림 D. $\Phi^{-1}(1-\mathrm{FAR})$ & FAR 비교",
                   fontsize=13, fontweight="bold", loc="left")
ax_zstar.tick_params(axis="both", labelsize=11)

zstar_vals = [CAL[d]["z_star"] for d in CALIBRATED]
far_vals   = [CAL[d]["FAR"]    for d in CALIBRATED]

width = 0.35
ax_zstar.bar(x_pos - width / 2, zstar_vals,
             width=width,
             color=[DOMAIN_COLORS[d] for d in CALIBRATED],
             edgecolor="white", linewidth=0.8, alpha=0.9)

ax_zstar2 = ax_zstar.twinx()
ax_zstar2.bar(x_pos + width / 2, far_vals,
              width=width,
              color=[DOMAIN_COLORS[d] for d in CALIBRATED],
              edgecolor="white", linewidth=0.8, alpha=0.45, hatch="//")
ax_zstar2.set_ylabel("FAR", fontsize=12, fontweight="bold", color="#555555")
ax_zstar2.set_ylim(0, 0.55)
ax_zstar2.tick_params(axis="y", labelsize=10)

ax_zstar.set_xticks(x_pos)
ax_zstar.set_xticklabels(CALIBRATED, fontsize=12, fontweight="bold")
ax_zstar.set_ylabel(r"$\Phi^{-1}(1-\mathrm{FAR})$", fontsize=12, fontweight="bold")
ax_zstar.set_ylim(0, 2.5)
ax_zstar.yaxis.set_major_locator(MultipleLocator(0.5))

for i, (z, f) in enumerate(zip(zstar_vals, far_vals)):
    ax_zstar.text(i - width / 2, z + 0.05, f"{z:.3f}",
                  ha="center", fontsize=11, fontweight="bold")
    ax_zstar2.text(i + width / 2, f + 0.007, f"{f:.2f}",
                   ha="center", fontsize=11, fontweight="bold", color="#555555")

ax_zstar.axhline(1.645, color="gray", ls="--", lw=1.0, alpha=0.7)
ax_zstar.text(len(CALIBRATED) - 0.05, 1.67,
              "Φ⁻¹(0.95)=1.645\n(FAR=0.05)",
              fontsize=10, fontweight="bold", color="gray", ha="right")
ax_zstar.axhline(0.524, color="#AAAAAA", ls=":", lw=1.0, alpha=0.7)
ax_zstar.text(len(CALIBRATED) - 0.05, 0.545,
              "Φ⁻¹(0.70)=0.524\n(FAR=0.30)",
              fontsize=10, fontweight="bold", color="#AAAAAA", ha="right")

h1 = mpatches.Patch(color="gray", alpha=0.9,  label=r"$\Phi^{-1}(1-\mathrm{FAR})$")
h2 = mpatches.Patch(color="gray", alpha=0.45, hatch="//", label="FAR")
ax_zstar.legend(handles=[h1, h2], fontsize=10, loc="upper left")


# ─────────────────────────────────────────────
# 9. 저장
# ─────────────────────────────────────────────
save(fig, "fig11_calibration_domain_compare.png")

print("\n=== 보정 파라미터 요약 ===")
print(f"{'Domain':<8} {'N':>8}  {'FAR':>5}  {'mu_null':>8}  {'sig_null':>8}  "
      f"{'Phi-inv':>9}  {'tau':>8}  {'note':>20}")
print("-" * 84)
for d in DOMAINS:
    c = CAL[d]
    if c is None:
        print(f"{d:<8} {'n/a':>8}  {'n/a':>5}  {'n/a':>8}  {'n/a':>8}  "
              f"{'n/a':>9}  {'n/a':>8}  {'미보정':>20}")
    else:
        note = f"capped (th={c.get('tau_theoretical', 0):.4f})" if c.get("capped") else ""
        print(f"{d:<8} {c['N']:>8,}  {c['FAR']:>5.2f}  {c['mu']:>8.4f}  "
              f"{c['sigma']:>8.4f}  {c['z_star']:>9.4f}  {c['tau']:>8.4f}  {note:>20}")
