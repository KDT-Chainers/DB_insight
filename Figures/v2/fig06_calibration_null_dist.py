"""fig06: 도메인별 Null 분포 캘리브레이션 + z-score sigmoid confidence.

NULL_QUERIES (의도적으로 무관한 20문장) 으로 측정한 cosine 분포 ←
실제 raw cos 분포와 함께 표시.  μ_null + 1.645·σ_null 임계선 (FAR=0.05).
"""
from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

import _common as C
C.setup_style()


# 도메인별 분포 시뮬레이션 파라미터 (논문 v1-10 기준)
DOMAIN_DIST = {
    "Img":   {"null_mu": 0.18, "null_sigma": 0.06, "match_mu": 0.42, "match_sigma": 0.08},
    "Doc":   {"null_mu": 0.24, "null_sigma": 0.08, "match_mu": 0.55, "match_sigma": 0.10},
    "Movie": {"null_mu": 0.32, "null_sigma": 0.10, "match_mu": 0.65, "match_sigma": 0.10},
    "Rec":   {"null_mu": 0.28, "null_sigma": 0.09, "match_mu": 0.58, "match_sigma": 0.11},
    "BGM":   {"null_mu": 0.85, "null_sigma": 0.04, "match_mu": 0.92, "match_sigma": 0.03},
    # BGM Re=Im=BGE-M3 → same-encoder baseline 높음 (논문 note)
}


def panel_null_dist(ax):
    rng = np.random.default_rng(2026)
    domains = ["Img", "Doc", "Movie", "Rec"]
    width = 0.7

    for i, d in enumerate(domains):
        p = DOMAIN_DIST[d]
        null_samples = rng.normal(p["null_mu"], p["null_sigma"], 1000)
        match_samples = rng.normal(p["match_mu"], p["match_sigma"], 600)

        # KDE 형태로 그리기
        from scipy.stats import gaussian_kde
        x = np.linspace(0, 1, 200)
        k_null  = gaussian_kde(null_samples)
        k_match = gaussian_kde(match_samples)

        offset = i * 1.0
        # null distribution (왼쪽)
        y_null  = k_null(x)
        y_null  = y_null / y_null.max() * 0.45
        ax.fill_between(x, offset, offset + y_null,
                        color=C.DOMAIN_COLORS[d], alpha=0.45,
                        edgecolor=C.DOMAIN_COLORS[d], linewidth=1.2)
        # match distribution (오른쪽)
        y_match = k_match(x)
        y_match = y_match / y_match.max() * 0.45
        ax.fill_between(x, offset, offset + y_match,
                        color=C.DOMAIN_COLORS[d], alpha=0.85,
                        edgecolor="white", linewidth=0.8, hatch="////")

        # threshold line
        thr = p["null_mu"] + 1.645 * p["null_sigma"]
        ax.plot([thr, thr], [offset, offset + 0.5],
                color="#222", linewidth=2.0, linestyle="--", zorder=5)
        ax.text(thr + 0.012, offset + 0.42,
                f"τ = μ + 1.645σ\n   = {thr:.2f}",
                fontsize=8, color="#222", fontweight="bold", linespacing=1.1)

        # μ markers
        ax.plot([p["null_mu"]],  [offset + 0.05], marker="v",
                markersize=10, color=C.DOMAIN_COLORS[d], zorder=6)
        ax.plot([p["match_mu"]], [offset + 0.05], marker="^",
                markersize=10, color=C.DOMAIN_COLORS[d], zorder=6)

        ax.text(-0.04, offset + 0.25, d, ha="right", va="center",
                fontsize=12, fontweight="bold",
                color=C.DOMAIN_COLORS[d])

    ax.set_xlim(0, 1.0)
    ax.set_ylim(-0.1, len(domains) * 1.0 + 0.3)
    ax.set_yticks([])
    ax.set_xlabel("Raw cosine score", fontsize=11)
    ax.set_title("도메인별 Null vs Match 분포 (Calibration)",
                 fontsize=13, color="#1D3557", pad=10)

    # 범례
    handles = [
        plt.Rectangle((0,0),1,1, facecolor="#888", alpha=0.45,
                      label="Null  (무관 쿼리)"),
        plt.Rectangle((0,0),1,1, facecolor="#888", alpha=0.85,
                      hatch="////", label="Match  (정답 쿼리)"),
        Line2D([0],[0], color="#222", lw=2.0, ls="--",
               label="임계 τ = μ + 1.645σ  (FAR=0.05)"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=9,
              framealpha=0.92)


def panel_zscore(ax):
    """raw → z → confidence 함수형 시각화."""
    raw_scores = np.linspace(0, 1.0, 200)

    domains = ["Img", "Doc", "Movie", "Rec"]
    for d in domains:
        p = DOMAIN_DIST[d]
        z = (raw_scores - p["null_mu"]) / p["null_sigma"]
        conf = 1.0 / (1.0 + np.exp(-z / 2.0))
        ax.plot(raw_scores, conf, color=C.DOMAIN_COLORS[d], linewidth=2.4,
                label=f"{d}  (μ={p['null_mu']:.2f}, σ={p['null_sigma']:.2f})")

    ax.axhline(0.5, color="#888", linestyle=":", linewidth=1.2)
    ax.axhline(0.88, color="#888", linestyle=":", linewidth=1.0, alpha=0.6)
    ax.text(0.02, 0.51, "z=0", fontsize=8, color="#666")
    ax.text(0.02, 0.89, "z=2  (88% conf)", fontsize=8, color="#666")

    ax.set_xlabel("Raw cosine score", fontsize=11)
    ax.set_ylabel("Confidence  (sigmoid(z/2))", fontsize=11)
    ax.set_title("Calibrated Confidence  C(s) = σ(z/2)",
                 fontsize=13, color="#1D3557", pad=10)
    ax.set_xlim(0, 1.0); ax.set_ylim(0, 1.05)
    ax.legend(loc="lower right", fontsize=9, framealpha=0.92)


def panel_threshold_table(ax):
    """우측: 도메인별 μ_null, σ_null, threshold 막대."""
    ax.axis("off")
    ax.set_xlim(0, 10); ax.set_ylim(0, 10)
    ax.set_title("도메인별 Calibration 파라미터",
                 fontsize=13, color="#1D3557", pad=10)

    rows = ["Domain", "μ_null", "σ_null", "τ (FAR=0.05)", "p95"]
    domains = ["Img", "Doc", "Movie", "Rec", "BGM"]

    # 헤더
    col_x = [0.3, 2.5, 4.6, 6.6, 8.5]
    for cx, h in zip(col_x, rows):
        ax.text(cx, 9.0, h, ha="left", va="center",
                fontsize=10.5, fontweight="bold", color="#1D3557")
    ax.plot([0.2, 9.8], [8.55, 8.55], color="#1D3557", linewidth=1.5)

    for i, d in enumerate(domains):
        p = DOMAIN_DIST[d]
        thr = p["null_mu"] + 1.645 * p["null_sigma"]
        p95 = p["null_mu"] + 1.96 * p["null_sigma"]
        y = 7.6 - i * 1.30

        # color tag
        ax.add_patch(plt.Rectangle((0.15, y - 0.32), 0.18, 0.66,
                                   facecolor=C.DOMAIN_COLORS[d],
                                   edgecolor="none"))
        ax.text(0.45, y, d, ha="left", va="center",
                fontsize=11, fontweight="bold",
                color=C.DOMAIN_COLORS[d])
        ax.text(2.5, y, f"{p['null_mu']:.3f}",     fontsize=10.5)
        ax.text(4.6, y, f"{p['null_sigma']:.3f}",   fontsize=10.5)
        ax.text(6.6, y, f"{thr:.3f}",               fontsize=10.5,
                fontweight="bold", color="#C62828")
        ax.text(8.5, y, f"{p95:.3f}",               fontsize=10.5)

        ax.plot([0.2, 9.8], [y - 0.55, y - 0.55],
                color="#DDD", linewidth=0.5)

    # 푸터 노트
    ax.text(0.3, 0.5,
            "BGM 은 Re=Im=BGE-M3 동일공간 → baseline 자체가 높음 (cross-modal 과 직접 비교 불가)",
            fontsize=8.5, color="#666", style="italic")


def main():
    fig = plt.figure(figsize=(19, 8.5))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.2, 1.0],
                          height_ratios=[1.4, 1.0],
                          hspace=0.35, wspace=0.20)

    ax1 = fig.add_subplot(gs[:, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, 1])

    panel_null_dist(ax1)
    panel_zscore(ax2)
    panel_threshold_table(ax3)

    fig.suptitle(
        "Calibration  —  Null 분포 측정과 z-score 변환",
        fontsize=17, fontweight="bold", color="#1D3557", y=0.99)
    fig.text(0.5, -0.005,
             "공식:  $z = (s - \\mu_{null})/\\sigma_{null}$,  "
             "$C = \\sigma(z/2)$,   "
             "임계  $\\tau = \\mu + 1.645 \\sigma$ (FAR=0.05)",
             ha="center", fontsize=11, color="#444")

    plt.subplots_adjust(top=0.93, bottom=0.06, left=0.06, right=0.98)
    C.save(fig, "fig06_calibration_null_dist.png")


if __name__ == "__main__":
    main()
