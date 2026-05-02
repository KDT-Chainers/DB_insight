"""BGM identify 자가 테스트 — 102 mp4 → 자기 자신 매칭 검증.

각 mp4 를 engine.identify() 입력으로 사용:
  - method == 'chromaprint' && top1.filename == input 이면 ✓
  - method == 'clap' / 'clap_low' 이면 △ (CLAP 의미 매칭, exact 매칭 X)
  - top1.filename != input 이면 ✗

외부 API 호출 없음 (api_enabled=False 가정).

사용:
  FORCE_CPU=1 python scripts/bgm_selftest.py
  python scripts/bgm_selftest.py --first 10   # 처음 10개만
  python scripts/bgm_selftest.py --workers 1  # 직렬 (메모리 안전)

출력:
  logs/bgm_selftest_result.json
  logs/bgm_selftest_result.txt
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
APP_BACKEND = ROOT / "App" / "backend"
sys.path.insert(0, str(APP_BACKEND))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=int, default=0,
                        help="처음 N 개만 테스트 (0 = 전체 102)")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    print(f"[bgm_selftest] FORCE_CPU={os.environ.get('FORCE_CPU', '0')}", flush=True)
    t0 = time.time()

    from services.bgm import bgm_config
    from services.bgm.search_engine import get_engine

    engine = get_engine()
    if not engine.is_ready():
        print("[bgm_selftest] BGM 엔진 미준비 — 먼저 인덱싱 필요", flush=True)
        return 2

    raw_dir = bgm_config.RAW_BGM_DIR
    mp4s = sorted(raw_dir.glob("*.mp4"))
    if args.first > 0:
        mp4s = mp4s[: args.first]
    print(f"[bgm_selftest] 대상 {len(mp4s)} 파일", flush=True)

    results: list[dict] = []
    counts = {
        "chromaprint_match":   0,   # exact 매칭 성공
        "chromaprint_wrong":   0,   # exact 매칭이지만 다른 파일
        "clap_match":          0,   # CLAP top1 가 자기 자신
        "clap_wrong":          0,   # CLAP top1 가 다른 파일
        "method_failure":      0,   # identify 실패
    }

    for i, mp4 in enumerate(mp4s, 1):
        t1 = time.time()
        try:
            r = engine.identify(mp4, top_k=args.top_k, use_api_fallback=False)
        except Exception as e:
            counts["method_failure"] += 1
            results.append({"file": mp4.name, "error": str(e)[:200]})
            print(f"[{i:>3}/{len(mp4s)}] {mp4.name} — ERROR: {e}", flush=True)
            continue

        method = r.get("method", "?")
        items = r.get("results", [])
        top1 = items[0] if items else None
        top1_name = (top1.get("filename") or "") if top1 else ""

        is_match = (top1_name == mp4.name)
        score = top1.get("score") if top1 else None
        conf  = top1.get("confidence") if top1 else None

        if method == "chromaprint":
            if is_match:
                counts["chromaprint_match"] += 1
                tag = "✓ chromaprint exact"
            else:
                counts["chromaprint_wrong"] += 1
                tag = f"✗ chromaprint MISMATCH (got {top1_name})"
        elif method in ("clap", "clap_low"):
            if is_match:
                counts["clap_match"] += 1
                tag = f"△ {method} self-match"
            else:
                counts["clap_wrong"] += 1
                tag = f"✗ {method} MISMATCH (got {top1_name})"
        else:
            counts["method_failure"] += 1
            tag = f"✗ no method (got {method})"

        elapsed = time.time() - t1
        print(f"[{i:>3}/{len(mp4s)}] {mp4.name:<30} {tag:<55} "
              f"score={score} conf={conf} ({elapsed:.1f}s)",
              flush=True)

        results.append({
            "file":      mp4.name,
            "method":    method,
            "top1_name": top1_name,
            "top1_score": score,
            "top1_conf":  conf,
            "is_self":    is_match,
            "elapsed":    round(elapsed, 2),
        })

    elapsed_total = time.time() - t0
    n = len(results)
    summary = {
        "n_files":             n,
        "elapsed_sec":         round(elapsed_total, 1),
        **counts,
        "exact_rate":          round(counts["chromaprint_match"] / max(n, 1), 4),
        "any_self_rate":       round(
            (counts["chromaprint_match"] + counts["clap_match"]) / max(n, 1), 4
        ),
    }
    print()
    print("=" * 70)
    print("=== 결과 요약 ===")
    print("=" * 70)
    for k, v in summary.items():
        print(f"  {k:<25} {v}")

    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "bgm_selftest_result.json").write_text(
        json.dumps({"summary": summary, "results": results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    txt = []
    txt.append("=== BGM 자가 테스트 결과 ===")
    txt.append(f"파일 수: {n}, 소요: {elapsed_total:.0f}s")
    txt.append("")
    for k, v in counts.items():
        pct = v / max(n, 1) * 100
        txt.append(f"  {k:<25} {v:>4} ({pct:5.1f}%)")
    txt.append("")
    txt.append(f"  exact_rate (chromaprint):     {summary['exact_rate']:.1%}")
    txt.append(f"  any_self_rate (chroma+clap):  {summary['any_self_rate']:.1%}")
    txt.append("")
    txt.append("=== 실패 항목 ===")
    for r in results:
        if r.get("error"):
            txt.append(f"  ERROR  {r['file']}: {r['error']}")
        elif not r.get("is_self"):
            txt.append(f"  MISS   {r['file']:<30} → got {r.get('top1_name', '?')}")

    (log_dir / "bgm_selftest_result.txt").write_text(
        "\n".join(txt), encoding="utf-8"
    )
    print(f"\n저장: logs/bgm_selftest_result.{json,txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
