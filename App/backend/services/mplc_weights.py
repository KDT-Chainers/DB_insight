"""MPLC Step 2 학습 결과 — 도메인별 logistic regression weights.

각 도메인의 final score = sigmoid(bias + Σ wᵢ · featureᵢ).
Cross-validation 으로 검증된 weights.
"""

FEATURES = ["dense", "sparse", "asf", "rerank", "keyword_count", "filename_substr", "z_dense"]

MPLC_WEIGHTS = {
  "doc": {
    "bias": -11.954424159434407,
    "weights": {
      "dense": 6.410711354802691,
      "sparse": -0.45316877151943075,
      "asf": -0.6288789127599828,
      "rerank": 0.24557066594054153,
      "keyword_count": 2.3017686367112042,
      "filename_substr": 0.23993537449337002,
      "z_dense": 8.429488793540106
    },
    "cv_auc": 0.9720435208056062
  },
  "image": {
    "bias": -14.60996669554787,
    "weights": {
      "dense": 18.685683158519183,
      "sparse": 0.0,
      "asf": 0.0,
      "rerank": -0.16031691437198348,
      "keyword_count": 0.8556107243190912,
      "filename_substr": 0.0,
      "z_dense": 0.1316993799745668
    },
    "cv_auc": 0.924403295750577
  },
  "video": {
    "bias": -8.895608188774538,
    "weights": {
      "dense": 5.074154696351687,
      "sparse": 2.4317342636437282,
      "asf": 0.689245759320877,
      "rerank": 0.3335422321249685,
      "keyword_count": 1.5482683261929489,
      "filename_substr": 0.0,
      "z_dense": 2.1377800771240314
    },
    "cv_auc": 0.9859739008286554
  },
  "audio": {
    "bias": -3.5465850136724617,
    "weights": {
      "dense": -0.20191893567743044,
      "sparse": -1.397962388951068,
      "asf": 2.8652910171789805,
      "rerank": 0.524471692517123,
      "keyword_count": -1.5018787647246548,
      "filename_substr": -1.4197347432352112,
      "z_dense": 4.129938798825391
    },
    "cv_auc": 0.9887615347088985
  },
  "bgm": {
    "bias": -4.689838181135159,
    "weights": {
      "dense": 11.4131955617799,
      "sparse": 0.0,
      "asf": 0.0,
      "rerank": -0.016810260437010678,
      "keyword_count": 0.6640988442885793,
      "filename_substr": 0.0,
      "z_dense": 0.0
    },
    "cv_auc": 0.9122179730876736
  }
}
