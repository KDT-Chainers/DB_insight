"""run_calibration.py — calibration.py 독립 실행 wrapper.

calibration.py 는 패키지 내 상대 import 사용으로 직접 실행 불가.
이 스크립트가 sys.path 를 설정한 뒤 recalibrate() 를 호출한다.

실행:
    python MR_TriCHEF/scripts/run_calibration.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# Windows cp949 회피 — em-dash 등 비ASCII 안전 출력
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "MR_TriCHEF"))

from pipeline.calibration import recalibrate

print("[calibration] Movie + Music null 분포 재측정 시작...")
result = recalibrate()

print("\n[calibration] 결과:")
for domain, d in result.items():
    if d.get("status") == "ok":
        print(f"  {domain}: mu={d['mu_null']:.4f}  sigma={d['sigma_null']:.4f}"
              f"  thr={d.get('abs_threshold', d.get('p95', 0)):.4f}"
              f"  n={d['n']}")
    else:
        print(f"  {domain}: {d}")

print("\n[calibration] 완료 — _calibration.json 저장됨")

# ── App/backend 통합: trichef_calibration.json 에도 merge ───────────────
#   MR_TriCHEF 는 MR_TriCHEF/pipeline/_calibration.json 에 쓰지만
#   App.backend.services.trichef.calibration 은 Data/embedded_DB/trichef_calibration.json
#   을 읽는다. 두 계열이 같은 movie/music 도메인을 공유하므로 동기화한다.
SHARED_PATH = _root / "Data" / "embedded_DB" / "trichef_calibration.json"
if SHARED_PATH.exists():
    try:
        shared = json.loads(SHARED_PATH.read_text(encoding="utf-8"))
    except Exception:
        shared = {}
else:
    shared = {}

for dom in ("movie", "music"):
    r = result.get(dom, {})
    if r.get("status") != "ok":
        continue
    entry = {
        "mu_null":       r["mu_null"],
        "sigma_null":    r["sigma_null"],
        "abs_threshold": r.get("abs_threshold", r.get("p95", 0.0)),
        "p95":           r.get("p95", 0.0),
        "p99":           r.get("p99", 0.0),
        "N":             r["n"],
        "method":        r.get("method",
                                "text_text_siglip2_null_v1" if dom == "music"
                                else "crossmodal_v1"),
    }
    if dom == "music":
        entry["note"] = ("Music Re=SigLIP2-text, same-encoder baseline high. "
                          "Do not cross-compare with cross-modal domains.")
    shared[dom] = entry

SHARED_PATH.parent.mkdir(parents=True, exist_ok=True)
SHARED_PATH.write_text(
    json.dumps(shared, ensure_ascii=False, indent=2), encoding="utf-8",
)
print(f"[calibration] synced → {SHARED_PATH}")
