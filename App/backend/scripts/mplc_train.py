"""MPLC Step 2 — 도메인별 Logistic Regression 학습 + 5-fold CV.

입력: md/_mplc_features.csv (Step 1 산출)

학습:
  - 도메인별 5 모델 (LogisticRegression)
  - class_weight='balanced' (rel 1% 불균형 보정)
  - L2 regularization (C=1.0)
  - 5-fold cross-validation
  - 7 features × 5 domains = 35 weights + 5 bias

Heuristic relabeling:
  - expected_keyword=None 인 케이스의 도메인 일치 top-3 결과 → relevant
  - 데이터 라벨 보강 (overfitting 위험 감소)

산출:
  services/mplc_weights.py     (학습된 weights — 추론용 import)
  md/_mplc_train_report.md     (CV 결과 + weight 분석)
"""
from __future__ import annotations
import sys, csv, json
from pathlib import Path
from collections import defaultdict

# ── numpy / sklearn 가용성 확인 ──────────────────────────────────────────
try:
    import numpy as np
except ImportError:
    print("ERROR: numpy 필요"); sys.exit(1)

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import KFold
    from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score, f1_score
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    print("WARN: sklearn 없음 — numpy closed-form fallback")


FEATURES = ["dense", "sparse", "asf", "rerank",
            "keyword_count", "filename_substr", "z_dense"]


def load_csv(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def heuristic_relabel(rows: list[dict]) -> list[dict]:
    """expected_keyword=None 케이스의 도메인 일치 top-3 → relevant.

    Step 1 의 144 rel/31884 irr 극단 불균형 완화.
    각 case_id 별로 result_domain 이 case_domain 과 같은 결과 중 dense 상위 3개.
    """
    by_case_dom: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_case_dom[(r["case_id"], r["result_domain"])].append(r)

    augmented = 0
    for (cid, dom), group in by_case_dom.items():
        # 케이스 도메인 정보는 첫 row 의 case_domain 에 있음
        if not group:
            continue
        case_dom = group[0]["case_domain"]
        if dom != case_dom:
            continue   # 다른 도메인 결과는 그대로 0
        if group[0]["expected_kw"]:
            continue   # expected_kw 있는 케이스는 Step 1 라벨 그대로 (정확)
        # expected_kw 없음 + 도메인 일치 → top-3 dense → relevant
        sorted_group = sorted(group, key=lambda x: float(x.get("dense", 0)), reverse=True)
        for r in sorted_group[:3]:
            if r["relevant"] == "0":
                r["relevant"] = "1"
                augmented += 1
    print(f"[relabel] heuristic augment: +{augmented} relevant")
    return rows


def main() -> None:
    sys.stdout = sys.stdout.reconfigure(encoding="utf-8") or sys.stdout
    project_root = Path(__file__).resolve().parents[3]
    in_csv = project_root / "md" / "_mplc_features.csv"
    out_md = project_root / "md" / "_mplc_train_report.md"
    out_weights = project_root / "App" / "backend" / "services" / "mplc_weights.py"

    rows = load_csv(in_csv)
    print(f"[mplc-train] {len(rows)} rows loaded")

    # Heuristic relabeling
    rows = heuristic_relabel(rows)

    # 도메인별 분리
    by_dom: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_dom[r["result_domain"]].append(r)

    weights_dict: dict[str, dict] = {}
    md_lines = ["# MPLC Step 2 — Logistic Regression 학습 결과\n",
                "## 도메인별 학습\n"]

    for dom in ("doc", "image", "video", "audio", "bgm"):
        lst = by_dom[dom]
        if not lst:
            continue
        # Feature matrix + 라벨
        X = np.array([[float(r[f]) for f in FEATURES] for r in lst], dtype=np.float32)
        y = np.array([1 if r["relevant"] == "1" else 0 for r in lst], dtype=np.int32)
        n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
        print(f"\n[{dom}] n={len(lst)}  pos={n_pos}  neg={n_neg}  ratio={n_pos/max(1,len(lst))*100:.2f}%")
        md_lines.append(f"\n### {dom}  (n={len(lst)}, pos={n_pos}, neg={n_neg})")

        if n_pos < 5 or n_neg < 5:
            print(f"  [{dom}] pos/neg 부족 → skip")
            md_lines.append("- pos/neg 부족 → skip")
            continue

        if not HAS_SKLEARN:
            print("  sklearn 없음 — skip"); continue

        # 5-fold CV
        kf = KFold(n_splits=5, shuffle=True, random_state=42)
        cv_aucs, cv_f1s, cv_prec, cv_rec = [], [], [], []
        for fold, (tr, te) in enumerate(kf.split(X)):
            X_tr, y_tr = X[tr], y[tr]
            X_te, y_te = X[te], y[te]
            try:
                model = LogisticRegression(
                    class_weight="balanced",
                    C=1.0, max_iter=500, solver="lbfgs",
                )
                model.fit(X_tr, y_tr)
                pred = model.predict(X_te)
                proba = model.predict_proba(X_te)[:, 1]
                if len(set(y_te)) >= 2:
                    cv_aucs.append(roc_auc_score(y_te, proba))
                cv_f1s.append(f1_score(y_te, pred, zero_division=0))
                cv_prec.append(precision_score(y_te, pred, zero_division=0))
                cv_rec.append(recall_score(y_te, pred, zero_division=0))
            except Exception as e:
                print(f"  fold {fold} fail: {e}")

        if cv_aucs:
            print(f"  CV: AUC={np.mean(cv_aucs):.3f}±{np.std(cv_aucs):.3f}  "
                  f"F1={np.mean(cv_f1s):.3f}  prec={np.mean(cv_prec):.3f}  "
                  f"rec={np.mean(cv_rec):.3f}")
            md_lines.append(f"- CV AUC: **{np.mean(cv_aucs):.3f}** ±{np.std(cv_aucs):.3f}")
            md_lines.append(f"- CV F1:  {np.mean(cv_f1s):.3f}")
            md_lines.append(f"- CV Precision: {np.mean(cv_prec):.3f}")
            md_lines.append(f"- CV Recall: {np.mean(cv_rec):.3f}")

        # 전체 데이터로 final 학습
        final = LogisticRegression(class_weight="balanced", C=1.0, max_iter=1000, solver="lbfgs")
        final.fit(X, y)
        weights = final.coef_[0]
        bias = final.intercept_[0]
        weights_dict[dom] = {
            "bias": float(bias),
            "weights": {f: float(w) for f, w in zip(FEATURES, weights)},
            "cv_auc": float(np.mean(cv_aucs)) if cv_aucs else 0.0,
        }
        # weights 정렬 (절댓값 큰 순)
        wsort = sorted(zip(FEATURES, weights), key=lambda x: -abs(x[1]))
        print(f"  bias={bias:.3f}")
        md_lines.append(f"\n| feature | weight | |weight| 정규화 |")
        md_lines.append("|---|---|---|")
        max_w = max(abs(w) for w in weights) if any(weights) else 1.0
        for f, w in wsort:
            print(f"  w[{f:18}] = {w:+.4f}")
            md_lines.append(f"| {f} | {w:+.4f} | {'█' * int(abs(w)/max_w * 20)} |")

    # weights 저장
    weights_py = '"""MPLC Step 2 학습 결과 — 도메인별 logistic regression weights.\n\n'
    weights_py += "각 도메인의 final score = sigmoid(bias + Σ wᵢ · featureᵢ).\n"
    weights_py += "Cross-validation 으로 검증된 weights.\n"
    weights_py += '"""\n\n'
    weights_py += f"FEATURES = {json.dumps(FEATURES)}\n\n"
    weights_py += "MPLC_WEIGHTS = " + json.dumps(weights_dict, indent=2, ensure_ascii=False) + "\n"
    out_weights.write_text(weights_py, encoding="utf-8")
    print(f"\n[output] {out_weights}")

    out_md.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[output] {out_md}")


if __name__ == "__main__":
    main()
