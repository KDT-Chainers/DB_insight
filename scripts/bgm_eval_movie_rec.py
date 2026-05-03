"""BGM 종합 성능 점검 — 옵션 A + B 통합 (GPU 우선).

A. 카탈로그 품질 평가 (텍스트 쿼리 × top-3 BGM)
   → logs/bgm_eval_catalog.txt — 사용자 청취용 가이드 (파일경로 포함)
B. Movie/Rec 샘플 → BGM identify 매칭 분포
   → logs/bgm_eval_movie_rec.json — Chromaprint/CLAP/None 분류

GPU 모드 자동 사용 (Qwen 종료 후이므로 안전).
"""
from __future__ import annotations
import json, os, random, sys, time
from pathlib import Path

# GPU 사용 (FORCE_CPU 환경변수 없을 시 cuda)
os.environ.pop("FORCE_CPU", None)
os.environ["OMC_DISABLE_QWEN_PREWARM"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


CATALOG_QUERIES = [
    "잔잔한 피아노",
    "신나는 댄스 음악",
    "슬픈 발라드",
    "classical orchestra",
    "어두운 분위기",
    "밝고 경쾌한 음악",
    "재즈",
    "전자 음악",
    "ambient mood",
    "vocal heavy song",
    "기악곡 instrumental",
    "fast tempo",
]


def opt_A_catalog_quality(bgm_engine):
    print("\n=== A. 카탈로그 품질 평가 (텍스트 쿼리 × top-3) ===\n", flush=True)
    out_lines = []
    out_lines.append("=== BGM 카탈로그 품질 평가 (사용자 청취 가이드) ===\n")
    out_lines.append(f"카탈로그: 102 BGM in raw_DB/Movie/정혜_BGM_1차/\n\n")
    out_lines.append("아래 각 쿼리의 top-3 BGM 을 청취하여 의미·분위기 적합성 평가하세요.\n")
    out_lines.append("재생: 파일경로 더블클릭 또는 앱 → BGM 검색 → 미니 player\n\n")
    out_lines.append("=" * 70 + "\n")

    raw_bgm_dir = ROOT / "Data" / "raw_DB" / "Movie" / "정혜_BGM_1차"

    for q in CATALOG_QUERIES:
        r = bgm_engine.search(q, top_k=3)
        results = r.get("results", [])
        out_lines.append(f"\n쿼리: {q!r}")
        conf_list = [f"{it['confidence']*100:.0f}%" for it in results]
        out_lines.append(f"  conf 분포: {conf_list}")
        for i, it in enumerate(results, 1):
            fname = it.get("filename", "")
            tags = ", ".join((it.get("tags") or [])[:3])
            params = it.get("params", {})
            bpm = params.get("tempo_bpm", 0)
            segs = it.get("segments") or []
            seg_str = ""
            if segs:
                top_seg = segs[0]
                seg_str = f"  [매칭 구간: {top_seg.get('label', '')}]"
            out_lines.append(f"  #{i} {fname}  tags={[tags] if tags else []}  BPM={bpm:.0f}{seg_str}")
            out_lines.append(f"      경로: {raw_bgm_dir / fname}")
        print(f"  [{q[:25]:<25}] top1={results[0]['filename'] if results else 'N/A'}", flush=True)

    Path(ROOT / "logs" / "bgm_eval_catalog.txt").write_text(
        "\n".join(out_lines), encoding="utf-8"
    )
    print(f"\n  → logs/bgm_eval_catalog.txt 저장 (사용자 청취 가이드)", flush=True)


def opt_B_movie_rec_identify(bgm_engine):
    print("\n=== B. Movie/Rec 샘플 → BGM identify 매칭 분포 ===\n", flush=True)
    raw_movie = ROOT / "Data" / "raw_DB" / "Movie"
    raw_rec = ROOT / "Data" / "raw_DB" / "Rec"

    # 샘플링 — 정혜_BGM_1차 제외
    movie_files = []
    if raw_movie.is_dir():
        for sub in raw_movie.iterdir():
            if sub.is_dir() and sub.name != "정혜_BGM_1차":
                movie_files.extend(sub.rglob("*.mp4"))
                movie_files.extend(sub.rglob("*.mkv"))
    rec_files = []
    if raw_rec.is_dir():
        rec_files = list(raw_rec.rglob("*.wav")) + list(raw_rec.rglob("*.mp3"))

    random.seed(42)
    movie_samples = random.sample(movie_files, min(20, len(movie_files)))
    rec_samples = random.sample(rec_files, min(20, len(rec_files)))

    print(f"  Movie 샘플: {len(movie_samples)}/{len(movie_files)}", flush=True)
    print(f"  Rec 샘플:   {len(rec_samples)}/{len(rec_files)}", flush=True)

    def _categorize(method, conf):
        if method == "chromaprint":
            return "chromaprint_exact"
        if method == "clap" and conf and conf >= 0.7:
            return "clap_high"
        if method == "clap" and conf and conf >= 0.5:
            return "clap_med"
        if method in ("clap", "clap_low"):
            return "clap_low"
        return "no_match"

    def _run(samples, label):
        print(f"\n  --- {label} ({len(samples)}건) ---", flush=True)
        results = []
        for i, p in enumerate(samples, 1):
            t = time.time()
            try:
                r = bgm_engine.identify(p, top_k=3, use_api_fallback=False)
                method = r.get("method", "?")
                items = r.get("results", [])
                top1 = items[0] if items else {}
                conf = top1.get("confidence")
                cat = _categorize(method, conf)
                elapsed = time.time() - t
                results.append({
                    "input":      p.name,
                    "method":     method,
                    "category":   cat,
                    "top1_match": top1.get("filename", ""),
                    "conf":       conf,
                    "elapsed_ms": round(elapsed * 1000, 1),
                })
                print(f"    [{i:2d}/{len(samples)}] {p.name[:40]:<40} → {cat} ({elapsed*1000:.0f}ms)",
                      flush=True)
            except Exception as e:
                results.append({"input": p.name, "error": str(e)[:120]})
                print(f"    [{i:2d}] ERROR: {e}", flush=True)
        return results

    movie_results = _run(movie_samples, "Movie")
    rec_results = _run(rec_samples, "Rec")

    # 분포 통계
    def _stats(results, label):
        cats = {"chromaprint_exact": 0, "clap_high": 0, "clap_med": 0,
                "clap_low": 0, "no_match": 0, "error": 0}
        for r in results:
            if r.get("error"):
                cats["error"] += 1
            else:
                cats[r["category"]] = cats.get(r["category"], 0) + 1
        n = len(results)
        return {
            "label": label,
            "n": n,
            **cats,
            "pct": {k: round(v / max(n, 1) * 100, 1) for k, v in cats.items()},
        }

    summary = {
        "movie": _stats(movie_results, "Movie"),
        "rec":   _stats(rec_results, "Rec"),
        "details": {"movie": movie_results, "rec": rec_results},
    }
    Path(ROOT / "logs" / "bgm_eval_movie_rec.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n  === 분포 ===", flush=True)
    for d in (summary["movie"], summary["rec"]):
        print(f"\n  [{d['label']}] n={d['n']}", flush=True)
        for k in ["chromaprint_exact", "clap_high", "clap_med", "clap_low", "no_match", "error"]:
            cnt = d[k]
            pct = d["pct"][k]
            print(f"    {k:<22}: {cnt:>3} ({pct}%)", flush=True)
    print(f"\n  → logs/bgm_eval_movie_rec.json 저장", flush=True)


def main():
    print("=== BGM 종합 성능 점검 시작 ===", flush=True)
    print(f"  GPU 사용: FORCE_CPU 미설정 ({os.environ.get('FORCE_CPU', 'cuda')})", flush=True)

    t0 = time.time()
    from services.bgm.search_engine import get_engine
    bgm = get_engine()
    print(f"  BGM 엔진 로드: {time.time()-t0:.1f}s", flush=True)
    print(f"  status: {bgm.status()}", flush=True)

    opt_A_catalog_quality(bgm)
    opt_B_movie_rec_identify(bgm)

    print(f"\n=== 완료 ({time.time()-t0:.0f}s 총) ===", flush=True)
    print(f"  logs/bgm_eval_catalog.txt   — 사용자 청취 가이드 (옵션 A)", flush=True)
    print(f"  logs/bgm_eval_movie_rec.json — 분포 통계 (옵션 B)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
