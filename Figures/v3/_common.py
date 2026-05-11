"""Shared style + data for v3 publication figures.

v3.1: Enhanced design, corrected fusion weights, Sparse/ASF split ablation.
Data sourced from actual implementation code.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

OUT_DIR = Path(__file__).resolve().parent
DPI = 300

# ── Color Palette ──────────────────────────────────────────
DOMAIN_COLORS = {
    "Doc":   "#3B6FA0",
    "Img":   "#E07B39",
    "Movie": "#4AA564",
    "Rec":   "#C44E52",
    "BGM":   "#8172B3",
}
DOMAIN_ORDER = ["Doc", "Img", "Movie", "Rec", "BGM"]

AXIS_COLORS = {
    "Re": "#2E7D52",
    "Im": "#1565C0",
    "Z":  "#8E24AA",
}

CHANNEL_COLORS = {
    "dense":  "#2E7D52",
    "sparse": "#1565C0",
    "asf":    "#8E24AA",
}

STAGE_COLORS = {
    "preprocess": "#607D8B",
    "dense":      "#2E7D52",
    "sparse":     "#1565C0",
    "asf":        "#8E24AA",
    "fusion":     "#E65100",
    "tau":        "#C62828",
    "confidence": "#0D47A1",
    "mplc":       "#2E7D32",
    "boost":      "#F57F17",
    "quota":      "#6A1B9A",
    "rerank":     "#BF360C",
    "floor":      "#263238",
}

# ── Calibration (live: trichef_calibration.json) ──────────
CAL = {
    "Doc":   {"mu": 0.7982, "sigma": 0.0967, "tau": 0.9573, "FAR": 0.05, "N": 34718},
    "Img":   {"mu": 0.2197, "sigma": 0.0350, "tau": 0.2492, "FAR": 0.20, "N": 2390},
    "Movie": {"mu": 0.1576, "sigma": 0.0424, "tau": 0.2274, "FAR": 0.05, "N": 45647},
    "Rec":   {"mu": 0.6809, "sigma": 0.0683, "tau": 0.7933, "FAR": 0.05, "N": 11039},
}

# ── MPLC Learned Weights (mplc_weights.py) ────────────────
MPLC_WEIGHTS = {
    "Doc":   {"dense": 14.40, "sparse": 0.0,  "asf": 0.0,  "rerank": 0.0,
              "keyword": 0.0,  "filename": 0.28, "z_dense": 8.50,
              "bias": -19.36, "auc": 0.985},
    "Img":   {"dense": 17.80, "sparse": 0.0,  "asf": 0.0,  "rerank": 0.0,
              "keyword": 0.0,  "filename": 0.0,  "z_dense": 0.32,
              "bias": -13.42, "auc": 0.921},
    "Movie": {"dense": 9.75,  "sparse": 2.68, "asf": 0.84, "rerank": 0.0,
              "keyword": 0.0,  "filename": 0.0,  "z_dense": 1.51,
              "bias": -12.79, "auc": 0.986},
    "Rec":   {"dense": 0.54,  "sparse": 0.23, "asf": 2.18, "rerank": 0.0,
              "keyword": 0.0,  "filename": 0.0,  "z_dense": 3.68,
              "bias": -9.24,  "auc": 0.989},
    "BGM":   {"dense": 12.54, "sparse": 0.0,  "asf": 0.0,  "rerank": 0.0,
              "keyword": 0.0,  "filename": 0.0,  "z_dense": 0.0,
              "bias": -5.78,  "auc": 0.922},
}

# ── Fusion Weights (unified_engine.py) ────────────────────
# DI path: w_d=0.60, w_lex=0.25, w_asf=0.15
# AV path: alpha=0.60, beta=0.15(lex), gamma=0.25(asf)
FUSION_WEIGHTS = {
    "Doc":   {"dense": 0.60, "sparse": 0.25, "asf": 0.15},
    "Img":   {"dense": 1.00, "sparse": 0.00, "asf": 0.00},
    "Movie": {"dense": 0.60, "sparse": 0.15, "asf": 0.25},
    "Rec":   {"dense": 0.60, "sparse": 0.15, "asf": 0.25},
    "BGM":   {"dense": 1.00, "sparse": 0.00, "asf": 0.00},
}

# ── Ablation (Sparse/ASF split from RRF) ─────────────────
ABLATION = {
    "Re only":        60,
    "Re + Im":        73,
    "Re + Im + Z":    80,
    "+ Gram-Schmidt":  87,
    "+ Sparse":        87,
    "+ ASF":           87,
    "+ Calibration":   93,
}

# ── Floor Thresholds (search.py) ──────────────────────────
FLOOR = {
    "Img":   {"min_conf": 0.40, "min_sim": 0.50, "min_dense": 0.50},
    "Doc":   {"min_conf": 0.30, "min_sim": 0.68, "min_dense": 0.50},
    "Movie": {"min_conf": 0.40, "min_sim": 0.75, "min_dense": 0.55},
    "Rec":   {"min_conf": 0.40, "min_sim": 0.85, "min_dense": 0.55},
    "BGM":   {"min_conf": 0.40, "min_sim": 0.55, "min_dense": 0.45},
}

# ── Quota Allocation (search.py) ──────────────────────────
QUOTA_RULES = [
    {"label": "conf >= 0.80", "multiplier": 2.0, "slots": 20},
    {"label": "conf >= 0.50", "multiplier": 1.0, "slots": 10},
    {"label": "conf >= 0.30", "multiplier": 0.5, "slots": 5},
    {"label": "conf < 0.30",  "multiplier": 0.0, "slots": 1},
]


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
