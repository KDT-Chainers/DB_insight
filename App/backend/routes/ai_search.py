"""routes/ai_search.py — LangGraph 기반 에이전트 검색 (SSE 스트리밍).

POST /api/ai/search   { query, topk, max_iterations }
  → text/event-stream

흐름:
  1. 전체 도메인 초기 탐색  →  iteration_results(iteration=0, domain="all")
  2. 쿼리/결과 분석 → 도메인 선택  →  domain_selected
  3. 선택 도메인에서 반복 검색 (최대 max_iter 회)
     각 단계마다  →  iteration_results + thought
  4. 최종 결과  →  results
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Generator, Optional

from flask import Blueprint, Response, jsonify, request

from config import PATHS

logger = logging.getLogger(__name__)
ai_search_bp = Blueprint("ai_search", __name__, url_prefix="/api/ai")
SUPPORTED_GEMMA_MODELS = ("gemma3:12b", "gemma3:4b")


# ── 도메인 키워드 힌트 ────────────────────────────────────────────────────────
_DOMAIN_HINTS: dict[str, list[str]] = {
    "image":    ["사진", "이미지", "그림", "포토", "스크린샷", "photo", "image", "pic", "jpg", "png", "gif"],
    "doc_page": ["문서", "pdf", "자료", "보고서", "슬라이드", "워드", "엑셀", "ppt", "doc", "report"],
    "movie":    ["영상", "동영상", "비디오", "영화", "클립", "video", "movie", "mp4",
                 # [v1.1] 우주/과학 다큐 쿼리 → movie 도메인 힌트
                 # "코스모스 보이저호가 나오는 부분", "달 탐사 영상" 등 LLM 없이도 movie 선택
                 "다큐", "다큐멘터리", "방송", "뉴스", "시리즈", "episode", "ep",
                 "우주", "코스모스", "보이저", "탐사", "나사", "nasa", "space", "cosmos",
                 "장면", "부분", "구간", "씬", "scene", "나오는", "나온"],
    "music":    ["음악", "음성", "노래", "소리", "음원", "audio", "music", "mp3", "song"],
}

_DOMAIN_LABELS = {
    "image": "이미지", "doc_page": "문서", "movie": "동영상", "music": "음성",
}


def _guess_domain(query: str) -> Optional[str]:
    q = query.lower()
    for domain, hints in _DOMAIN_HINTS.items():
        if any(h in q for h in hints):
            return domain
    return None


# ── TRI-CHEF 검색 (멀티/단일 도메인 공통) ────────────────────────────────────
def _trichef_search(
    query: str, topk: int = 20, domains: list[str] | None = None
) -> list[dict]:
    """멀티 or 단일 도메인 검색 + 정규화·중복 제거."""
    from routes.trichef import _get_engine, _parse_doc_page_id

    engine = _get_engine()
    search_domains = domains if domains is not None else ["image", "doc_page", "movie", "music"]
    all_items: list[dict] = []

    for d in search_domains:
        try:
            if d in ("movie", "music"):
                # [fix] search.py 와 동일하게 쿼리 확장 후 검색.
                # expand_bilingual: "코스모스 보이저호" → "cosmos space universe Voyager Voyager spacecraft ..."
                # 확장 없이는 E13 보이저 세그먼트(0.889) 대신 E10 일반 코스모스(0.268) 가 나옴.
                try:
                    from services.query_expand import expand_bilingual as _qexp
                    _q_av = _qexp(query)
                except Exception:
                    _q_av = query
                av_res = engine.search_av(_q_av, domain=d, topk=topk, top_segments=5)
                for rank, r in enumerate(av_res, 1):
                    # [E13 fix] z-score CDF 인플레이션 방지:
                    # AV confidence 는 domain 내 상대 순위(CDF) 라서 비음악 쿼리에서도
                    # 80%+ 가 나와 도메인 선택 시 music 이 movie 를 눌러버림.
                    # raw_dense_agg (부스트 전 실제 cosine ≤1.0) 로 상한 설정.
                    _raw_dv = float(r.metadata.get("raw_dense_agg", 0.0))
                    _conf   = min(r.confidence, _raw_dv) if _raw_dv > 0 else r.confidence
                    all_items.append({
                        "rank": rank, "domain": d,
                        "id": r.file_path, "file_name": r.file_name,
                        "score": r.score, "confidence": round(_conf, 4),
                        "dense": r.score, "lexical": 0.0, "asf": 0.0,
                        "segments": r.segments,
                        "low_confidence": r.metadata.get("low_confidence", False),
                        "preview_url": None, "page_num": None, "source_path": "",
                    })
            else:
                res = engine.search(query, domain=d, topk=topk,
                                    use_lexical=True, use_asf=True, pool=300)
                for rank, r in enumerate(res, 1):
                    if d == "doc_page":
                        doc_info    = _parse_doc_page_id(r.id)
                        file_name   = doc_info["file_name"]
                        page_num    = doc_info["page_num"]
                        source_path = doc_info["source_path"]
                    else:
                        file_name   = Path(r.id).name
                        page_num    = None
                        source_path = (
                            str(Path(PATHS["RAW_DB"]) / "Img" / r.id)
                            if d == "image" else ""
                        )

                    all_items.append({
                        "rank": rank, "domain": d,
                        "id": r.id, "file_name": file_name,
                        "page_num": page_num, "source_path": source_path,
                        "score":      round(r.score, 4),
                        "confidence": round(r.confidence, 4),
                        "dense":      round(r.metadata.get("dense", r.score), 4),
                        "lexical":    round(r.metadata.get("lexical", 0.0), 4),
                        "asf":        round(r.metadata.get("asf", 0.0), 4),
                        "low_confidence": r.metadata.get("low_confidence", False),
                        "segments":   [],
                        "preview_url": f"/api/trichef/file?domain={d}&path={r.id}",
                    })
        except Exception as e:
            logger.warning(f"[ai_search] domain={d} 실패: {e}")

    # 중복 제거 — 이미지: 파일명 기준 1개 / 문서: 파일명 기준 최대 3페이지 유지
    _DOC_MAX_PAGES = 3
    seen_img: dict[str, dict] = {}
    seen_doc: dict[str, list[dict]] = {}
    other: list[dict] = []
    for item in all_items:
        if item["domain"] == "image":
            leaf = Path(item["id"]).name
            if leaf not in seen_img or item["confidence"] > seen_img[leaf]["confidence"]:
                seen_img[leaf] = item
        elif item["domain"] == "doc_page":
            key = item.get("file_name") or Path(item["id"]).name
            pages = seen_doc.setdefault(key, [])
            if len(pages) < _DOC_MAX_PAGES:
                pages.append(item)
                pages.sort(key=lambda x: -x["confidence"])
            elif item["confidence"] > pages[-1]["confidence"]:
                pages[-1] = item
                pages.sort(key=lambda x: -x["confidence"])
        else:
            other.append(item)

    merged = list(seen_img.values()) + [p for pages in seen_doc.values() for p in pages] + other
    merged.sort(key=lambda x: -x["confidence"])
    for i, it in enumerate(merged[:topk], 1):
        it["global_rank"] = i
    return merged[:topk]


# ── Ollama LLM ────────────────────────────────────────────────────────────────
def _is_supported_gemma_model(name: str) -> bool:
    lowered = name.lower()
    return any(model in lowered for model in SUPPORTED_GEMMA_MODELS)


def _get_ollama_model() -> Optional[str]:
    try:
        import requests as _req
        r = _req.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code == 200:
            models = r.json().get("models", [])
            preferred = ["qwen2.5", "llama3.2", "llama3", "mistral", "gemma3:12b", "gemma3:4b", "phi4", "phi"]
            for pref in preferred:
                for m in models:
                    name = m.get("name", "").lower()
                    if pref in name:
                        return m["name"]
            for m in models:
                name = m.get("name", "").lower()
                if name.startswith("gemma") and not _is_supported_gemma_model(name):
                    continue
                if name:
                    return m["name"]
    except Exception:
        pass
    return None


def _call_ollama(prompt: str, model: str) -> Optional[dict]:
    try:
        import requests as _req
        resp = _req.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False,
                  "keep_alive": 300,
                  "options": {"temperature": 0.1, "num_predict": 300}},
            timeout=45,
        )
        if resp.status_code != 200:
            return None
        text = resp.json().get("response", "").strip()
        m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        logger.debug(f"[ollama] 실패: {e}")
    return None


# ── 도메인 선택 ────────────────────────────────────────────────────────────────
def _build_domain_prompt(query: str, results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results[:8], 1):
        dom   = _DOMAIN_LABELS.get(r.get("domain", ""), r.get("domain", "?"))
        fname = r.get("file_name", "?")
        conf  = r.get("confidence", 0)
        lines.append(f"  {i}. [{dom}] {fname} — 신뢰도 {conf:.1%}")
    return f"""사용자 검색어: "{query}"

전체 도메인 초기 검색 결과:
{chr(10).join(lines) or "  (없음)"}

사용자가 원하는 파일 유형을 하나만 선택하세요:
- image:    사진·이미지
- doc_page: PDF·문서
- movie:    동영상
- music:    음성·음악

판단 우선순위:
1. 검색어에 사진/이미지/그림 → image
2. 검색어에 문서/자료/보고서 → doc_page
3. 검색어에 영상/동영상/비디오 → movie
4. 검색어에 음악/노래/음성 → music
5. 그 외 → 상위 결과에서 가장 관련성 높은 도메인

반드시 JSON만 (다른 텍스트 없이):
{{"domain": "image|doc_page|movie|music", "reason": "선택 이유를 한국어로"}}"""


def _heuristic_select_domain(query: str, results: list[dict]) -> dict:
    """쿼리 키워드 → 결과 분포 순으로 도메인 선택."""
    guessed = _guess_domain(query)
    if guessed:
        return {"domain": guessed,
                "reason": f"'{query}'에서 {_DOMAIN_LABELS.get(guessed, guessed)} 콘텐츠 의도를 감지했습니다"}

    domain_conf: dict[str, list[float]] = {}
    for r in results[:10]:
        d = r.get("domain", "")
        if d:
            domain_conf.setdefault(d, []).append(r.get("confidence", 0))

    if domain_conf:
        best = max(domain_conf, key=lambda d: sum(domain_conf[d]) / len(domain_conf[d]))
        avg  = sum(domain_conf[best]) / len(domain_conf[best])
        lbl  = _DOMAIN_LABELS.get(best, best)
        return {"domain": best,
                "reason": f"초기 결과 분석: {lbl} 도메인 평균 신뢰도 {avg:.1%}가 가장 높아 집중합니다"}

    return {"domain": "image", "reason": "기본값으로 이미지 도메인을 선택합니다"}


# ── 탑3 평가 ─────────────────────────────────────────────────────────────────
def _build_eval_prompt(
    original: str, current: str, iteration: int, domain: str, results: list[dict]
) -> str:
    domain_lbl = _DOMAIN_LABELS.get(domain, domain)
    lines = []
    for i, r in enumerate(results[:6], 1):
        fname = r.get("file_name", r.get("id", "?"))
        conf  = r.get("confidence", 0)
        page  = f" (p.{r['page_num']})" if r.get("page_num") else ""
        lines.append(f"  {i}. {fname}{page} — 신뢰도 {conf:.1%}")

    return f"""목표: "{original}" 관련 {domain_lbl} 파일이 상위 3위 안에 들도록 검색어를 개선합니다.

현재 검색어: "{current}" (도메인: {domain_lbl}, {iteration}회차)

결과 (상위 3개가 핵심):
{chr(10).join(lines) or "  (결과 없음)"}

판단:
- 상위 3개 결과가 "{original}"와 명확히 관련 있으면 done: true
- 관련 없거나 신뢰도 낮으면 done: false → new_query에 더 나은 한국어 검색어 제안

반드시 JSON만:
{{"done": true/false, "new_query": "...", "reason": "판단 이유를 한국어로"}}"""


def _heuristic_evaluate(
    original: str, current: str, iteration: int, results: list[dict]
) -> dict:
    if not results:
        return {"done": False, "new_query": f"{original} 관련 파일",
                "reason": "결과 없음 — 검색어를 확장합니다"}

    top3 = results[:3]
    top1 = results[0].get("confidence", 0)
    avg3 = sum(r.get("confidence", 0) for r in top3) / len(top3)
    top3_good = all(r.get("confidence", 0) >= 0.75 for r in top3)

    if top1 >= 0.85 or (avg3 >= 0.72 and top3_good):
        return {"done": True, "new_query": "",
                "reason": f"탑3 평균 신뢰도 {avg3:.1%} — 탑3 목표 달성! ✓"}

    words = original.split()
    strategies = [
        f"{original} 사진 이미지",
        f"{original} 문서 자료",
        " ".join(reversed(words)) if len(words) > 1 else f"{original} 관련",
        f"{original} 파일",
        original,
    ]
    new_q = strategies[min(iteration - 1, len(strategies) - 1)]
    return {"done": False, "new_query": new_q,
            "reason": f"탑3 평균 {avg3:.1%} (목표 미달) — 검색어 변형 #{iteration}으로 재시도"}


# ── SSE 에이전트 ──────────────────────────────────────────────────────────────
def _run_agent(query: str, topk: int, max_iter: int) -> Generator[str, None, None]:
    def emit(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    ollama_model = _get_ollama_model()
    yield emit({
        "type": "info",
        "text": f"LLM: {ollama_model}" if ollama_model else "LLM 없음 — 휴리스틱 모드",
        "has_llm": ollama_model is not None,
    })
    yield emit({"type": "start", "query": query})

    original_query = query
    history: list[dict] = []
    final_results: list[dict] = []

    # ─── Phase 1 : 전체 도메인 초기 탐색 ──────────────────────────────────
    yield emit({"type": "search", "iteration": 0, "query": query, "domain": "all"})
    try:
        global_results = _trichef_search(query, topk)
    except Exception as e:
        yield emit({"type": "error", "message": str(e)[:300]})
        return

    yield emit({
        "type":           "search_done",
        "iteration":      0,
        "query":          query,
        "count":          len(global_results),
        "top_confidence": round(global_results[0]["confidence"], 4) if global_results else 0.0,
        "domain":         "all",
    })
    # 전체 검색 결과 카드 전송
    yield emit({
        "type":      "iteration_results",
        "iteration": 0,
        "query":     query,
        "domain":    "all",
        "items":     global_results[:6],
    })

    # ─── Phase 2 : 도메인 선택 ─────────────────────────────────────────────
    domain_sel: dict = {}
    if ollama_model:
        llm_res = _call_ollama(_build_domain_prompt(query, global_results), ollama_model)
        if llm_res and "domain" in llm_res:
            domain_sel = llm_res
    if not domain_sel:
        domain_sel = _heuristic_select_domain(query, global_results)

    selected_domain = domain_sel.get("domain", "image")
    domain_reason   = domain_sel.get("reason", "")
    yield emit({"type": "domain_selected", "domain": selected_domain, "reason": domain_reason})

    # ─── Phase 3 : 단일 도메인 반복 검색 ──────────────────────────────────
    current_query = query

    for iteration in range(1, max_iter + 1):
        yield emit({
            "type":      "search",
            "iteration": iteration,
            "query":     current_query,
            "domain":    selected_domain,
        })
        try:
            results = _trichef_search(current_query, topk, domains=[selected_domain])
        except Exception as e:
            yield emit({"type": "error", "message": str(e)[:300]})
            return

        top_conf = results[0]["confidence"] if results else 0.0
        yield emit({
            "type":           "search_done",
            "iteration":      iteration,
            "query":          current_query,
            "count":          len(results),
            "top_confidence": round(top_conf, 4),
            "domain":         selected_domain,
        })
        # 이번 단계 결과 카드 전송
        yield emit({
            "type":      "iteration_results",
            "iteration": iteration,
            "query":     current_query,
            "domain":    selected_domain,
            "items":     results[:6],
        })

        # 평가
        yield emit({"type": "evaluating", "iteration": iteration})
        evaluation: Optional[dict] = None
        if ollama_model:
            evaluation = _call_ollama(
                _build_eval_prompt(original_query, current_query, iteration, selected_domain, results),
                ollama_model,
            )
        if evaluation is None:
            evaluation = _heuristic_evaluate(original_query, current_query, iteration, results)

        done      = bool(evaluation.get("done", False))
        new_query = (evaluation.get("new_query") or "").strip() or current_query
        reason    = evaluation.get("reason", "")

        history.append({
            "query":  current_query,
            "domain": selected_domain,
            "count":  len(results),
            "thought": reason,
            "done":   done,
        })
        yield emit({"type": "thought", "iteration": iteration, "text": reason, "done": done})
        final_results = results

        if done or iteration >= max_iter:
            break

        yield emit({
            "type":      "refine",
            "iteration": iteration + 1,
            "old_query": current_query,
            "new_query": new_query,
            "reason":    reason,
            "domain":    selected_domain,
        })
        current_query = new_query

    # ─── 최종 결과 ─────────────────────────────────────────────────────────
    yield emit({
        "type":             "results",
        "items":            final_results,
        "query":            original_query,
        "final_query":      current_query,
        "final_domain":     selected_domain,
        "total_iterations": len(history),
        "history":          history,
    })


# ── 엔드포인트 ────────────────────────────────────────────────────────────────
@ai_search_bp.post("/search")
def ai_search():
    body  = request.get_json(force=True)
    query = body.get("query", "").strip()
    if not query:
        return jsonify({"error": "query 필수"}), 400

    topk     = int(body.get("topk", 20))
    # [로딩 시간 단축] 최대 반복 횟수 5→3 으로 하향.
    # LLM 추론 1회 ≈ 10~15초 × (도메인 선택 + 반복 평가) → 30초+ 원인.
    # 3회로 줄여 최악 시나리오 ~30초 → ~20초.
    max_iter = max(1, min(int(body.get("max_iterations", 3)), 3))

    def generate():
        try:
            yield from _run_agent(query, topk, max_iter)
        except Exception as e:
            logger.exception("[ai_search] SSE 오류")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:300]}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
