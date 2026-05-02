"""G+H+I 통합: 동시 요청 + 에러 handling + 검색 정성 평가."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ["FORCE_CPU"] = "1"
os.environ["OMC_DISABLE_QWEN_PREWARM"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "App" / "backend"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("[p0p1] 엔진 로드 (CPU mode)...", flush=True)
t0 = time.time()
from routes.trichef import _get_engine
from services.bgm.search_engine import get_engine as get_bgm
engine = _get_engine()
bgm = get_bgm()
print(f"  로드 완료: {time.time()-t0:.1f}s\n", flush=True)


# ── G. 동시 요청 stress test ──────────────────────────────────────────
def stress_test():
    print("=== G. 동시 요청 stress test (10개 동시) ===", flush=True)
    queries = [("doc_page", "취업"), ("image", "고양이"), ("movie", "회의"),
               ("music", "안녕하세요"), ("bgm", "잔잔한"),
               ("doc_page", "예산"), ("image", "사람"), ("movie", "뉴스"),
               ("music", "방송"), ("bgm", "댄스")]

    def _do(domain_q):
        domain, q = domain_q
        t = time.time()
        try:
            if domain == "bgm":
                bgm.search(q, top_k=5)
            elif domain in ("movie", "music"):
                engine.search_av(q, domain=domain, topk=5)
            else:
                engine.search(q, domain=domain, topk=5, use_lexical=True, use_asf=True)
            return (domain, q, time.time() - t, None)
        except Exception as e:
            return (domain, q, time.time() - t, str(e)[:120])

    t_start = time.time()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(_do, q) for q in queries]
        results = [f.result() for f in as_completed(futs)]
    elapsed = time.time() - t_start
    n_err = sum(1 for r in results if r[3])
    times = [r[2] * 1000 for r in results]
    print(f"  10개 요청 동시 → 총 {elapsed*1000:.0f}ms (avg per-req {sum(times)/len(times):.0f}ms)", flush=True)
    print(f"  실패: {n_err}, 최단 {min(times):.0f}ms, 최장 {max(times):.0f}ms", flush=True)
    return {
        "n": len(results), "elapsed_ms": round(elapsed * 1000, 1),
        "avg_ms": round(sum(times) / len(times), 1),
        "errors": n_err,
    }


# ── H. 에러 handling 스트레스 ──────────────────────────────────────────
def error_handling():
    print("\n=== H. 에러 handling (edge cases) ===", flush=True)
    cases = [
        ("빈 쿼리", "doc_page", ""),
        ("매우 긴 쿼리 (1000자)", "image", "테스트 " * 200),
        ("특수문자 only", "doc_page", "@#$%^&*()"),
        ("SQL injection 시도", "image", "'; DROP TABLE users; --"),
        ("XSS 시도", "doc_page", "<script>alert('x')</script>"),
        ("null byte", "image", "test\x00query"),
        ("탭/개행", "doc_page", "test\tquery\n2"),
        ("emoji", "image", "🐱🌳🚀"),
        ("매우 짧음", "doc_page", "."),
        ("공백만", "image", "    "),
    ]
    results = []
    for name, domain, q in cases:
        t = time.time()
        try:
            if domain == "bgm":
                r = bgm.search(q, top_k=3)
                ok = isinstance(r, dict)
            else:
                hits = engine.search(q, domain=domain, topk=3, use_lexical=True, use_asf=True) if domain in ("doc_page", "image") else engine.search_av(q, domain=domain, topk=3)
                ok = True
            elapsed = (time.time() - t) * 1000
            mark = "✓"
            results.append({"case": name, "ok": True, "ms": round(elapsed, 1)})
            print(f"  {mark} {name:<30} ({elapsed:.0f}ms) — 핸들링 OK", flush=True)
        except Exception as e:
            elapsed = (time.time() - t) * 1000
            mark = "✗"
            results.append({"case": name, "ok": False, "error": str(e)[:80], "ms": round(elapsed, 1)})
            print(f"  {mark} {name:<30} ({elapsed:.0f}ms) — {type(e).__name__}: {str(e)[:60]}", flush=True)
    n_pass = sum(1 for r in results if r["ok"])
    print(f"\n  {n_pass}/{len(results)} 통과", flush=True)
    return results


# ── I. 검색 결과 정성 평가 ──────────────────────────────────────────
def quality_review():
    print("\n=== I. 검색 결과 정성 평가 (top-3 가독 출력) ===", flush=True)
    samples = [
        ("doc_page", "취업률"),
        ("doc_page", "예산 정책"),
        ("image", "산 풍경"),
        ("image", "회의 사진"),
        ("movie", "AI 기술"),
        ("music", "강의"),
        ("bgm", "잔잔한 피아노"),
        ("bgm", "신나는 댄스"),
    ]
    out_text = []
    for domain, q in samples:
        out_text.append(f"\n=== [{domain}] {q!r} ===")
        try:
            if domain == "bgm":
                r = bgm.search(q, top_k=3)
                for it in r.get("results", [])[:3]:
                    title = it.get("acr_title") or it.get("guess_title") or it["filename"]
                    artist = it.get("acr_artist") or it.get("guess_artist") or ""
                    segs = it.get("segments", [])
                    seg_str = f" segs={[s['label'] for s in segs[:2]]}" if segs else ""
                    out_text.append(f"  #{it['rank']} {artist} · {title}  conf={it['confidence']:.3f}{seg_str}")
            elif domain in ("movie", "music"):
                hits = engine.search_av(q, domain=domain, topk=3, top_segments=2)
                for i, h in enumerate(hits, 1):
                    seg = h.segments[0] if h.segments else {}
                    preview = (seg.get("text") or seg.get("preview") or "")[:60]
                    out_text.append(f"  #{i} {h.file_name[:50]}  conf={h.confidence:.3f}")
                    out_text.append(f"     {preview}")
            else:
                hits = engine.search(q, domain=domain, topk=3, use_lexical=True, use_asf=True)
                for i, h in enumerate(hits, 1):
                    out_text.append(f"  #{i} {h.id[:60]}  conf={h.confidence:.3f}")
        except Exception as e:
            out_text.append(f"  ERROR: {e}")

    Path(ROOT / "logs" / "search_quality_review.txt").write_text(
        "\n".join(out_text), encoding="utf-8"
    )
    print(f"  → logs/search_quality_review.txt 저장 ({len(out_text)} 줄)", flush=True)


# ── 실행 ──────────────────────────────────────────────────────────────
g_result = stress_test()
h_result = error_handling()
quality_review()

print("\n=== 종합 요약 ===", flush=True)
print(f"  G: 10개 동시 요청 평균 {g_result['avg_ms']}ms / 실패 {g_result['errors']}", flush=True)
print(f"  H: 10 edge case 중 {sum(1 for r in h_result if r['ok'])}/{len(h_result)} 통과", flush=True)
print(f"  I: logs/search_quality_review.txt 참조", flush=True)
