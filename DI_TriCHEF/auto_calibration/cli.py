"""DI_TriCHEF/auto_calibration/cli.py

수동 실행용 자동 재캘리 러너. `incremental_runner.py` 훅 삽입 전 검증 단계에서
사용 — 현재 DB 로드 → 트리거 조건 확인 → 필요 시 `calibrate_domain` 호출.

실행:
    cd DB_insight
    python DI_TriCHEF/auto_calibration/cli.py                # dry-run (결정만 출력)
    python DI_TriCHEF/auto_calibration/cli.py --apply        # 실제 재캘리 수행
    python DI_TriCHEF/auto_calibration/cli.py --domain image --added 50 --apply

meta 파일: Data/embedded_DB/trichef_autocalib_meta.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "App" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auto_calibration.auto_recalibrate import maybe_recalibrate, should_recalibrate


def _meta_path() -> Path:
    from config import PATHS
    return Path(PATHS["EMBEDDED_DB"]) / "trichef_autocalib_meta.json"


def _load_meta() -> dict:
    p = _meta_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _save_meta(data: dict) -> None:
    p = _meta_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", choices=["image", "doc_page", "doc_text", "all"],
                    default="all")
    ap.add_argument("--added", type=int, default=0,
                    help="최근 추가/수정 건수 (incremental 에서 전달 가정).")
    ap.add_argument("--apply", action="store_true",
                    help="실제 재캘리 수행. 미지정 시 결정만 출력.")
    args = ap.parse_args()

    from routes.trichef import _get_engine
    engine = _get_engine()

    if args.domain == "all":
        domains = list(engine._cache.keys())
    else:
        domains = [args.domain]

    meta_all = _load_meta()
    any_change = False

    for dom in domains:
        cache = engine._cache.get(dom)
        if not cache:
            print(f"[auto-calib:{dom}] SKIP — 캐시 없음")
            continue
        Re, Im, Z = cache["Re"], cache["Im"], cache["Z"]
        total = int(Re.shape[0])
        meta = meta_all.get(dom, {"last_calibrated_N": 0})
        do, reason = should_recalibrate(args.added, total, meta.get("last_calibrated_N", 0))
        print(f"[auto-calib:{dom}] N={total}, added={args.added}, "
              f"last={meta.get('last_calibrated_N', 0)} → "
              f"{'RUN' if do else 'SKIP'} ({reason})")
        if do and args.apply:
            meta = maybe_recalibrate(dom, Re, Im, Z, args.added, meta)
            meta_all[dom] = meta
            any_change = True

    if args.apply and any_change:
        _save_meta(meta_all)
        print(f"[auto-calib] meta 저장 → {_meta_path()}")
    elif not args.apply:
        print("[auto-calib] (dry-run 모드. --apply 로 실제 수행)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
