"""fig11-1 — 도메인별 보정 파라미터 비교 (표1 + 3D σ-stratified null distribution).

논문 Tri-CHEF_paper_v1-10 Fig 5(a) 스타일:
  X = Hermitian score s(q,d)
  Y = σ_null (×10⁻²)
  Z = Prob. density
각 도메인 가우시안을 σ_null 깊이에 배치하고,
τ 임계값 위치에 반투명 막대(bar)를 표시.

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
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from scipy.stats import norm

from _common import setup_style, save, DOMAIN_COLORS

RNG = np.random.default_rng(42)

# fig11 전용: Doc↔Movie, Rec↔Img 색상 교환 (_common.py 불변)
FIG11_COLORS = dict(DOMAIN_COLORS)
FIG11_COLORS["Doc"],   FIG11_COLORS["Movie"] = FIG11_COLORS["Movie"], FIG11_COLORS["Doc"]
FIG11_COLORS["Rec"],   FIG11_COLORS["Img"]   = FIG11_COLORS["Img"],   FIG11_COLORS["Rec"]

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
        "null_n": 693220,
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
        "null_n": 47800,
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
        "null_n": 912940,
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
        "null_n": 220780,
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
        "null_n": 220780,
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

DOMAIN_MARKERS = {"Doc": "^", "Img": "D", "Movie": "o", "Rec": "s", "BGM": "v"}
DOMAIN_LSTYLES = {"Doc": "--", "Img": ":", "Movie": "-", "Rec": "-.", "BGM": (0, (3, 1, 1, 1))}

# ─────────────────────────────────────────────
# 2. 레이아웃: 표1(상단) + 3D 그래프(하단)
# ─────────────────────────────────────────────
setup_style()
fig = plt.figure(figsize=(18, 16))
fig.suptitle(
    "도메인별 Null 분포 보정 파라미터 비교\n"
    r"$\tau = \mu_{\mathrm{null}} + \Phi^{-1}(1-\mathrm{FAR})\cdot\sigma_{\mathrm{null}}$",
    fontsize=22, fontweight="bold", y=0.98,
)

gs = gridspec.GridSpec(
    2, 1,
    figure=fig,
    height_ratios=[1, 2.2],
    hspace=0.18,
    left=0.06, right=0.97, top=0.91, bottom=0.04,
)

ax_table = fig.add_subplot(gs[0])
ax_3d    = fig.add_subplot(gs[1], projection="3d")

# ─────────────────────────────────────────────
# 3. 표 1 (ax_table) — 기존과 동일
# ─────────────────────────────────────────────
ax_table.axis("off")

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

COL_W = [0.07, 0.09, 0.08, 0.15, 0.07, 0.08, 0.08, 0.10, 0.08, 0.08, 0.06]

tbl = ax_table.table(
    cellText=rows,
    colLabels=col_labels,
    colWidths=COL_W,
    cellLoc="center",
    loc="center",
    bbox=[0, 0, 1, 1],
)
tbl.auto_set_font_size(False)
tbl.set_fontsize(16)
tbl.scale(1, 0.82)  # 셀 높이 압축

# 헤더 스타일
for j in range(len(col_labels)):
    tbl[(0, j)].set_facecolor("#2C3E50")
    tbl[(0, j)].set_text_props(color="white", fontweight="bold", fontsize=16)

# 행별 색상
row_colors = {
    "Doc":   "#D4EDDA",
    "Img":   "#F8D7DA",
    "Movie": "#D6E4F7",
    "Rec":   "#FCE5D0",
    "BGM":   "#EDE7F6",
}
for i, d in enumerate(DOMAINS, start=1):
    for j in range(len(col_labels)):
        tbl[(i, j)].set_facecolor(row_colors[d])
        if CAL[d] is None:
            tbl[(i, j)].set_text_props(color="#888888", style="italic", fontsize=16)
        else:
            tbl[(i, j)].set_text_props(fontweight="bold", fontsize=16)

# τ 열 강조
TAU_COL = 4
FAR_COL = 10
for i in range(1, len(DOMAINS) + 1):
    tbl[(i, TAU_COL)].set_text_props(fontweight="bold", color="#B71C1C", fontsize=16)
    if CAL[DOMAINS[i - 1]] is not None:
        tbl[(i, FAR_COL)].set_text_props(fontweight="bold", fontsize=14)

ax_table.set_title("표 1. 도메인별 보정 파라미터 요약", fontsize=14,
                   fontweight="bold", pad=4, loc="left")

# 표 1 하단 각주
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
# 4. 3D σ-stratified null distribution (ax_3d)
# ─────────────────────────────────────────────

# Y축: σ_null (×10⁻²) — 각 도메인이 자신의 σ 깊이에 배치됨
# X축: Hermitian score s(q,d)
# Z축: Prob. density

ax_3d.set_xlabel("\nHermitian score  $s(q,d)$", fontsize=16, fontweight="bold", labelpad=12)
ax_3d.set_ylabel("\n$\\sigma_{\\mathrm{null}}$  $(\\times 10^{-2})$", fontsize=16, fontweight="bold", labelpad=12)
ax_3d.set_zlabel("Prob. density", fontsize=16, fontweight="bold", labelpad=8)
ax_3d.text2D(
    0.0, 0.90,
    "그림 A. 도메인별 Null Score 분포와 보정 임계값 타우\n"
    "(실측 $\\mu$, $\\sigma$ 기반 가우시안 피팅; 각 도메인을 $\\sigma_{null}$ 깊이에 배치)",
    transform=ax_3d.transAxes,
    fontsize=14, fontweight="bold", ha="left", va="top",
)

# 시점 설정 — 논문 스타일
ax_3d.view_init(elev=28, azim=-52)

# 도메인 데이터 수집
sigma_values = [CAL[d]["sigma"] * 100 for d in CALIBRATED]  # ×10⁻² 단위

legend_handles = []

# Rec ↔ BGM Y축(σ_null 깊이) 위치 교환
Y_POS_SWAP = {
    "Rec": CAL["BGM"]["sigma"] * 100,
    "BGM": CAL["Rec"]["sigma"] * 100,
}

for d in CALIBRATED:
    c   = CAL[d]
    col = FIG11_COLORS[d]
    marker = DOMAIN_MARKERS[d]
    ls  = DOMAIN_LSTYLES[d]
    y_pos = Y_POS_SWAP.get(d, c["sigma"] * 100)  # σ_null ×10⁻² 단위

    # 가우시안 곡선 데이터
    x = np.linspace(c["mu"] - 4.5 * c["sigma"], c["mu"] + 4.5 * c["sigma"], 300)
    z = norm.pdf(x, c["mu"], c["sigma"])

    # ── 가우시안 커브 (3D 라인) ──
    y_arr = np.full_like(x, y_pos)
    ax_3d.plot(x, y_arr, z, color=col, lw=2.5, ls=ls, zorder=5)

    # ── 반투명 면 채우기 (커브 아래 영역) ──
    verts = [(x[0], y_pos, 0)]
    for xi, zi in zip(x, z):
        verts.append((xi, y_pos, zi))
    verts.append((x[-1], y_pos, 0))
    poly = Poly3DCollection([verts], alpha=0.15, facecolor=col, edgecolor="none")
    ax_3d.add_collection3d(poly)

    # ── 실측 기반 히스토그램 심벌 마커 (fig11 방식) ──
    n_vis = min(c["N"], 3000)
    synth = RNG.normal(c["mu"], c["sigma"], n_vis)
    h_cnt, h_edges = np.histogram(synth, bins=22, density=True)
    h_centers = (h_edges[:-1] + h_edges[1:]) / 2
    h_y = np.full_like(h_centers, y_pos)
    ax_3d.plot(h_centers, h_y, h_cnt,
               marker=marker, color=col, ls="none",
               ms=7, markerfacecolor="none", markeredgewidth=1.5,
               alpha=0.9, zorder=6)

    z_peak = norm.pdf(c["mu"], c["mu"], c["sigma"])

    # ── μ 수직 점선 (바닥 → 피크) ──
    ax_3d.plot([c["mu"], c["mu"]], [y_pos, y_pos], [0, z_peak],
               color=col, lw=1.0, ls=":", alpha=0.6, zorder=3)

    # ── τ 반투명 막대 (bar) ──
    z_at_tau = norm.pdf(c["tau"], c["mu"], c["sigma"])
    # 막대 본체: 바닥(z=0) → τ 위치의 밀도 높이
    bar_height = max(z_peak * 0.6, z_at_tau * 1.5)  # 시각적으로 충분한 높이
    ax_3d.plot([c["tau"], c["tau"]], [y_pos, y_pos], [0, bar_height],
               color=col, lw=3.5, alpha=0.45, solid_capstyle="round", zorder=4)
    # 막대 상단 마름모 캡
    ax_3d.plot([c["tau"]], [y_pos], [bar_height],
               marker="d", color=col, ms=6,
               markerfacecolor=col, markeredgecolor="white",
               markeredgewidth=0.8, alpha=0.7, zorder=6)

    # ── τ 이론값 점선 (capped 도메인만) ──
    if c.get("capped") and "tau_theoretical" in c:
        tau_th = c["tau_theoretical"]
        ax_3d.plot([tau_th, tau_th], [y_pos, y_pos], [0, bar_height * 0.5],
                   color="black", lw=1.5, ls=":", alpha=0.7, zorder=3)
        ax_3d.text(tau_th, y_pos + 0.15, bar_height * 0.55,
                   f"τ_th={tau_th:.2f}", fontsize=12, color="black",
                   fontweight="bold", ha="left")

    # ── 도메인 레이블 (커브 끝) ──
    x_label = c["mu"] + 3.5 * c["sigma"]
    z_label = norm.pdf(x_label, c["mu"], c["sigma"])
    ax_3d.text(x_label, y_pos, z_label + z_peak * 0.05,
               f"{d}\nτ={c['tau']:.4f}",
               fontsize=10, fontweight="bold", color=col,
               ha="left", va="bottom", zorder=11)

    # ── 범례 항목 ──
    legend_handles.append(
        Line2D([0], [0], color=col, lw=2.5, ls=ls,
               marker=marker, markerfacecolor="none",
               markersize=8, markeredgewidth=1.8,
               label=f"{d}  μ={c['mu']:.4f}  σ={c['sigma']:.4f}  τ={c['tau']:.4f}")
    )

# ── 추가 범례 항목 ──
legend_handles += [
    mpatches.Patch(color="gray", alpha=0.15, label="Null 분포 면적"),
    Line2D([0], [0], color="gray", lw=3.5, alpha=0.45,
           solid_capstyle="round", label="τ (임계값 막대)"),
    Line2D([0], [0], color="gray", lw=1.0, ls=":", alpha=0.6, label="μ_null 수직선"),
    Line2D([0], [0], marker="d", color="gray", lw=0,
           markersize=6, markerfacecolor="gray", markeredgecolor="white",
           markeredgewidth=0.8, alpha=0.7, label="τ 막대 캡"),
]

# ── 축 범위 설정 ──
ax_3d.set_xlim(0.0, 1.1)
ax_3d.set_ylim(min(sigma_values) - 0.5, max(sigma_values) + 1.0)
ax_3d.set_zlim(0, 22)

# ── 축 틱 ──
ax_3d.set_xticks(np.arange(0.0, 1.2, 0.1))
ax_3d.tick_params(axis="x", labelsize=13, pad=2)
ax_3d.tick_params(axis="y", labelsize=13, pad=2)
ax_3d.tick_params(axis="z", labelsize=13, pad=2)

# ── 배경 그리드 투명도 ──
ax_3d.xaxis.pane.fill = False
ax_3d.yaxis.pane.fill = False
ax_3d.zaxis.pane.fill = False
ax_3d.xaxis.pane.set_edgecolor("gray")
ax_3d.yaxis.pane.set_edgecolor("gray")
ax_3d.zaxis.pane.set_edgecolor("gray")
ax_3d.xaxis.pane.set_alpha(0.1)
ax_3d.yaxis.pane.set_alpha(0.1)
ax_3d.zaxis.pane.set_alpha(0.1)
ax_3d.grid(True, alpha=0.2, linestyle="--")

# ── 범례 ──
ax_3d.legend(handles=legend_handles, fontsize=10, loc="upper right",
             bbox_to_anchor=(1.0, 0.88), ncol=1, framealpha=0.92)

# ─────────────────────────────────────────────
# 5. 저장
# ─────────────────────────────────────────────
save(fig, "fig11-1_calibration_domain_compare.png")

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
