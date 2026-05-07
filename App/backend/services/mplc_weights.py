"""MPLC Step 2 학습 결과 — 도메인별 logistic regression weights.

각 도메인의 final score = sigmoid(bias + Σ wᵢ · featureᵢ).
Cross-validation 으로 검증된 weights.
"""

FEATURES = ["dense", "sparse", "asf", "rerank", "keyword_count", "filename_substr", "z_dense"]

MPLC_WEIGHTS = {
  "doc": {
    "bias": -19.362504369511633,
    "weights": {
      "dense": 14.395949164192753,
      "sparse": 0.0,
      "asf": 0.0,
      "rerank": 0.0,
      "keyword_count": 0.0,
      "filename_substr": 0.27649356642688183,
      "z_dense": 8.496565670601615
    },
    "cv_auc": 0.9846142776847066
  },
  "image": {
    "bias": -13.417211543181955,
    "weights": {
      "dense": 17.795138620357996,
      "sparse": 0.0,
      "asf": 0.0,
      "rerank": 0.0,
      "keyword_count": 0.0,
      "filename_substr": 0.0,
      "z_dense": 0.31546925160688705
    },
    "cv_auc": 0.9208031849014648
  },
  "video": {
    "bias": -12.787251384075441,
    "weights": {
      "dense": 9.752628869180388,
      "sparse": 2.675342954425297,
      "asf": 0.8365524894689303,
      "rerank": 0.0,
      "keyword_count": 0.0,
      "filename_substr": 0.0,
      "z_dense": 1.5142504107381536
    },
    "cv_auc": 0.9863526112128598
  },
  "audio": {
    "bias": -9.238093717782512,
    "weights": {
      "dense": 0.5389755666434403,
      "sparse": 0.23367071498864747,
      "asf": 2.1823747511509715,
      "rerank": 0.0,
      "keyword_count": 0.0,
      "filename_substr": 0.0,
      "z_dense": 3.681575230023254
    },
    "cv_auc": 0.988926595958957
  },
  "bgm": {
    "bias": -5.781696122733409,
    "weights": {
      "dense": 12.542244344110797,
      "sparse": 0.0,
      "asf": 0.0,
      "rerank": 0.0,
      "keyword_count": 0.0,
      "filename_substr": 0.0,
      "z_dense": 0.0
    },
    "cv_auc": 0.9219988645931817
  }
}
