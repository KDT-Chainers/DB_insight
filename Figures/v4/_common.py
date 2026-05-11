"""Shared style + data for v4 experiment figures.

v4: Hermitian alpha/beta grid search + SigLIP2 model comparison.
Inherits v3 color palette and style conventions.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

OUT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = OUT_DIR  # 실험 결과 JSON도 Figures/v4/ 에 저장
DPI = 300

# ── Color Palette (v3 계승) ───────────────────────────────────
DOMAIN_COLORS = {
    "Doc":   "#3B6FA0",
    "Img":   "#E07B39",
    "Movie": "#4AA564",
    "Rec":   "#C44E52",
    "BGM":   "#8172B3",
}

AXIS_COLORS = {
    "Re": "#2E7D52",
    "Im": "#1565C0",
    "Z":  "#8E24AA",
}

MODEL_COLORS = {
    "SO400M": "#2E7D52",
    "Large":  "#1565C0",
}

METRIC_COLORS = {
    "R@1":    "#E65100",
    "R@5":    "#2E7D52",
    "MRR@10": "#1565C0",
}

HEATMAP_CMAP = "YlOrRd"


def setup_style() -> None:
    """Publication-ready style: large fonts, clean grid, professional look."""
    mpl.rcParams.update({
        "font.family":         "Malgun Gothic",
        "axes.unicode_minus":  False,
        "font.size":           13,
        "axes.labelsize":      15,
        "axes.titlesize":      16,
        "axes.titleweight":    "bold",
        "xtick.labelsize":     12,
        "ytick.labelsize":     12,
        "legend.fontsize":     12,
        "axes.spines.top":     False,
        "axes.spines.right":   False,
        "axes.grid":           True,
        "grid.alpha":          0.15,
        "grid.linestyle":      "--",
        "grid.linewidth":      0.8,
        "legend.frameon":      True,
        "legend.framealpha":   0.92,
        "legend.edgecolor":    "#CCCCCC",
        "savefig.bbox":        "tight",
        "savefig.dpi":         DPI,
        "figure.facecolor":    "white",
        "axes.facecolor":      "#FAFAFA",
        "figure.titlesize":    18,
        "figure.titleweight":  "bold",
    })


def save(fig, name: str) -> Path:
    out = OUT_DIR / name
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[OK] {name}")
    return out


def load_latest_result(prefix: str) -> dict:
    """RESULTS_DIR 에서 prefix 로 시작하는 가장 최신 JSON 로드."""
    candidates = sorted(RESULTS_DIR.glob(f"*_{prefix}.json"), reverse=True)
    if not candidates:
        raise FileNotFoundError(
            f"No result file matching '*_{prefix}.json' in {RESULTS_DIR}"
        )
    path = candidates[0]
    print(f"[load] {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))
