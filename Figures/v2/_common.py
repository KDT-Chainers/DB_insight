"""Shared style + data for v2 publication figures.

도메인 색상은 v1 노트북과 일관성 유지. 폰트는 Malgun Gothic (Windows 한글).
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

OUT_DIR = Path(__file__).resolve().parent
DPI = 300

# 일관 색상 (v1 노트북 호환)
DOMAIN_COLORS = {
    "Doc":   "#4C72B0",
    "Img":   "#DD8452",
    "Movie": "#55A868",
    "Rec":   "#C44E52",
    "BGM":   "#8172B3",
}
DOMAIN_ORDER = ["Doc", "Img", "Movie", "Rec", "BGM"]

# 모듈/축 색상
AXIS_COLORS = {
    "Re": "#2E7D52",   # SigLIP2 (시각/cross-modal)
    "Im": "#1565C0",   # BGE-M3  (언어)
    "Z":  "#8E24AA",   # DINOv2  (구조)
}
MOD_COLORS = {
    "ASF":       "#A45C5C",
    "Lexical":   "#7B6B9E",
    "Rerank":    "#C47A3A",
    "LangGraph": "#5E8FBF",
}

# 실측 ablation (publication/paper/_*_results.json)
ABLATION = {
    "ASF": {
        "Doc":   {"off": 0.00, "on": 0.00, "p50_off": 72.5, "p50_on": 75.7},
        "Img":   {"off": 1.00, "on": 1.00, "p50_off": 35.0, "p50_on": 33.0},
        "Movie": {"off": 0.95, "on": 0.95, "p50_off": 46.0, "p50_on": 47.0},
        "Rec":   {"off": 1.00, "on": 1.00, "p50_off": 39.5, "p50_on": 37.5},
    },
    "Rerank": {
        "Movie": {"off": 0.967, "on": 0.333, "p95_off": 84.9,  "p95_on": 550.9},
        "Rec":   {"off": 1.000, "on": 0.200, "p95_off": 69.0,  "p95_on": 603.8},
    },
    "LangGraph": {
        "Movie": {"off": 0.867, "on": 0.867, "p95_off": 61.9, "p95_on": 57.4},
        "Rec":   {"off": 0.200, "on": 0.200, "p95_off": 44.7, "p95_on": 38.1},
    },
}

# 위상 ridge 분리도 (degrees)
PHASE_RIDGE = {
    "Img":   {"match_q50": 0.6,  "match_q90": 1.7,  "null_q10": 0.3,  "null_q50": 1.4,  "sep": 0.8},
    "Doc":   {"match_q50": 0.9,  "match_q90": 3.3,  "null_q10": 0.5,  "null_q50": 3.2,  "sep": 2.3},
    "Movie": {"match_q50": 0.9,  "match_q90": 3.0,  "null_q10": 0.7,  "null_q50": 4.0,  "sep": 3.2},
    "Rec":   {"match_q50": 1.0,  "match_q90": 2.8,  "null_q10": 0.4,  "null_q50": 2.1,  "sep": 1.1},
}

# 도메인 × 기능 적용 매트릭스
# 0=N/A(gray), 1=적용 효과있음, 2=적용 효과없음(yellow), 3=성능저하(red)
APPLICATION_MATRIX = {
    "ASF":       {"Doc": 2, "Img": 2, "Movie": 2, "Rec": 2, "BGM": 1},
    "Lexical":   {"Doc": 1, "Img": 0, "Movie": 1, "Rec": 1, "BGM": 0},
    "Rerank":    {"Doc": 0, "Img": 0, "Movie": 3, "Rec": 3, "BGM": 0},
    "LangGraph": {"Doc": 0, "Img": 0, "Movie": 2, "Rec": 2, "BGM": 0},
    "BGE-M3":    {"Doc": 1, "Img": 1, "Movie": 1, "Rec": 1, "BGM": 1},
    "SigLIP2":   {"Doc": 1, "Img": 1, "Movie": 1, "Rec": 0, "BGM": 1},
    "DINOv2":    {"Doc": 1, "Img": 1, "Movie": 0, "Rec": 0, "BGM": 0},
    "Whisper":   {"Doc": 0, "Img": 0, "Movie": 1, "Rec": 1, "BGM": 0},
    "CLAP":      {"Doc": 0, "Img": 0, "Movie": 0, "Rec": 0, "BGM": 1},
    "Calibration":{"Doc": 1, "Img": 1, "Movie": 1, "Rec": 1, "BGM": 1},
}

# 도메인별 hit@5 (실측, ASF off 기준 — 현재 default)
# Doc: _doc_query_len_ablation_results.json (n=30, 80-char query, lex off, Δ 2026-05-07)
HIT_AT_5 = {
    "Doc":   0.20,
    "Img":   1.00,
    "Movie": 0.95,
    "Rec":   1.00,
    "BGM":   0.92,  # 별도 BGM bench 추정치 (논문 v1-10 기준)
}

# Doc 보조 메트릭 — self-retrieval 한계 시각화용
HIT_DOC_EXTENDED = {
    "hit_at_5":  0.20,
    "hit_at_10": 0.27,
    "hit_at_50": 0.50,
    "n_corpus":  34718,
    "n_sample":  30,
    "missing_gt50_pct": 0.50,  # 50% 가 top-50 밖
}


def setup_style(theme: str = "light") -> None:
    mpl.rcParams["font.family"] = "Malgun Gothic"
    mpl.rcParams["axes.unicode_minus"] = False
    mpl.rcParams["font.size"] = 10
    mpl.rcParams["axes.labelsize"] = 11
    mpl.rcParams["axes.titlesize"] = 13
    mpl.rcParams["axes.titleweight"] = "bold"
    mpl.rcParams["axes.spines.top"]   = False
    mpl.rcParams["axes.spines.right"] = False
    mpl.rcParams["axes.grid"] = True
    mpl.rcParams["grid.alpha"] = 0.25
    mpl.rcParams["grid.linestyle"] = "--"
    mpl.rcParams["legend.frameon"] = True
    mpl.rcParams["legend.framealpha"] = 0.92
    mpl.rcParams["savefig.bbox"] = "tight"
    mpl.rcParams["savefig.dpi"] = DPI
    mpl.rcParams["figure.facecolor"] = "white"


def save(fig, name: str) -> Path:
    out = OUT_DIR / name
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[OK] {name}  →  {out}")
    return out
