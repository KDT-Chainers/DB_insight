"""Figures/v4/fig_hermitian_ab_heatmap.py — Hermitian alpha/beta grid search 시각화.

입력: DI_TriCHEF/results/*_hermitian_ab_sweep.json
출력:
  - fig_hermitian_ab_heatmap.png  (R@5 + MRR@10 히트맵)
  - fig_hermitian_ab_line.png     (alpha별 R@1/R@5/MRR@10 라인 차트)
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import setup_style, save, load_latest_result, METRIC_COLORS, HEATMAP_CMAP


def _build_grid(data: dict) -> tuple[list[float], list[float], dict[str, np.ndarray]]:
    """결과 JSON → alpha/beta 축 + 메트릭 2D 배열."""
    alphas = data["grid"]["alphas"]
    betas = data["grid"]["betas"]
    results = data["results"]

    grids = {m: np.zeros((len(alphas), len(betas))) for m in ("r1", "r5", "mrr10")}

    for r in results:
        ai = alphas.index(r["alpha"])
        bi = betas.index(r["beta"])
        for m in grids:
            grids[m][ai, bi] = r[m]

    return alphas, betas, grids


def plot_heatmap(data: dict) -> None:
    """R@5 + MRR@10 이중 히트맵."""
    setup_style()
    alphas, betas, grids = _build_grid(data)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    fig.suptitle("Hermitian Score alpha/beta Grid Search  (Doc LOO, N=150)",
                 fontsize=16, fontweight="bold")

    metrics = [("r5", "Recall@5"), ("mrr10", "MRR@10")]

    for ax, (key, label) in zip(axes, metrics):
        grid = grids[key]
        im = ax.imshow(grid, cmap=HEATMAP_CMAP, aspect="auto",
                       vmin=grid.min() - 0.01, vmax=grid.max() + 0.01)

        # 셀 값 표시
        best_val = grid.max()
        for i in range(len(alphas)):
            for j in range(len(betas)):
                val = grid[i, j]
                is_best = abs(val - best_val) < 1e-6
                is_default = (alphas[i] == 0.4 and betas[j] == 0.2)

                color = "white" if val > (grid.min() + grid.max()) / 2 else "black"
                weight = "bold" if is_best else "normal"
                text = f"{val:.3f}"
                if is_best:
                    text += "\n(BEST)"
                if is_default:
                    text += "\n[default]"

                ax.text(j, i, text, ha="center", va="center",
                        fontsize=10, color=color, fontweight=weight)

                # 최적 조합 빨간 테두리
                if is_best:
                    rect = plt.Rectangle((j - 0.5, i - 0.5), 1, 1,
                                         linewidth=3, edgecolor="red",
                                         facecolor="none")
                    ax.add_patch(rect)

                # 기본값 파란 점선 테두리
                if is_default and not is_best:
                    rect = plt.Rectangle((j - 0.5, i - 0.5), 1, 1,
                                         linewidth=2, edgecolor="#1565C0",
                                         facecolor="none", linestyle="--")
                    ax.add_patch(rect)

        ax.set_xticks(range(len(betas)))
        ax.set_xticklabels([f"{b:.1f}" for b in betas])
        ax.set_yticks(range(len(alphas)))
        ax.set_yticklabels([f"{a:.1f}" for a in alphas])
        ax.set_xlabel("beta (Z-axis weight)")
        ax.set_ylabel("alpha (Im-axis weight)")
        ax.set_title(label)

        fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    save(fig, "fig_hermitian_ab_heatmap.png")


def plot_line(data: dict) -> None:
    """alpha별 R@1/R@5/MRR@10 라인 차트 (beta=0.0 고정, beta 무관 검증)."""
    setup_style()
    alphas, betas, grids = _build_grid(data)

    fig, ax = plt.subplots(figsize=(8, 5))
    fig.suptitle("Hermitian Score: Recall vs alpha  (beta=0.0, Doc LOO)",
                 fontsize=15, fontweight="bold")

    # beta=0.0 열 (index 0)
    bi = betas.index(0.0)
    for key, label in [("r1", "R@1"), ("r5", "R@5"), ("mrr10", "MRR@10")]:
        vals = grids[key][:, bi]
        ax.plot(alphas, vals, "o-", color=METRIC_COLORS[label],
                label=label, linewidth=2, markersize=7)

    # 기본값 alpha=0.4 표시
    ax.axvline(0.4, color="gray", linestyle="--", alpha=0.5, label="default alpha=0.4")

    ax.set_xlabel("alpha (Im-axis weight)")
    ax.set_ylabel("Score")
    ax.set_xticks(alphas)
    ax.legend(loc="best")
    ax.set_ylim(0, 1.05)

    # beta 무관 검증 주석
    spread_r5 = []
    for ai in range(len(alphas)):
        vals = [grids["r5"][ai, bi] for bi in range(len(betas))]
        spread_r5.append(max(vals) - min(vals))
    max_spread = max(spread_r5)
    ax.annotate(
        f"beta spread (R@5): max={max_spread:.4f}\n"
        f"(q_Z=zeros -> beta 무관 확인)",
        xy=(0.98, 0.02), xycoords="axes fraction",
        ha="right", va="bottom", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#F5F5F5",
                  edgecolor="#CCCCCC", alpha=0.9),
    )

    fig.tight_layout()
    save(fig, "fig_hermitian_ab_line.png")


def main() -> None:
    data = load_latest_result("hermitian_ab_sweep")
    plot_heatmap(data)
    plot_line(data)

    # 주요 결과 요약 출력
    best = data["best"]
    print(f"\nBEST: alpha={best['alpha']}, beta={best['beta']}")
    print(f"  R@1={best['r1']:.3f}  R@5={best['r5']:.3f}  MRR@10={best['mrr10']:.3f}")


if __name__ == "__main__":
    main()
