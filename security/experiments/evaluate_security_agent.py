"""
evaluate_security_agent.py
──────────────────────────────────────────────────────────────────────────────
보안 에이전트 성능 평가 스크립트.

출력:
  1) JSON 리포트
  2) Markdown 표 리포트
  3) PNG 차트 (matplotlib 설치 시)

평가 항목:
  - Query 분류 성능 (NORMAL/SENSITIVE/DANGEROUS): accuracy, macro-F1, confusion matrix
  - Action 성능 (allow/confirm/block): accuracy
  - Upload PII 탐지 성능 (has_pii 이진): accuracy, precision, recall, f1
  - SVG 차트 생성 (외부 라이브러리 없이)
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.upload_security import UploadSecurityAgent
from security.pii_detector import PIIDetector
from security.qwen_classifier import QwenClassifier


LABELS = ["NORMAL", "SENSITIVE", "DANGEROUS"]
ACTIONS = ["allow", "confirm", "block"]


@dataclass
class QueryCase:
    query: str
    expected_label: str
    expected_action: str


@dataclass
class UploadCase:
    path: Path
    expected_has_pii: bool


def _safe_div(a: float, b: float) -> float:
    return 0.0 if b == 0 else a / b


def _accuracy(y_true: List[str], y_pred: List[str]) -> float:
    if not y_true:
        return 0.0
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return correct / len(y_true)


def _class_metrics(y_true: List[str], y_pred: List[str], labels: List[str]) -> Dict[str, Any]:
    cm: Dict[str, Dict[str, int]] = {l: {k: 0 for k in labels} for l in labels}
    for t, p in zip(y_true, y_pred):
        if t in cm and p in cm[t]:
            cm[t][p] += 1

    per_label: Dict[str, Dict[str, float]] = {}
    f1s: List[float] = []
    for l in labels:
        tp = cm[l][l]
        fp = sum(cm[t][l] for t in labels if t != l)
        fn = sum(cm[l][p] for p in labels if p != l)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        support = sum(cm[l].values())
        per_label[l] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }
        f1s.append(f1)

    return {
        "accuracy": round(_accuracy(y_true, y_pred), 4),
        "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
        "per_label": per_label,
        "confusion_matrix": cm,
    }


def _binary_metrics(y_true: List[bool], y_pred: List[bool]) -> Dict[str, float]:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    tn = sum(1 for t, p in zip(y_true, y_pred) if (not t) and (not p))
    fp = sum(1 for t, p in zip(y_true, y_pred) if (not t) and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and (not p))

    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    acc = _safe_div(tp + tn, len(y_true))
    return {
        "accuracy": round(acc, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def _load_query_cases(data_dir: Path) -> List[QueryCase]:
    path = data_dir / "dangerous_queries.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        QueryCase(
            query=row["query"],
            expected_label=row["expected_label"],
            expected_action=row["expected_action"],
        )
        for row in rows
    ]


def _default_upload_cases(data_dir: Path) -> List[UploadCase]:
    return [
        UploadCase(path=data_dir / "normal_meeting.pdf", expected_has_pii=False),
        UploadCase(path=data_dir / "pii_profile.pdf", expected_has_pii=True),
        UploadCase(path=data_dir / "pii_profile.hwpx", expected_has_pii=True),
        UploadCase(path=data_dir / "bank_info.pdf", expected_has_pii=True),
    ]


def _build_feature_map(query: str) -> Dict[str, Any]:
    q = query.lower()
    bulk_keywords = ["전부", "모두", "전체", "all", "dump", "export"]
    sensitive_keywords = ["계좌", "주민", "카드", "여권", "사업자", "개인정보"]
    contains_pii = any(k in q for k in sensitive_keywords)
    bulk_request = any(k in q for k in bulk_keywords)
    sensitivity_score = 0.2 + (0.4 if contains_pii else 0.0) + (0.4 if bulk_request else 0.0)
    return {
        "matched_docs": 3,
        "contains_pii": contains_pii,
        "pii_types": ["synthetic"] if contains_pii else [],
        "bulk_request": bulk_request,
        "owner_match": True,
        "sensitivity_score": round(min(1.0, sensitivity_score), 4),
    }


def _fallback_classify(user_query: str, feature_map: Dict[str, Any]):
    from security.qwen_classifier import ClassificationResult

    q = user_query.lower()
    dangerous_kw = ["전부", "모두", "전체 출력", "dump", "export", "삭제", "all records"]
    sensitive_kw = ["계좌번호", "주민번호", "비밀번호", "카드번호", "패스워드"]

    if any(kw in q for kw in dangerous_kw) or feature_map.get("bulk_request"):
        return ClassificationResult(
            label="DANGEROUS",
            reason="위험 키워드 또는 대량 요청 감지 (fallback)",
            action="block",
        )
    if any(kw in q for kw in sensitive_kw) or feature_map.get("contains_pii"):
        return ClassificationResult(
            label="SENSITIVE",
            reason="민감 키워드 또는 PII 포함 문서 감지 (fallback)",
            action="confirm",
        )
    return ClassificationResult(
        label="NORMAL",
        reason="일반 질문 (fallback)",
        action="allow",
    )


def evaluate_queries(mode: str, data_dir: Path) -> Dict[str, Any]:
    cases = _load_query_cases(data_dir)
    qwen = QwenClassifier()

    pred_labels: List[str] = []
    true_labels: List[str] = []
    pred_actions: List[str] = []
    true_actions: List[str] = []
    details: List[Dict[str, Any]] = []

    for case in cases:
        feature_map = _build_feature_map(case.query)
        if mode == "qwen" and qwen.is_available():
            pred = qwen.classify_query(case.query, feature_map)
            used = "qwen"
        else:
            pred = _fallback_classify(case.query, feature_map)
            used = "fallback"

        true_labels.append(case.expected_label)
        pred_labels.append(pred.label)
        true_actions.append(case.expected_action)
        pred_actions.append(pred.action)
        details.append(
            {
                "query": case.query,
                "expected_label": case.expected_label,
                "pred_label": pred.label,
                "expected_action": case.expected_action,
                "pred_action": pred.action,
                "reason": pred.reason,
                "mode_used": used,
            }
        )

    return {
        "mode": mode,
        "label_metrics": _class_metrics(true_labels, pred_labels, LABELS),
        "action_metrics": _class_metrics(true_actions, pred_actions, ACTIONS),
        "cases": details,
    }


def evaluate_upload_pii(data_dir: Path) -> Dict[str, Any]:
    detector = PIIDetector(qwen_classifier=None)
    agent = UploadSecurityAgent(pii_detector=detector)
    cases = _default_upload_cases(data_dir)

    y_true: List[bool] = []
    y_pred: List[bool] = []
    details: List[Dict[str, Any]] = []

    for case in cases:
        scan = agent.scan_file(case.path)
        y_true.append(case.expected_has_pii)
        y_pred.append(scan.has_pii)
        details.append(
            {
                "file": str(case.path.name),
                "expected_has_pii": case.expected_has_pii,
                "pred_has_pii": scan.has_pii,
                "pii_summary": scan.pii_summary,
                "error": scan.error,
            }
        )

    return {
        "metrics": _binary_metrics(y_true, y_pred),
        "cases": details,
    }


def _render_markdown(report: Dict[str, Any]) -> str:
    q = report["query_eval"]
    p = report["pii_eval"]
    lm = q["label_metrics"]
    am = q["action_metrics"]
    pm = p["metrics"]

    lines: List[str] = []
    lines.append("# Security Agent Evaluation Report")
    lines.append("")
    lines.append(f"- Generated at: `{report['generated_at']}`")
    lines.append(f"- Query mode: `{q['mode']}`")
    lines.append("")
    lines.append("## 1) Query Classification Performance")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Label Accuracy | {lm['accuracy']:.4f} |")
    lines.append(f"| Label Macro-F1 | {lm['macro_f1']:.4f} |")
    lines.append(f"| Action Accuracy | {am['accuracy']:.4f} |")
    lines.append(f"| Action Macro-F1 | {am['macro_f1']:.4f} |")
    lines.append("")
    lines.append("### Label-wise")
    lines.append("")
    lines.append("| Label | Precision | Recall | F1 | Support |")
    lines.append("|---|---:|---:|---:|---:|")
    for label, m in lm["per_label"].items():
        lines.append(f"| {label} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['support']} |")
    lines.append("")
    lines.append("## 2) Upload PII Detection Performance")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Accuracy | {pm['accuracy']:.4f} |")
    lines.append(f"| Precision | {pm['precision']:.4f} |")
    lines.append(f"| Recall | {pm['recall']:.4f} |")
    lines.append(f"| F1 | {pm['f1']:.4f} |")
    lines.append(f"| TP / TN / FP / FN | {pm['tp']} / {pm['tn']} / {pm['fp']} / {pm['fn']} |")
    lines.append("")
    lines.append("## 3) Notes")
    lines.append("")
    lines.append("- This benchmark uses synthetic dummy data in `secure_rag/data`.")
    lines.append("- For team demo, compare this baseline with real anonymized samples.")
    lines.append("")
    return "\n".join(lines)


def _save_chart(report: Dict[str, Any], output_png: Path) -> str:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return "matplotlib not installed; skipped chart generation."

    lm = report["query_eval"]["label_metrics"]
    pm = report["pii_eval"]["metrics"]

    metrics = {
        "Label Acc": lm["accuracy"],
        "Label F1": lm["macro_f1"],
        "PII Acc": pm["accuracy"],
        "PII F1": pm["f1"],
    }

    plt.figure(figsize=(8, 4.5))
    xs = list(metrics.keys())
    ys = [metrics[k] for k in xs]
    bars = plt.bar(xs, ys)
    plt.ylim(0, 1.0)
    plt.title("Security Agent Evaluation (Dummy Data)")
    plt.ylabel("Score")
    for b, y in zip(bars, ys):
        plt.text(b.get_x() + b.get_width() / 2, y + 0.02, f"{y:.2f}", ha="center")
    plt.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_png, dpi=150)
    plt.close()
    return f"chart saved to {output_png}"


def _save_svg_chart(report: Dict[str, Any], output_svg: Path) -> str:
    lm = report["query_eval"]["label_metrics"]
    pm = report["pii_eval"]["metrics"]
    metrics = [
        ("Label Acc", lm["accuracy"]),
        ("Label F1", lm["macro_f1"]),
        ("PII Acc", pm["accuracy"]),
        ("PII F1", pm["f1"]),
    ]

    width = 900
    height = 520
    margin_left = 110
    margin_right = 40
    margin_top = 80
    margin_bottom = 90
    chart_w = width - margin_left - margin_right
    chart_h = height - margin_top - margin_bottom
    bar_w = chart_w // (len(metrics) * 2)
    gap = bar_w

    colors = ["#2E86DE", "#10AC84", "#F39C12", "#8E44AD"]

    parts: List[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">')
    parts.append('<rect width="100%" height="100%" fill="white"/>')
    parts.append('<text x="110" y="40" font-size="24" font-family="Arial" font-weight="bold">'
                 'Security Agent Evaluation (Dummy Data)</text>')

    # axes
    x0, y0 = margin_left, margin_top + chart_h
    parts.append(f'<line x1="{x0}" y1="{margin_top}" x2="{x0}" y2="{y0}" stroke="#333" stroke-width="2"/>')
    parts.append(f'<line x1="{x0}" y1="{y0}" x2="{x0 + chart_w}" y2="{y0}" stroke="#333" stroke-width="2"/>')

    # y ticks
    for i in range(6):
        v = i / 5
        y = margin_top + chart_h - int(v * chart_h)
        parts.append(f'<line x1="{x0 - 6}" y1="{y}" x2="{x0}" y2="{y}" stroke="#333" stroke-width="1"/>')
        parts.append(f'<text x="{x0 - 50}" y="{y + 5}" font-size="12" font-family="Arial">{v:.1f}</text>')

    # bars
    cur_x = x0 + gap
    for idx, (name, value) in enumerate(metrics):
        h = int(value * chart_h)
        y = y0 - h
        color = colors[idx % len(colors)]
        parts.append(f'<rect x="{cur_x}" y="{y}" width="{bar_w}" height="{h}" fill="{color}" rx="4"/>')
        parts.append(f'<text x="{cur_x + bar_w / 2}" y="{y - 8}" text-anchor="middle" '
                     f'font-size="12" font-family="Arial">{value:.2f}</text>')
        parts.append(f'<text x="{cur_x + bar_w / 2}" y="{y0 + 24}" text-anchor="middle" '
                     f'font-size="12" font-family="Arial">{name}</text>')
        cur_x += bar_w + gap

    parts.append('<text x="20" y="260" transform="rotate(-90,20,260)" '
                 'font-size="14" font-family="Arial">Score</text>')
    parts.append('</svg>')

    output_svg.parent.mkdir(parents=True, exist_ok=True)
    output_svg.write_text("\n".join(parts), encoding="utf-8")
    return f"svg chart saved to {output_svg}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate security agent performance")
    parser.add_argument(
        "--mode",
        choices=["fallback", "qwen"],
        default="fallback",
        help="query classification mode; qwen requires running ollama server",
    )
    parser.add_argument(
        "--data-dir",
        default=str(ROOT / "data"),
        help="dummy data directory",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "reports"),
        help="report output directory",
    )
    parser.add_argument(
        "--chart",
        action="store_true",
        help="generate PNG chart with matplotlib (optional)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    query_eval = evaluate_queries(args.mode, data_dir)
    pii_eval = evaluate_upload_pii(data_dir)

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "query_eval": query_eval,
        "pii_eval": pii_eval,
    }

    json_path = out_dir / f"security_eval_{now}.json"
    md_path = out_dir / f"security_eval_{now}.md"
    png_path = out_dir / f"security_eval_{now}.png"
    svg_path = out_dir / f"security_eval_{now}.svg"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    svg_status = _save_svg_chart(report, svg_path)
    if args.chart:
        chart_status = _save_chart(report, png_path)
    else:
        chart_status = "chart generation skipped (--chart not set)."

    print(f"[OK] JSON: {json_path}")
    print(f"[OK] MD:   {md_path}")
    print(f"[OK] SVG:  {svg_path}")
    if args.chart:
        print(f"[OK] PNG:  {png_path}")
    print(f"[INFO] {svg_status}")
    print(f"[INFO] {chart_status}")
    print(f"[SUMMARY] label_acc={query_eval['label_metrics']['accuracy']:.4f} "
          f"label_f1={query_eval['label_metrics']['macro_f1']:.4f} "
          f"pii_acc={pii_eval['metrics']['accuracy']:.4f} pii_f1={pii_eval['metrics']['f1']:.4f}")


if __name__ == "__main__":
    main()
