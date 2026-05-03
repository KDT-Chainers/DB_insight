"""routes/aimode.py — AIMODE 시각화 4-step QnA 엔드포인트.

흐름 (각 step 약 2초 시각화 지연 포함):
  Step 1: 검색어 추출 (Ollama qwen2.5:3b)
  Step 2: 데이터베이스 검색 → sources
  Step 3: 가장 관련된 카드 자동 선택
  Step 4: 답변 정리 (Ollama 스트리밍)

SSE 이벤트:
  {"type": "step", "step": 1, "label": "...", "query": "..."}
  {"type": "sources", "items": [...]}
  {"type": "step", "step": 3, "selected_idx": 0}
  {"type": "token", "text": "..."}
  {"type": "done", "answer": "...", "selected_idx": 0, "model": "qwen2.5:3b"}
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Annotated, Generator, TypedDict

from flask import Blueprint, Response, jsonify, request
import requests as _req

logger = logging.getLogger(__name__)
aimode_bp = Blueprint("aimode", __name__, url_prefix="/api/aimode")

OLLAMA_URL = "http://localhost:11434"
STEP_DELAY = 1.5   # 각 시각화 단계 사이 (초)


# ── LangGraph 통합 — 4-node 그래프 + MemorySaver (thread_id 별 대화 이력) ──
_LANGGRAPH_OK = False
_graph = None
_graph_lock = threading.Lock()


def _add_messages(left: list, right: list) -> list:
    """append-only 누적 reducer."""
    return (left or []) + (right or [])


try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

    class AImodeState(TypedDict):
        user_question: str
        extracted:     str
        topk:          int
        sources:       list[dict]
        selected_idx:  int
        answer:        str
        messages:      Annotated[list[BaseMessage], _add_messages]

    _LANGGRAPH_OK = True
except Exception as _e:
    logger.warning(f"[aimode] LangGraph 미사용 (폴백 모드): {_e}")


def _get_graph():
    """LangGraph 4-node 싱글턴.

    중요: graph.stream() 절대 사용 금지 (체크포인트 손상 위험).
    이 그래프는 MemorySaver 메모리 저장소로만 사용 — 노드는 schema용.
    실제 흐름은 _aimode_sse() 에서 직접 제어.
    """
    global _graph
    if not _LANGGRAPH_OK:
        return None
    if _graph is not None:
        return _graph
    with _graph_lock:
        if _graph is not None:
            return _graph

        def parse_intent_node(state):  # Step 1
            return {"extracted": state.get("extracted", "")}

        def retrieve_node(state):       # Step 2
            return {"sources": state.get("sources", [])}

        def select_node(state):         # Step 3
            return {"selected_idx": state.get("selected_idx", 0)}

        def generate_node(state):       # Step 4
            return {"answer": state.get("answer", "")}

        builder = StateGraph(AImodeState)
        builder.add_node("parse_intent", parse_intent_node)
        builder.add_node("retrieve",     retrieve_node)
        builder.add_node("select",       select_node)
        builder.add_node("generate",     generate_node)
        builder.add_edge(START, "parse_intent")
        builder.add_edge("parse_intent", "retrieve")
        builder.add_edge("retrieve",     "select")
        builder.add_edge("select",       "generate")
        builder.add_edge("generate", END)
        _graph = builder.compile(checkpointer=MemorySaver())
    return _graph


# ── 대화 이력 (LangGraph thread_id 기반, 폴백 dict) ─────────────────
_fallback_history: dict[str, list[dict]] = {}
_fallback_lock = threading.Lock()


def _load_history(thread_id: str) -> list[dict]:
    g = _get_graph()
    if g is not None:
        try:
            cfg = {"configurable": {"thread_id": thread_id}}
            st = g.get_state(cfg)
            if st and st.values:
                msgs = st.values.get("messages") or []
                out = []
                for m in msgs:
                    role = "user" if m.__class__.__name__ == "HumanMessage" else "assistant"
                    out.append({"role": role, "content": getattr(m, "content", "")})
                return out
        except Exception as e:
            logger.debug(f"[aimode] history load 실패: {e}")
    with _fallback_lock:
        return list(_fallback_history.get(thread_id, []))


def _save_state(thread_id: str, user_q: str, extracted: str,
                sources: list[dict], selected_idx: int, answer: str):
    g = _get_graph()
    if g is not None and _LANGGRAPH_OK:
        try:
            from langchain_core.messages import HumanMessage, AIMessage
            cfg = {"configurable": {"thread_id": thread_id}}
            g.update_state(cfg, {
                "user_question": user_q,
                "extracted":     extracted,
                "sources":       sources,
                "selected_idx":  selected_idx,
                "answer":        answer,
                "messages":      [HumanMessage(content=user_q), AIMessage(content=answer)],
            })
            return
        except Exception as e:
            logger.debug(f"[aimode] state save 실패, 폴백: {e}")
    with _fallback_lock:
        h = _fallback_history.setdefault(thread_id, [])
        h.append({"role": "user", "content": user_q})
        h.append({"role": "assistant", "content": answer})
        if len(h) > 40:
            _fallback_history[thread_id] = h[-40:]


def _clear_history(thread_id: str):
    g = _get_graph()
    if g is not None:
        try:
            cfg = {"configurable": {"thread_id": thread_id}}
            g.update_state(cfg, {
                "user_question": "", "extracted": "", "sources": [],
                "selected_idx": 0, "answer": "", "messages": [],
            })
        except Exception:
            pass
    with _fallback_lock:
        _fallback_history.pop(thread_id, None)


# ── Ollama 모델 자동 선택 ──────────────────────────────────────────
def _get_ollama_model() -> str | None:
    try:
        r = _req.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        models = r.json().get("models", [])
        preferred = ["qwen2.5", "llama3.2", "llama3", "mistral", "gemma3", "phi4"]
        for pref in preferred:
            for m in models:
                if pref in m.get("name", "").lower():
                    return m["name"]
        return models[0]["name"] if models else None
    except Exception:
        return None


# ── Ollama 단발 호출 (검색어 추출용) ─────────────────────────────────
def _ollama_oneshot(prompt: str, model: str) -> str:
    try:
        r = _req.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.1, "num_predict": 80}},
            timeout=30,
        )
        r.raise_for_status()
        return (r.json().get("response") or "").strip()
    except Exception as e:
        logger.warning(f"[aimode] Ollama oneshot 실패: {e}")
        return ""


def _ollama_stream(messages: list[dict], model: str) -> Generator[str, None, None]:
    try:
        with _req.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model":   model,
                "messages": messages,
                "stream":  True,
                "options": {"temperature": 0.3, "num_predict": 1024},
            },
            stream=True, timeout=180,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                tok = d.get("message", {}).get("content", "")
                if tok:
                    yield tok
                if d.get("done"):
                    break
    except Exception as e:
        logger.warning(f"[aimode] Ollama stream 실패: {e}")


# ── Step 1: 검색어 추출 ────────────────────────────────────────────
def _extract_query(user_question: str, model: str) -> str:
    prompt = (
        "다음 사용자 질문에서 데이터베이스 검색에 사용할 핵심 키워드만 추출해.\n"
        "조사·동사·접속사 빼고 명사 위주로, 5단어 이내, 한 줄.\n"
        "답변 외 다른 글자는 출력 금지.\n\n"
        f"질문: {user_question}\n\n"
        "검색어:"
    )
    extracted = _ollama_oneshot(prompt, model).split("\n")[0].strip()
    # 따옴표/괄호/콜론 제거
    extracted = extracted.replace('"', '').replace("'", '').replace("검색어:", "").strip()
    if not extracted or len(extracted) > 80:
        # fallback — 사용자 질문에서 의미 단어만
        import re
        tokens = re.findall(r"[가-힣A-Za-z0-9]+", user_question)
        meaningful = [t for t in tokens if len(t) >= 2 and t not in
                      ("문서에서", "찾아서", "정리해줘", "찾아줘", "알려줘", "해줘", "있는", "있을")]
        extracted = " ".join(meaningful[:5])
    return extracted or user_question


# ── Step 2: 검색 ────────────────────────────────────────────────────
def _do_search(query: str, topk: int = 5) -> list[dict]:
    """기존 search.py 엔드포인트 재사용 — 5도메인 통합 검색."""
    try:
        from routes.search import _search_trichef, _search_trichef_av
        from services.query_expand import expand_bilingual
        from services.score_adjust import adjust_confidence, _generous_curve

        eq = expand_bilingual(query)
        results = []
        results.extend(_search_trichef(eq, ["doc_page", "image"], topk))
        results.extend(_search_trichef_av(eq, ["movie", "music"], topk))

        # confidence 조정 (5도메인 통합 매핑)
        for r in results:
            if "confidence" in r and r["confidence"] is not None:
                r["confidence"] = round(adjust_confidence(r["confidence"], query), 4)
            if "dense" in r and r["dense"] is not None:
                r["dense"] = round(_generous_curve(r["dense"]), 4)

        results.sort(key=lambda x: -(x.get("confidence") or 0))
        return results[:topk]
    except Exception as e:
        logger.exception("[aimode] _do_search 실패")
        return []


# ── 시스템 프롬프트 ─────────────────────────────────────────────────
def _build_system_prompt(selected: dict, all_sources: list[dict]) -> str:
    domain_label = {"image": "이미지", "doc": "문서", "video": "동영상", "audio": "음성"}
    fname = selected.get("file_name") or "?"
    domain = domain_label.get(selected.get("file_type", ""), "파일")
    snippet = (selected.get("snippet") or "")[:600]
    fpath = selected.get("file_path") or ""

    other_lines = []
    for i, s in enumerate(all_sources, 1):
        is_sel = "★" if s is selected else " "
        other_lines.append(
            f"  {is_sel} [{i}] {s.get('file_name', '?')} "
            f"({domain_label.get(s.get('file_type', ''), s.get('file_type', ''))}, "
            f"{(s.get('confidence') or 0)*100:.0f}%)"
        )

    return f"""당신은 로컬 파일 데이터베이스 전문 AI 어시스턴트입니다.
사용자의 질문에 가장 관련된 [{domain}] 파일을 찾아서, 그 내용을 기반으로 한국어로 답변하세요.

가장 관련된 파일 (★ 선택됨):
{chr(10).join(other_lines)}

선택 파일 상세:
  이름: {fname}
  경로: {fpath}
  내용:
  ---
  {snippet if snippet else '(snippet 없음)'}
  ---

답변 원칙:
- 선택된 파일의 내용을 우선 참고하여 답변하세요.
- 인용 시 "[{1 if all_sources and all_sources[0] is selected else '?'}] {fname}" 형식으로 출처 표기.
- 검색 결과가 질문과 무관하다면 솔직히 말하세요.
- 한국어로 간결·명확하게."""


# ── 메인 SSE 제너레이터 (LangGraph 통합) ───────────────────────────
def _aimode_sse(query: str, topk: int, thread_id: str) -> Generator[str, None, None]:
    """
    흐름 (LangGraph thread_id 별 대화 이력 + 검색 sources 함께 LLM 에 전달):
      1. 검색어 추출 (LLM)
      2. 검색 → sources
      3. confidence 최상위 카드 선택
      4. system_prompt(sources + 이전 대화) + user_question → Ollama 스트리밍
      5. state 저장 (thread_id 별 히스토리)
    """
    def emit(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    model = _get_ollama_model()
    if not model:
        yield emit({"type": "error", "message": "Ollama 미연결 또는 모델 없음. ollama pull qwen2.5:3b 필요."})
        return

    # 시작 — LangGraph 상태 + thread_id 알림
    yield emit({
        "type": "info",
        "thread_id": thread_id,
        "langgraph": _LANGGRAPH_OK,
        "model": model,
    })

    # ── Step 1: 검색어 추출 ────────────────────────────────────────
    yield emit({"type": "step", "step": 1, "label": "🔍 질문에서 검색어 추출 중...",
                "model": model, "user_question": query})
    extracted = _extract_query(query, model)
    yield emit({"type": "step", "step": 1, "label": f"✓ 검색어: {extracted!r}",
                "query": extracted, "done": True})
    time.sleep(STEP_DELAY)

    # ── Step 2: 검색 ─────────────────────────────────────────────
    yield emit({"type": "step", "step": 2, "label": f"📚 데이터베이스에서 {extracted!r} 검색 중...",
                "query": extracted})
    sources = _do_search(extracted, topk=topk)
    yield emit({"type": "sources", "items": sources, "query": extracted})
    yield emit({"type": "step", "step": 2,
                "label": f"✓ {len(sources)}건 발견", "done": True})
    time.sleep(STEP_DELAY)

    if not sources:
        yield emit({"type": "error", "message": "검색 결과 없음 — 다른 질문을 시도해보세요."})
        return

    # ── Step 3: 가장 관련 카드 자동 선택 ──────────────────────────
    selected_idx = 0
    selected = sources[selected_idx]
    yield emit({
        "type": "step", "step": 3,
        "label": f"🎯 가장 관련된 결과 선택 (#{selected_idx+1})",
        "selected_idx": selected_idx,
        "selected_name": selected.get("file_name", ""),
    })
    time.sleep(STEP_DELAY)

    # ── Step 4: 답변 생성 — LangGraph 이전 대화 + 검색 sources 함께 ──
    yield emit({"type": "step", "step": 4, "label": "✨ 답변 정리 중...",
                "selected_idx": selected_idx})

    # 이전 대화 이력 로드 (LangGraph thread_id 기반)
    prior_history = _load_history(thread_id)

    sys_prompt = _build_system_prompt(selected, sources)
    messages = [{"role": "system", "content": sys_prompt}]
    # 최근 5턴 (user+assistant = 10 메시지)
    if prior_history:
        messages.extend(prior_history[-10:])
    messages.append({"role": "user", "content": query})

    full_answer = ""
    for tok in _ollama_stream(messages, model):
        full_answer += tok
        yield emit({"type": "token", "text": tok})

    # ── State 저장 (LangGraph MemorySaver) ───────────────────────
    _save_state(thread_id, query, extracted, sources, selected_idx, full_answer)

    yield emit({
        "type":         "done",
        "answer":       full_answer,
        "selected_idx": selected_idx,
        "model":        model,
        "extracted":    extracted,
        "thread_id":    thread_id,
        "history_used": len(prior_history),
        "langgraph":    _LANGGRAPH_OK,
    })


# ── Flask 엔드포인트 ───────────────────────────────────────────────
@aimode_bp.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    topk = max(1, min(int(body.get("topk", 5)), 10))
    thread_id = (body.get("thread_id") or "default").strip()
    if not query:
        return jsonify({"error": "query 필수"}), 400

    return Response(
        _aimode_sse(query, topk, thread_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@aimode_bp.delete("/chat/<thread_id>")
def clear_thread(thread_id: str):
    """대화 이력 초기화 — LangGraph state + 폴백 dict 모두 비움."""
    _clear_history(thread_id)
    return jsonify({"ok": True, "thread_id": thread_id})


@aimode_bp.get("/history/<thread_id>")
def history(thread_id: str):
    """LangGraph thread_id 기반 대화 이력 조회 (디버깅용)."""
    h = _load_history(thread_id)
    return jsonify({
        "thread_id": thread_id,
        "history":   h,
        "count":     len(h),
        "langgraph": _LANGGRAPH_OK,
    })


@aimode_bp.get("/status")
def status():
    model = _get_ollama_model()
    g = _get_graph()
    return jsonify({
        "ollama_model":     model,
        "ollama_available": model is not None,
        "step_delay_sec":   STEP_DELAY,
        "langgraph_ok":     _LANGGRAPH_OK,
        "graph_loaded":     g is not None,
    })
