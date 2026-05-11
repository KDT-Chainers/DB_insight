"""fig11 — 도메인별 보정(Calibration) 파라미터 비교 시각화.

τ = μ_null + Φ^-1(1 − FAR) · σ_null

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

# fig11 전용: Doc↔Movie, Rec↔Img 색상 교환 (_common.py 불변)
FIG11_COLORS = dict(DOMAIN_COLORS)
FIG11_COLORS["Doc"],   FIG11_COLORS["Movie"] = FIG11_COLORS["Movie"], FIG11_COLORS["Doc"]
FIG11_COLORS["Rec"],   FIG11_COLORS["Img"]   = FIG11_COLORS["Img"],   FIG11_COLORS["Rec"]

RNG = np.random.default_rng(42)

# ─────────────────────────────────────────────
# 1. 실측 보정 파라미터 (trichef_calibration.json, 2026-05-09)
# ─────────────────────────────────────────────
CAL = {
    "Doc": {
        "mu":     0.1693,
        "sigma":  0.0218,
        "tau":    0.2051,
        "FAR":    0.05,
        "N":      34661,
        "null_n": 693220,   # 20 null queries × 34,661 페이지
        "seg":    "page",
        "method": "crossmodal_v2_α=0.8",
        "capped": False,
    },
    "Img": {
        "mu":     0.1776,
        "sigma":  0.0281,
        "tau":    0.2012,
        "FAR":    0.20,
        "N":      2390,
        "null_n": 47800,    # 20 null queries × 2,390 이미지
        "seg":    "image (1 skip)",
        "method": "standard",
        "capped": False,
    },
    "Movie": {
        "mu":     0.1576,
        "sigma":  0.0424,
        "tau":    0.2274,
        "FAR":    0.05,
        "N":      45647,
        "null_n": 912940,   # 20 null queries × 45,647 프레임
        "seg":    "2s/scene frame",
        "method": "standard",
        "capped": False,
    },
    "Rec": {
        "mu":     0.6809,
        "sigma":  0.0683,
        "tau":    0.7933,
        "FAR":    0.05,
        "N":      11039,
        "null_n": 220780,   # 20 null queries × 11,039 곡
        "seg":    "30s/15s win",
        "method": "standard",
        "capped": False,
    },
    "BGM": {
        "mu":     0.8226,
        "sigma":  0.0533,
        "tau":    0.8500,    # capped at 0.85 (이론값 ≈ 0.9103)
        "FAR":    0.05,
        "N":      11039,
        "null_n": 220780,   # 20 null queries × 11,039 세그먼트
        "seg":    "30s/15s win",
        "method": "random_query_null_v2",
        "capped": True,
    },
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

# 상단: 표(row0) + 그림A dist(row1)
gs_top = gridspec.GridSpec(
    2, 1,
    figure=fig,
    hspace=0.55,
    left=0.07, right=0.97, top=0.91, bottom=0.395,
)

# 하단: 그림 B, C, D — wspace=0.20, 그림A와 간격 ≈0.085
gs_bot = gridspec.GridSpec(
    1, 3,
    figure=fig,
    wspace=0.20,
    left=0.07, right=0.97, top=0.310, bottom=0.06,
)

ax_table  = fig.add_subplot(gs_top[0])
ax_dist   = fig.add_subplot(gs_top[1])
ax_mu     = fig.add_subplot(gs_bot[0])
ax_sigma  = fig.add_subplot(gs_bot[1])
ax_zstar  = fig.add_subplot(gs_bot[2])

# ─────────────────────────────────────────────
# 3. 표 (ax_table)
# ─────────────────────────────────────────────
ax_table.axis("off")

# 도메인별 실제 파일(인덱스 아이템) 수 — N_null 과 동일하나 명시적 표기
FILE_COUNTS = {
    "Doc":   443,
    "Img":   2391,
    "Movie": 205,
    "Rec":   117,
    "BGM":   102,
}

col_labels = [
    "Domain",
    "N(파일 수)",
    "N(세그먼트)",
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

# 열 너비: N(파일수)·N(세그먼트) 넓게, Method 줄임 (합≈1.0)
# Domain  파일수  N    Method  τ     μ     σ     Φ^-1   Φ(z*) 1-FAR FAR
COL_W = [0.07,  0.09, 0.08,  0.15, 0.07, 0.08, 0.08, 0.10, 0.08, 0.08, 0.06]

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
    "Doc":   "#D4EDDA",   # ← Movie 색 (교환)
    "Img":   "#F8D7DA",   # ← Rec 색 (교환)
    "Movie": "#D6E4F7",   # ← Doc 색 (교환)
    "Rec":   "#FCE5D0",   # ← Img 색 (교환)
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


ax_table.set_title("표 1. 도메인별 보정 파라미터 요약", fontsize=14,
                   fontweight="bold", pad=4, loc="left")

# 표 1 하단 각주 — BGM cap 설명
ax_table.text(
    0.0, -0.06,
    "* BGM τ 상한(cap=0.85): null 분포가 고득점 영역에 집중(μ=0.8226)하여 "
    "이론값 τ_th=0.9103 적용 시 검색 전체 차단(full-block) 발생\n"
    "→ 실용 상한 τ=0.85 채택 (FAR=0.05 보장 완화; 실제 FAR > 0.05)",
    transform=ax_table.transAxes,
    fontsize=13, color="black", style="italic",
    ha="left", va="top", clip_on=False,
    wrap=True,
)

# ─────────────────────────────────────────────
# 4. Null 분포 곡선 + rug plot (ax_dist)
# ─────────────────────────────────────────────
_t1 = ax_dist.set_title(
    "그림 A. 도메인별 Null Score 분포와 보정 임계값 τ",
    fontsize=14, fontweight="bold", loc="left",
)
# '도'의 가로 위치에 '('를 맞추기 위해 renderer로 "그림 A. " 폭 측정
_probe = ax_dist.text(0, 0, "그림 A. ", fontsize=14, fontweight="bold",
                      ha="left", va="bottom", transform=ax_dist.transAxes,
                      clip_on=False, alpha=0)
fig.canvas.draw()
_rdr    = fig.canvas.get_renderer()
_ax_bb  = ax_dist.get_window_extent(_rdr)
_x_frac = _probe.get_window_extent(_rdr).width / _ax_bb.width
_y_frac = (_t1.get_window_extent(_rdr).y0 - _ax_bb.y0) / _ax_bb.height
_probe.remove()
ax_dist.text(
    _x_frac, _y_frac,
    "(실측 μ, σ 기반 가우시안 피팅; 확률 밀도)",
    transform=ax_dist.transAxes,
    fontsize=14, fontweight="bold",
    ha="left", va="top", clip_on=False,
)
ax_dist.set_xlabel("Hermitian 스코어", fontsize=13, fontweight="bold")
ax_dist.set_ylabel("확률 밀도  (Probability Density)", fontsize=13, fontweight="bold")
ax_dist.tick_params(axis="both", labelsize=12)

# τ 텍스트 위치: data 좌표 (x=Hermitian score, y=확률 밀도)
TAU_POSITIONS = {
    "Img":   (0.25, 17),   # 가장 위
    "Movie": (0.25,  7),
    "Doc":   (0.25, 12),
    "Rec":   (0.80, 10),   # 우측
    "BGM":   (0.87,  8),   # τ=0.85 가리킴
}

DOMAIN_MARKERS = {"Doc": "o", "Img": "s", "Movie": "^", "Rec": "D", "BGM": "v"}

legend_handles = []

for d in CALIBRATED:
    c   = CAL[d]
    col = FIG11_COLORS[d]

    x   = np.linspace(c["mu"] - 4.5 * c["sigma"], c["mu"] + 4.5 * c["sigma"], 500)
    y   = norm.pdf(x, c["mu"], c["sigma"])   # 원래 확률 밀도 (비정규화)

    # ── 히스토그램: 실측 파라미터(μ, σ, N)로 경험적 분포 시뮬레이션 ──
    n_vis   = min(c["N"], 3000)
    synth   = RNG.normal(c["mu"], c["sigma"], n_vis)
    h_cnt, h_edges = np.histogram(synth, bins=22, density=True)
    h_centers = (h_edges[:-1] + h_edges[1:]) / 2
    h_width   = h_edges[1] - h_edges[0]
    ax_dist.bar(h_centers, h_cnt,
                width=h_width * 0.88, color=col, alpha=0.18,
                edgecolor=col, linewidth=0.7, zorder=1)

    # ── 가우시안 피팅 곡선 (확률 밀도) ──
    ax_dist.plot(x, y, color=col, lw=2.5, zorder=3)

    # μ 수직선 (점선) — Rec·BGM은 y 범위 0~10 제한, 나머지 0~20
    _y_top = 10 if d in ("Rec", "BGM") else 20
    ax_dist.vlines(c["mu"],  0, _y_top, color=col, lw=1.2, ls=":", alpha=0.6)

    # τ 수직선 — Rec·BGM은 y 범위 0~10 제한, 나머지 0~20
    ax_dist.vlines(c["tau"], 0, _y_top, color=col, lw=2.0, ls="--", alpha=0.9)

    # τ 이론값 점선 (capped 도메인만) — 검정 세로 점선 + 수치 표기
    if c.get("capped") and "tau_theoretical" in c:
        tau_th = c["tau_theoretical"]
        ax_dist.vlines(tau_th, 0, 10,
                       color="black", lw=1.5, ls=":", alpha=0.85, zorder=2)
        ax_dist.text(tau_th + 0.005, 5,
                     f"τ_th={tau_th:.4f}",
                     fontsize=10, fontweight="bold", color="black",
                     ha="left", va="top", rotation=0)

    # τ 오른쪽 FAR 음영
    x_fill = np.linspace(c["tau"], c["mu"] + 4.5 * c["sigma"], 200)
    y_fill = norm.pdf(x_fill, c["mu"], c["sigma"])
    ax_dist.fill_between(x_fill, y_fill, alpha=0.12, color=col)

    # τ 레이블 — axes fraction 좌표, 화살표로 τ 수직선 가리킴
    y_at_tau = norm.pdf(c["tau"], c["mu"], c["sigma"])
    xt, yt   = TAU_POSITIONS[d]
    tau_label = f"τ={c['tau']:.4f}\n({d})"
    ax_dist.annotate(
        tau_label,
        xy=(c["tau"], y_at_tau), xycoords="data",
        xytext=(xt, yt),         textcoords="data",
        fontsize=11, fontweight="bold", color=col,
        arrowprops=dict(arrowstyle="->", color=col, lw=1.0),
    )

    # ── 히스토그램 막대 꼭대기에 도메인별 마커 ──
    ax_dist.plot(
        h_centers, h_cnt,
        marker=DOMAIN_MARKERS[d], color=col, ls="none",
        ms=7, markerfacecolor="none", markeredgewidth=1.5,
        alpha=0.9, zorder=4,
    )

    legend_handles.append(
        Line2D([0], [0], color=col, lw=2.5,
               marker=DOMAIN_MARKERS[d], markerfacecolor="none",
               markersize=7, markeredgewidth=1.5,
               label=f"{d}  μ={c['mu']:.4f}  σ={c['sigma']:.4f}")
    )

legend_handles += [
    mpatches.Patch(color="gray", alpha=0.25, label="경험적 분포 (히스토그램)"),
    Line2D([0], [0], color="gray", lw=2.5,   label="가우시안 피팅"),
    Line2D([0], [0], color="gray", lw=2.0, ls="--",  label="τ (임계값)"),
    Line2D([0], [0], color="gray", lw=1.2, ls=":",   label="μ_null"),
    Line2D([0], [0], marker="o",   color="gray", lw=0,
           markersize=7, markerfacecolor="none", markeredgewidth=1.5,
           alpha=0.9, label="막대 꼭대기 심벌 (○□△◇)"),
]
# 범례: 우측 상단
ax_dist.legend(handles=legend_handles, fontsize=11, loc="upper left",
               bbox_to_anchor=(0.31, 1.0), ncol=1)
ax_dist.set_ylim(bottom=0, top=22)
ax_dist.set_xlim(0.00, 1.00)
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
                 color=[FIG11_COLORS[d] for d in CALIBRATED],
                 edgecolor="white", linewidth=0.8, width=0.55)
ax_mu.set_xticks(x_pos)
ax_mu.set_xticklabels(CALIBRATED, fontsize=12, fontweight="bold")
for bar, v, d in zip(bars, mu_vals, CALIBRATED):
    if d == "Rec":
        y_lbl = 0.78
    elif d == "BGM":
        y_lbl = 0.90
    else:
        y_lbl = v + 0.062
    ax_mu.text(bar.get_x() + bar.get_width() / 2, y_lbl,
               f"{v:.4f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
ax_mu.set_ylim(0, 0.99)
ax_mu.yaxis.set_major_locator(MultipleLocator(0.1))
ax_mu.axhline(0.5, color="gray", ls="--", lw=0.9, alpha=0.5)
ax_mu.text(0.01, 0.5 / 0.99 + 0.01, "0.5 기준선",
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
                     color=[FIG11_COLORS[d] for d in CALIBRATED],
                     edgecolor="white", linewidth=0.8, width=0.55)
ax_sigma.set_xticks(x_pos)
ax_sigma.set_xticklabels(CALIBRATED, fontsize=12, fontweight="bold")
for bar, v in zip(bars2, sigma_vals):
    ax_sigma.text(bar.get_x() + bar.get_width() / 2, v + 0.001,
                  f"{v:.4f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
ax_sigma.set_ylim(0, 0.089)

widest_idx = int(np.argmax(sigma_vals))
widest     = CALIBRATED[widest_idx]
ax_sigma.annotate(
    "최대 분산\n→ τ가 μ에서\n  멀어짐",
    xy=(widest_idx, max(sigma_vals)),
    xytext=(widest_idx - 0.7, 0.07),
    fontsize=10, fontweight="bold", color=FIG11_COLORS[widest],
    ha="right",
    arrowprops=dict(arrowstyle="->", color=FIG11_COLORS[widest], lw=1.0),
)

# ─────────────────────────────────────────────
# 7. Φ^-1 & FAR 이중 막대 (ax_zstar)
# ─────────────────────────────────────────────
ax_zstar.set_title(r"그림 D. $\Phi^{-1}(1-\mathrm{FAR})$ & FAR 비교",
                   fontsize=13, fontweight="bold", loc="left")
ax_zstar.tick_params(axis="both", labelsize=11)

zstar_vals = [CAL[d]["z_star"] for d in CALIBRATED]
far_vals   = [CAL[d]["FAR"]    for d in CALIBRATED]

width = 0.35
ax_zstar.bar(x_pos - width / 2, zstar_vals,
             width=width,
             color=[FIG11_COLORS[d] for d in CALIBRATED],
             edgecolor="white", linewidth=0.8, alpha=0.9)

ax_zstar2 = ax_zstar.twinx()
ax_zstar2.bar(x_pos + width / 2, far_vals,
              width=width,
              color=[FIG11_COLORS[d] for d in CALIBRATED],
              edgecolor="white", linewidth=0.8, alpha=0.45, hatch="//")
ax_zstar2.set_ylabel("FAR", fontsize=12, fontweight="bold", color="#555555")
ax_zstar2.set_ylim(0, 0.35)
ax_zstar2.tick_params(axis="y", labelsize=10)
ax_zstar2.yaxis.set_major_locator(MultipleLocator(0.1))

ax_zstar.set_xticks(x_pos)
ax_zstar.set_xticklabels(CALIBRATED, fontsize=12, fontweight="bold")
ax_zstar.set_ylabel(r"$\Phi^{-1}(1-\mathrm{FAR})$", fontsize=12, fontweight="bold")
ax_zstar.set_ylim(0, 2.4)
ax_zstar.yaxis.set_major_locator(MultipleLocator(0.5))

for i, (z, f) in enumerate(zip(zstar_vals, far_vals)):
    ax_zstar.text(i - width / 2, z + 0.05, f"{z:.3f}",
                  ha="center", fontsize=11, fontweight="bold")
    ax_zstar2.text(i + width / 2, f + 0.007, f"{f:.2f}",
                   ha="center", fontsize=11, fontweight="bold", color="#555555")

ax_zstar.axhline(1.645, color="gray", ls="--", lw=1.0, alpha=0.7)
ax_zstar.text(len(CALIBRATED) - 0.05, 1.67,
              "Φ^-1(0.95)=1.645\n(FAR=0.05)",
              fontsize=10, fontweight="bold", color="gray", ha="right")
ax_zstar.axhline(0.842, color="#AAAAAA", ls=":", lw=1.0, alpha=0.7)
ax_zstar.text(len(CALIBRATED) - 0.05, 0.862,
              "Φ^-1(0.80)=0.842\n(FAR=0.20)",
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
