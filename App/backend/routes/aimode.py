"""routes/aimode.py — AIMODE RAG (Retrieval-Augmented Generation) 엔드포인트.

로컬 DB를 두뇌로 쓰는 RAG:
  1. Qwen 질문 의도 파악 → "~를 원하시는군요." + 키워드 추출
  2. 벡터 검색 → 후보 파일 카드 표시
  3. 파일별 전문 스캔 → scanning / found / not_found 애니메이션
  4. 컨텍스트 조립 + 출처 번호 부여
  5. Ollama 스트리밍 답변 (출처 인용)

SSE 이벤트:
  {"type": "info",        "model": "...", "thread_id": "..."}
  {"type": "intent",      "message": "...", "file_keywords": [...], "detail_keywords": [...]}
  {"type": "candidates",  "items": [...]}
  {"type": "scanning",    "index": N, "file_id": "...", "file_name": "..."}
  {"type": "scan_result", "index": N, "found": true/false, "chunks": [...]}
  {"type": "selected",    "sources": [...], "context_len": N}
  {"type": "token",       "text": "..."}
  {"type": "done",        "answer": "...", "model": "..."}
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

OLLAMA_URL  = "http://localhost:11434"
SCAN_DELAY  = 0.25   # 파일 스캔 간 UI 애니메이션 딜레이 (초)


# ── LangGraph 통합 (대화 이력 관리용) ─────────────────────────────
_LANGGRAPH_OK = False


def _add_messages(left: list, right: list) -> list:
    """append-only 누적 reducer."""
    return (left or []) + (right or [])


try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

    class RAGState(TypedDict):
        question:        str
        file_keywords:   list[str]
        detail_keywords: list[str]
        answer:          str
        messages:        Annotated[list[BaseMessage], _add_messages]

    _LANGGRAPH_OK = True
except Exception as _e:
    logger.warning(f"[aimode] LangGraph 미사용 (폴백 모드): {_e}")


# ── 대화 이력 (LangGraph thread 기반, 폴백 dict) ──────────────────
_fallback_history: dict[str, list[dict]] = {}
_fallback_lock = threading.Lock()
_history_graph = None
_history_graph_lock = threading.Lock()


def _get_history_graph():
    """대화 이력 저장 전용 단순 그래프."""
    global _history_graph
    if not _LANGGRAPH_OK:
        return None
    if _history_graph is not None:
        return _history_graph
    with _history_graph_lock:
        if _history_graph is not None:
            return _history_graph
        try:
            builder = StateGraph(RAGState)
            builder.add_node("store", lambda s: {})
            builder.add_edge(START, "store")
            builder.add_edge("store", END)
            _history_graph = builder.compile(checkpointer=MemorySaver())
        except Exception as _e:
            logger.warning(f"[aimode] history graph 생성 실패: {_e}")
    return _history_graph


def _load_history(thread_id: str) -> list[dict]:
    g = _get_history_graph()
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


def _save_history(thread_id: str, question: str, answer: str):
    g = _get_history_graph()
    if g is not None and _LANGGRAPH_OK:
        try:
            from langchain_core.messages import HumanMessage, AIMessage
            cfg = {"configurable": {"thread_id": thread_id}}
            g.update_state(cfg, {
                "question": question,
                "answer":   answer,
                "messages": [HumanMessage(content=question), AIMessage(content=answer)],
            })
            return
        except Exception as e:
            logger.debug(f"[aimode] history save 실패, 폴백: {e}")
    with _fallback_lock:
        h = _fallback_history.setdefault(thread_id, [])
        h.append({"role": "user",      "content": question})
        h.append({"role": "assistant", "content": answer})
        if len(h) > 40:
            _fallback_history[thread_id] = h[-40:]


def _clear_history(thread_id: str):
    g = _get_history_graph()
    if g is not None:
        try:
            cfg = {"configurable": {"thread_id": thread_id}}
            g.update_state(cfg, {"question": "", "answer": "", "messages": []})
        except Exception:
            pass
    with _fallback_lock:
        _fallback_history.pop(thread_id, None)


# ── Ollama 함수 ────────────────────────────────────────────────────
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


def _ollama_oneshot(prompt: str, model: str, num_predict: int = 150) -> str:
    try:
        r = _req.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.1, "num_predict": num_predict}},
            timeout=30,
        )
        r.raise_for_status()
        return (r.json().get("response") or "").strip()
    except Exception as e:
        logger.warning(f"[aimode] Ollama oneshot 실패: {e}")
        return ""


def _ollama_stream(messages: list[dict], model: str,
                   num_predict: int = 1024,
                   temperature: float = 0.3) -> Generator[str, None, None]:
    try:
        with _req.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model":    model,
                "messages": messages,
                "stream":   True,
                "options":  {"temperature": temperature, "num_predict": num_predict},
            },
            stream=True, timeout=600,
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


# ── RAG 의도 추출 ──────────────────────────────────────────────────
_STOPWORDS = frozenset((
    "문서에서", "문서", "이미지에서", "이미지", "영상에서", "영상", "음원에서", "음원",
    "파일에서", "파일", "내용을", "내용", "정보를", "정보",
    "찾아서", "찾아", "찾기", "찾을", "찾는", "찾아줘",
    "알려줘", "알려", "보여줘", "보여", "정리해줘", "정리",
    "해줘", "주세요", "주십시오", "있는", "있을", "있나", "있어",
    "입니다", "이다", "합니다", "하면", "하는", "하여", "되는", "됩니다",
    "이야", "이지", "이에요", "이고", "이랑", "것이", "것들",
    "하나요", "할까요", "이었", "했어", "했나", "했지",
    "에서", "에게", "에는", "한테", "에서는", "으로는", "에서의",
    "어디", "무엇", "어떤", "어떻게", "왜", "언제", "누가", "누구",
    "뭐야", "뭐더라", "뭐지", "뭔가", "뭐였", "뭐였지",
    "몇개", "몇개지", "몇가지", "몇명", "몇번", "몇개야",
    "얼마나", "얼마", "얼마야",
))


def _extract_rag_intent(question: str, model: str) -> tuple[str, list[str], list[str]]:
    """질문 → (의도메시지, 파일검색_키워드_list, 내용검색_키워드_list)

    Ollama 에게 아래 3줄 형식 출력을 요청:
      의도메시지: ~를 원하시는군요.
      파일검색: 키워드1 키워드2
      내용검색: 키워드1 키워드2
    """
    import re as _re

    prompt = (
        "사용자 질문의 의도를 파악하고 아래 형식으로만 출력해. 다른 글자 절대 금지.\n\n"
        "의도메시지: (질문자가 원하는 것을 '~를/을 원하시는군요.' 형식 한 문장으로)\n"
        "파일검색: (어떤 파일을 찾을지, 고유명사·주제어 위주, 최대 4단어)\n"
        "내용검색: (파일 안에서 찾을 핵심 키워드, 최대 3단어)\n\n"
        "예시1)\n"
        "질문: 김라민 생년월일 뭐더라\n"
        "의도메시지: 김라민의 생년월일을 알고 싶으신군요.\n"
        "파일검색: 김라민\n"
        "내용검색: 김라민 생년월일\n\n"
        "예시2)\n"
        "질문: 경주 동궁 월지 문서에서 유구가 몇개야\n"
        "의도메시지: 경주 동궁 월지 관련 문서에서 유구의 수를 알고 싶으신군요.\n"
        "파일검색: 경주 동궁 월지\n"
        "내용검색: 유구\n\n"
        "예시3)\n"
        "질문: 나이테 PDF에서 탄소 측정 방법 알려줘\n"
        "의도메시지: 나이테 관련 문서에서 탄소 측정 방법을 알고 싶으신군요.\n"
        "파일검색: 나이테 탄소\n"
        "내용검색: 탄소 측정\n\n"
        f"질문: {question}\n"
        "의도메시지:"
    )

    raw = _ollama_oneshot(prompt, model, num_predict=150)

    def _parse_line(text: str, label: str) -> str:
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith(label):
                val = line[len(label):].strip().strip(":")
                return val.replace('"', '').replace("'", '').strip()
        return ""

    # "의도메시지:" 가 prompt 마지막에 붙어있으므로 raw 앞에 붙여서 파싱
    full       = f"의도메시지:{raw}"
    intent_msg = _parse_line(full, "의도메시지")
    file_q     = _parse_line(full, "파일검색")
    content_q  = _parse_line(full, "내용검색")

    def _to_list(s: str) -> list[str]:
        return [w for w in _re.findall(r"[가-힣A-Za-z0-9]{2,}", s)
                if w not in _STOPWORDS]

    # Fallback — Ollama 실패 시 STOPWORDS 기반
    if not file_q:
        tokens = _re.findall(r"[가-힣A-Za-z0-9]+", question)
        meaningful = [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS]
        file_q    = " ".join(meaningful[:4])
        content_q = " ".join(meaningful[:2])

    if not intent_msg:
        intent_msg = f"{file_q or question}에 대해 알고 싶으신군요."

    return (
        intent_msg,
        _to_list(file_q) or _to_list(question),
        _to_list(content_q) or _to_list(file_q),
    )


# ── RAG 파일 스캔 ──────────────────────────────────────────────────
def _scan_file_for_keywords(
    source: dict,
    keywords: list[str],
    max_chars: int = 80000,
) -> tuple[bool, list[str]]:
    """source 파일 전문에서 keywords 검색 → (found, [chunk_snippets]).

    doc  : _read_source_full_text 로 전문 추출
    기타 : snippet 기반 처리 (이미지/영상/음악)
    각 chunk 는 키워드 주변 ±250자 텍스트.
    """
    import re as _re

    file_type = source.get("file_type", "")

    if file_type == "doc":
        full_text = _read_source_full_text(source, max_chars=max_chars)
    else:
        full_text = source.get("snippet") or ""

    if not full_text or not keywords:
        return False, []

    text_lower = full_text.lower()
    found_chunks: list[str] = []
    seen_positions: set[int] = set()

    for kw in keywords:
        kw_lower = kw.lower()
        start = 0
        while True:
            pos = text_lower.find(kw_lower, start)
            if pos < 0:
                break
            # 250자 내 중복 위치 skip
            if not any(abs(pos - p) < 250 for p in seen_positions):
                seen_positions.add(pos)
                c_start = max(0, pos - 200)
                c_end   = min(len(full_text), pos + len(kw) + 200)
                chunk   = full_text[c_start:c_end].strip()
                chunk   = _re.sub(r'\n{3,}', '\n\n', chunk)
                if chunk:
                    found_chunks.append(chunk)
            start = pos + 1
            if len(found_chunks) >= 3:
                break

    return len(found_chunks) > 0, found_chunks[:3]


# ── RAG 컨텍스트 조립 ─────────────────────────────────────────────
def _build_rag_context(matched_sources: list[dict]) -> str:
    """매칭된 파일들의 청크 → LLM 컨텍스트 문자열 (출처 번호 포함)."""
    parts = []
    for i, src in enumerate(matched_sources, 1):
        fname  = src.get("file_name") or "?"
        chunks = src.get("matched_chunks") or [src.get("snippet") or ""]
        content = "\n...\n".join(c.strip() for c in chunks if c.strip())
        if content:
            parts.append(f"[출처{i}: {fname}]\n{content}")
    return "\n\n".join(parts)


def _build_rag_messages(
    question: str,
    context: str,
    matched_sources: list[dict],
    prior_history: list[dict],
) -> list[dict]:
    """RAG 시스템 프롬프트 + 대화 이력 + 사용자 질문 → messages 리스트."""
    source_list = "\n".join(
        f"  [출처{i+1}] {s.get('file_name', '?')} ({s.get('file_type', '?')})"
        for i, s in enumerate(matched_sources)
    )
    sys_msg = f"""당신은 로컬 파일 데이터베이스 전문 AI 어시스턴트입니다.
아래 파일 내용을 참고하여 한국어로 답변하세요.

참고 파일:
{source_list if source_list else '  (매칭 파일 없음 — 일반 지식으로 답변)'}

파일 내용:
{context if context else '(본문 없음)'}

답변 원칙:
• 파일 내용을 직접 인용하면서 사용자 질문에 답변하세요.
• 출처는 [출처N] 형식으로 인용하세요. 예: "유구는 총 5개입니다. [출처1]"
• 마크다운 문법 일체 금지 (별표 **, 헤딩 #, 백틱 ` 절대 금지).
• 항목 정리는 번호(1. 2.) 또는 점(•)만 사용.
• 한국어로 간결·명확하게 작성하세요."""

    messages: list[dict] = [{"role": "system", "content": sys_msg}]
    if prior_history:
        messages.extend(prior_history[-10:])
    messages.append({"role": "user", "content": question})
    return messages


# ── 메인 RAG SSE 제너레이터 ───────────────────────────────────────
def _rag_sse(question: str, topk: int, thread_id: str) -> Generator[str, None, None]:
    """RAG 전체 파이프라인 SSE 스트림.

    단계:
      0. Ollama 연결 확인
      1. 의도 파악 + 키워드 추출 → intent 이벤트
      2. 벡터 검색 → candidates 이벤트
      3. 파일별 내용 스캔 → scanning / scan_result 이벤트
      4. 컨텍스트 조립 → selected 이벤트
      5. Ollama 스트리밍 답변 → token / done 이벤트
    """
    from concurrent.futures import ThreadPoolExecutor

    def emit(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    # ── 0. Ollama 연결 확인 ────────────────────────────────────────
    model = _get_ollama_model()
    if not model:
        yield emit({"type": "error",
                    "message": "Ollama 미연결. 'ollama pull qwen2.5:3b' 실행 후 재시도."})
        return

    yield emit({"type": "info", "model": model, "thread_id": thread_id,
                "langgraph": _LANGGRAPH_OK})

    # ── 1. 의도 파악 + 키워드 추출 ────────────────────────────────
    intent_msg, file_kws, detail_kws = _extract_rag_intent(question, model)
    file_query = " ".join(file_kws) if file_kws else question

    yield emit({
        "type":            "intent",
        "message":         intent_msg,
        "file_keywords":   file_kws,
        "detail_keywords": detail_kws,
    })
    time.sleep(0.5)

    # ── 2. 벡터 검색 ──────────────────────────────────────────────
    candidates = _do_search(file_query, topk=topk)
    if not candidates:
        # 원본 질문으로 재시도
        candidates = _do_search(question, topk=topk)

    yield emit({"type": "candidates", "items": candidates})

    if not candidates:
        yield emit({"type": "error", "message": "검색 결과 없음 — 다른 질문을 시도해보세요."})
        return

    time.sleep(0.4)

    # ── 3. 파일별 내용 스캔 (병렬 실행, 순서대로 이벤트 방출) ──────
    scan_futures = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        for src in candidates:
            f = executor.submit(_scan_file_for_keywords, src, detail_kws)
            scan_futures.append(f)

        matched_sources: list[dict] = []

        for i, (src, fut) in enumerate(zip(candidates, scan_futures)):
            file_id   = src.get("trichef_id") or str(i)
            file_name = src.get("file_name")  or "?"
            file_type = src.get("file_type")  or "?"

            yield emit({
                "type":      "scanning",
                "index":     i,
                "file_id":   file_id,
                "file_name": file_name,
                "file_type": file_type,
            })

            try:
                found, chunks = fut.result(timeout=15)
            except Exception as _e:
                logger.debug(f"[rag] scan 실패 {file_name}: {_e}")
                found, chunks = False, []

            yield emit({
                "type":    "scan_result",
                "index":   i,
                "file_id": file_id,
                "found":   found,
                "chunks":  chunks,
            })

            if found:
                matched_sources.append({**src, "matched_chunks": chunks})

            time.sleep(SCAN_DELAY)

    # ── 4. 매칭 파일 없으면 confidence 1위 fallback ─────────────
    if not matched_sources:
        logger.info("[rag] 키워드 매칭 없음 → confidence 1위 fallback")
        best = candidates[0]
        matched_sources = [{**best, "matched_chunks": [best.get("snippet") or ""]}]

    # ── 5. 컨텍스트 조립 ──────────────────────────────────────────
    context = _build_rag_context(matched_sources)

    yield emit({
        "type":        "selected",
        "sources":     matched_sources,
        "context_len": len(context),
    })
    time.sleep(0.3)

    # ── 6. Ollama 스트리밍 답변 ────────────────────────────────────
    prior_history = _load_history(thread_id)
    messages      = _build_rag_messages(question, context, matched_sources, prior_history)

    full_answer  = ""
    stream_error: str | None = None
    t_stream = time.time()
    try:
        for tok in _ollama_stream(messages, model):
            full_answer += tok
            yield emit({"type": "token", "text": tok})
    except Exception as e:
        stream_error = str(e)
        logger.warning(f"[rag] stream 중단: {e}")

    # ── 7. 이력 저장 ──────────────────────────────────────────────
    if full_answer and len(full_answer.strip()) >= 10 and not stream_error:
        _save_history(thread_id, question, full_answer)

    try:
        logger.info(
            f"[rag] q={question[:40]!r} file_kws={file_kws} detail_kws={detail_kws} "
            f"candidates={len(candidates)} matched={len(matched_sources)} "
            f"answer_len={len(full_answer)} dt={time.time()-t_stream:.2f}s"
        )
    except Exception:
        pass

    yield emit({
        "type":          "done",
        "answer":        full_answer,
        "model":         model,
        "thread_id":     thread_id,
        "sources_count": len(matched_sources),
        "history_used":  len(prior_history),
        "error":         stream_error,
    })


# ── Flask 엔드포인트 ───────────────────────────────────────────────
_THREAD_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_\-]{1,64}$")


@aimode_bp.post("/chat")
def chat():
    body      = request.get_json(silent=True) or {}
    question  = (body.get("query") or "").strip()
    topk      = max(1, min(int(body.get("topk", 5)), 10))
    thread_id = (body.get("thread_id") or "default").strip()
    if not _THREAD_ID_RE.match(thread_id):
        thread_id = "default"
    if not question:
        return jsonify({"error": "query 필수"}), 400

    return Response(
        _rag_sse(question, topk, thread_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@aimode_bp.delete("/chat/<thread_id>")
def clear_thread(thread_id: str):
    """대화 이력 초기화."""
    _clear_history(thread_id)
    return jsonify({"ok": True, "thread_id": thread_id})


@aimode_bp.get("/history/<thread_id>")
def history(thread_id: str):
    """대화 이력 조회 (디버깅용)."""
    h = _load_history(thread_id)
    return jsonify({"thread_id": thread_id, "history": h, "count": len(h),
                    "langgraph": _LANGGRAPH_OK})


@aimode_bp.get("/status")
def status():
    model = _get_ollama_model()
    return jsonify({
        "ollama_model":     model,
        "ollama_available": model is not None,
        "scan_delay_sec":   SCAN_DELAY,
        "langgraph_ok":     _LANGGRAPH_OK,
    })


# ══════════════════════════════════════════════════════════════════════
# 아래: 검색·스니펫·요약 헬퍼 (변경 없음)
# ══════════════════════════════════════════════════════════════════════

# ── doc snippet LRU 캐시 ─────────────────────────────────────────
from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=1024)
def _cached_doc_snippet(rid: str) -> str:
    """doc_page rid → page_text 첫 800자 캐시 (LRU=1024)."""
    try:
        from config import PATHS
        from pathlib import Path
        import re
        m = re.match(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$", rid)
        if not m:
            return ""
        stem, page_num = m.group(1), int(m.group(2))
        pt = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text" / stem / f"p{page_num:04d}.txt"
        if pt.is_file():
            return pt.read_text(encoding="utf-8").strip()[:800]

        try:
            import fitz as _fitz
            from config import PATHS as _PATHS
            from pathlib import Path as _Path
            _pdf_path = None

            from services.trichef.lexical_rebuild import resolve_doc_pdf_map
            _candidate = resolve_doc_pdf_map().get(stem)
            if _candidate and _candidate.suffix.lower() == ".pdf" and _candidate.exists():
                _pdf_path = _candidate

            if _pdf_path is None and _candidate:
                _conv_root = _Path(_PATHS["TRICHEF_DOC_EXTRACT"]) / "converted_pdf"
                _want = _candidate.stem + ".pdf"
                if _conv_root.is_dir():
                    for _sub in _conv_root.iterdir():
                        _c = _sub / _want
                        if _c.exists():
                            _pdf_path = _c
                            break

            if _pdf_path:
                with _fitz.open(str(_pdf_path)) as _doc:
                    if page_num < len(_doc):
                        _t = _doc[page_num].get_text("text").strip()
                        if _t:
                            pt.parent.mkdir(parents=True, exist_ok=True)
                            pt.write_text(_t, encoding="utf-8")
                            return _t[:800]
        except Exception:
            pass
    except Exception:
        pass
    return ""


@_lru_cache(maxsize=512)
def _cached_image_caption(rid: str, query: str = "") -> str:
    """image rid → Qwen 5-stage caption 결합 캐시."""
    try:
        from services.location_resolver import _img_location
        loc = _img_location(rid, query=query) or {}
        parts = [loc.get(k, "") for k in ("title", "tagline", "synopsis")]
        txt = " | ".join(p.strip() for p in parts if p and p.strip())
        if txt:
            return txt[:600]
        return (loc.get("caption") or "")[:600]
    except Exception:
        return ""


def _enrich_snippet(r: dict, query: str) -> None:
    """LLM 에 전달할 snippet 채우기 (doc_page 는 PDF page text 직접 로드)."""
    if r.get("snippet"):
        return
    file_type = r.get("file_type", "")
    rid = r.get("trichef_id") or ""
    if file_type == "doc" and rid:
        t = _cached_doc_snippet(rid)
        if t:
            r["snippet"] = t
            return
    elif file_type == "image" and rid:
        t = _cached_image_caption(rid, query)
        if t:
            r["snippet"] = t
            return
    # 미지원 타입 fallback
    try:
        from config import PATHS
        from pathlib import Path
        import re

        if file_type == "doc" and rid:
            m = re.match(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$", rid)
            if m:
                stem, page_num = m.group(1), int(m.group(2))
                pt = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text" / stem / f"p{page_num:04d}.txt"
                if pt.is_file():
                    txt = pt.read_text(encoding="utf-8").strip()
                    if txt:
                        r["snippet"] = txt[:800]
                        return
        elif file_type == "image":
            from services.location_resolver import _img_location
            loc = _img_location(rid, query=query) or {}
            parts = [loc.get(k, "") for k in ("title", "tagline", "synopsis")]
            txt = " | ".join(p.strip() for p in parts if p and p.strip())
            if txt:
                r["snippet"] = txt[:600]
                return
            if loc.get("caption"):
                r["snippet"] = loc["caption"][:600]
    except Exception as e:
        logger.debug(f"[aimode] enrich_snippet 실패: {e}")


def _do_search(query: str, topk: int = 5) -> list[dict]:
    """TRI-CHEF 파이프라인 인라인 재현 — 도메인 quota + cross-encoder + snippet 보강."""
    try:
        from routes.search import (
            _search_trichef, _search_trichef_av,
            _search_legacy_video, _search_legacy_audio,
            _search_bgm,
        )
        from services.query_expand import expand_bilingual
        from services.score_adjust import adjust_confidence, _generous_curve
        from services.rerank_adapter import maybe_rerank
        from services.location_resolver import extract_location
        from concurrent.futures import ThreadPoolExecutor

        eq = expand_bilingual(query)

        with ThreadPoolExecutor(max_workers=5) as ex:
            f_img = ex.submit(_search_trichef,    eq, ["image"],    topk)
            f_doc = ex.submit(_search_trichef,    eq, ["doc_page"], topk)
            f_mov = ex.submit(_search_trichef_av, eq, ["movie"],    topk)
            f_mus = ex.submit(_search_trichef_av, eq, ["music"],    topk)
            f_bgm = ex.submit(_search_bgm,        eq, topk)
            img_only = f_img.result() or []
            doc_only = f_doc.result() or []
            video    = f_mov.result() or []
            audio    = f_mus.result() or []
            bgm      = f_bgm.result() or []

        if not video:
            try: video = _search_legacy_video(eq, topk) or []
            except Exception: pass
        if not audio:
            try: audio = _search_legacy_audio(eq, topk) or []
            except Exception: pass

        for lst in (img_only, doc_only, video, audio, bgm):
            lst.sort(key=lambda r: r.get("confidence", 0), reverse=True)
        quota = max(1, topk // 4)
        guaranteed: list[dict] = []
        for lst in (doc_only, img_only, video, audio, bgm):
            guaranteed.extend(lst[:quota])
        _DW = {"image": 1.0, "doc": 1.0, "video": 0.75, "audio": 0.75, "bgm": 0.75}
        extras: list[dict] = []
        for lst in (img_only, doc_only, video, audio, bgm):
            extras.extend(lst[quota:])
        extras.sort(
            key=lambda r: r.get("confidence", 0) * _DW.get(r.get("file_type", ""), 1.0),
            reverse=True,
        )
        results = (guaranteed + extras)[:topk * 2]

        results = maybe_rerank(query, results)

        from services.score_adjust import apply_query_penalty
        for r in results:
            if r.get("file_type") == "bgm":
                for f in ("confidence", "similarity"):
                    if f in r and r[f] is not None:
                        r[f] = round(min(0.75, float(r[f])), 4)
                continue
            for f in ("confidence", "similarity"):
                if f in r and r[f] is not None:
                    r[f] = round(apply_query_penalty(float(r[f]), query), 4)
            if "dense" in r and r["dense"] is not None:
                r["dense"] = round(_generous_curve(r["dense"]), 4)

        for r in results:
            try:
                loc = extract_location(r, query=query)
                if loc is not None:
                    r["location"] = loc
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(_enrich_snippet, r, query) for r in results]
            for f in futs:
                try: f.result(timeout=5)
                except Exception: pass

        return results[:topk]
    except Exception:
        logger.exception("[aimode] _do_search 실패")
        return []


def _read_source_full_text(source: dict, max_chars: int = 60000) -> str:
    """검색 결과 source 의 file_path 로 직접 파일 텍스트 추출.

    우선순위:
      1) page_text/<stem>/p*.txt 캐시
      2) file_path 가 .pdf → fitz 직접 읽기 + 캐시 저장
      3) docx/hwp 등 → converted_pdf/ 에서 변환본 탐색 → fitz
      4) python-docx fallback (.docx)
      5) 텍스트 파일 직접 읽기
    이미지/영상/음악 도메인은 '' 반환.
    """
    from pathlib import Path
    import re

    file_type = source.get("file_type", "")
    if file_type in {"image", "video", "audio", "bgm"}:
        return ""

    file_path = (source.get("file_path") or "").strip()
    if not file_path:
        return ""

    fp  = Path(file_path)
    ext = fp.suffix.lower()

    # ── 1순위: page_text/<stem>/p*.txt 캐시 ─────────────────────
    rid = source.get("trichef_id") or ""
    m = re.match(r"^page_images/(.+)/p\d+\.(?:jpg|png)$", rid)
    if m:
        try:
            from config import PATHS
            stem = m.group(1)
            page_text_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text" / stem
            if page_text_dir.is_dir():
                pages = sorted(page_text_dir.glob("p*.txt"),
                               key=lambda p: int(p.stem[1:]))
                texts = []
                total = 0
                for tp in pages:
                    try:
                        t = tp.read_text(encoding="utf-8").strip()
                        if t:
                            texts.append(t)
                            total += len(t)
                            if total >= max_chars:
                                break
                    except Exception:
                        continue
                if texts:
                    return "\n".join(texts)[:max_chars]
        except Exception:
            pass

    # ── 2순위: PDF → fitz ───────────────────────────────────────
    if ext == ".pdf":
        if fp.exists() and fp.stat().st_size > 0:
            try:
                import fitz
                texts = []
                total = 0
                pt_dir = None
                if m:
                    try:
                        from config import PATHS
                        pt_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text" / m.group(1)
                        pt_dir.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pt_dir = None
                with fitz.open(str(fp)) as doc:
                    for i, page in enumerate(doc):
                        t = page.get_text("text") or ""
                        t = t.strip()
                        if t:
                            texts.append(t)
                            total += len(t)
                            if pt_dir:
                                try:
                                    (pt_dir / f"p{i:04d}.txt").write_text(t, encoding="utf-8")
                                except Exception:
                                    pass
                        if total >= max_chars:
                            break
                return "\n".join(texts)[:max_chars]
            except Exception as e:
                logger.debug(f"[read_source] fitz 실패 {fp.name}: {e}")

    # ── 3순위: docx/hwp → converted_pdf/ ───────────────────────
    if ext in {".docx", ".doc", ".hwp", ".hwpx", ".pptx", ".xlsx"}:
        try:
            from config import PATHS
            conv_root = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "converted_pdf"
            want = fp.stem + ".pdf"
            if conv_root.is_dir():
                for sub in conv_root.iterdir():
                    cand = sub / want
                    if cand.exists() and cand.stat().st_size > 0:
                        try:
                            import fitz
                            texts = []
                            total = 0
                            with fitz.open(str(cand)) as doc:
                                for page in doc:
                                    t = page.get_text("text") or ""
                                    t = t.strip()
                                    if t:
                                        texts.append(t)
                                        total += len(t)
                                    if total >= max_chars:
                                        break
                            if texts:
                                return "\n".join(texts)[:max_chars]
                        except Exception:
                            pass
        except Exception:
            pass

        # ── 4순위: python-docx (.docx 전용) ─────────────────────
        if ext == ".docx" and fp.exists():
            try:
                from docx import Document as _Docx
                doc = _Docx(str(fp))
                paras = [p.text for p in doc.paragraphs if p.text.strip()]
                return "\n".join(paras)[:max_chars]
            except Exception:
                pass

    # ── 5순위: 텍스트 파일 직접 읽기 ────────────────────────────
    if ext in {".txt", ".md", ".csv", ".json", ".xml", ".html"}:
        if fp.exists():
            try:
                return fp.read_text(encoding="utf-8", errors="ignore")[:max_chars]
            except Exception:
                pass

    return ""


def _doc_neighborhood_text(rid: str, max_chars: int = 3600,
                            query: str | None = None, window: int = 2,
                            src_path: str | None = None) -> str:
    """doc_page rid 의 인접 페이지(±window) 텍스트 결합."""
    try:
        from config import PATHS
        from pathlib import Path
        import re
        m = re.match(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$", rid)
        if not m:
            return ""
        stem, p = m.group(1), int(m.group(2))
        page_text_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text" / stem

        def _fitz_populate_all() -> None:
            try:
                import fitz as _fitz
                _pdf_path: Path | None = None

                if src_path:
                    _p = Path(src_path)
                    if _p.suffix.lower() == ".pdf" and _p.exists():
                        _pdf_path = _p

                if _pdf_path is None and src_path:
                    _orig = Path(src_path)
                    _conv_root = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "converted_pdf"
                    if _conv_root.is_dir():
                        _want = _orig.stem + ".pdf"
                        for _sub in _conv_root.iterdir():
                            _cand = _sub / _want
                            if _cand.exists():
                                _pdf_path = _cand
                                break

                if _pdf_path is None:
                    from services.trichef.lexical_rebuild import resolve_doc_pdf_map
                    _candidate = resolve_doc_pdf_map().get(stem)
                    if _candidate and _candidate.suffix.lower() == ".pdf" and _candidate.exists():
                        _pdf_path = _candidate

                if _pdf_path is None:
                    return
                page_text_dir.mkdir(parents=True, exist_ok=True)
                with _fitz.open(str(_pdf_path)) as _doc:
                    for _i, _pg in enumerate(_doc):
                        _out = page_text_dir / f"p{_i:04d}.txt"
                        if _out.exists():
                            continue
                        _t = _pg.get_text("text").strip()
                        if _t:
                            _out.write_text(_t, encoding="utf-8")
            except Exception as _e:
                logger.debug(f"[neighborhood] fitz populate 실패: {_e}")

        window_files = [
            page_text_dir / f"p{p + d:04d}.txt"
            for d in range(-window, window + 1)
            if (p + d) >= 0
        ]
        if not any(f.is_file() for f in window_files):
            _fitz_populate_all()

        if not page_text_dir.is_dir():
            return ""
        chunks: list[tuple[int, str]] = []
        total_len = 0
        for delta in range(-window, window + 1):
            tp = page_text_dir / f"p{p + delta:04d}.txt"
            if tp.is_file():
                t = tp.read_text(encoding="utf-8").strip()
                if t:
                    chunks.append((p + delta + 1, t))
                    total_len += len(t)
        if not chunks:
            return ""
        chunks.sort(key=lambda x: abs(x[0] - (p + 1)))
        rendered_parts = []
        running = 0
        truncated = False
        for page_num, text in chunks:
            piece = f"[p.{page_num}]\n{text}"
            if running + len(piece) > max_chars:
                remain = max(0, max_chars - running - 80)
                if remain > 200:
                    rendered_parts.append(piece[:remain] + "\n... [본문 일부 생략]")
                truncated = True
                break
            rendered_parts.append(piece)
            running += len(piece) + 2
        combined = "\n\n".join(rendered_parts)
        if truncated:
            combined += f"\n\n[전체 본문 {total_len:,}자 중 일부만 표시됨]"
        return combined
    except Exception:
        return ""


# ════════════════════════════════════════════════════════════════════
# 파일 요약 (상세 페이지 [요약] 버튼)
# ════════════════════════════════════════════════════════════════════

def _load_full_doc_text(rid: str, max_chars: int = 12000) -> tuple[str, str]:
    """doc_page rid → PDF 전체 페이지 텍스트 (요약용)."""
    try:
        from config import PATHS
        from pathlib import Path
        import re
        m = re.match(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$", rid)
        if not m:
            return "", ""
        stem = m.group(1)

        def _build_output(page_texts: list[tuple[int, str]]) -> str:
            chunks: list[str] = []
            running = 0
            truncated = False
            total = len(page_texts)
            for page_num, t in page_texts:
                t = t.strip()
                if not t:
                    continue
                piece = f"[p.{page_num}]\n{t}"
                if running + len(piece) > max_chars:
                    remain = max(0, max_chars - running - 80)
                    if remain > 200:
                        chunks.append(piece[:remain] + "\n... [중략]")
                    truncated = True
                    break
                chunks.append(piece)
                running += len(piece) + 2
            out = "\n\n".join(chunks)
            if truncated:
                out += f"\n\n[전체 {total}쪽 중 일부만 표시]"
            return out

        page_text_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text" / stem
        if page_text_dir.is_dir():
            pages = sorted(page_text_dir.glob("p*.txt"),
                           key=lambda p: int(p.stem[1:]))
            page_texts = []
            for tp in pages:
                try:
                    t = tp.read_text(encoding="utf-8").strip()
                    page_texts.append((int(tp.stem[1:]) + 1, t))
                except Exception:
                    continue
            if page_texts:
                return _build_output(page_texts), stem

        try:
            import fitz
            from services.trichef.lexical_rebuild import resolve_doc_pdf_map
            stem_to_pdf = resolve_doc_pdf_map()
            pdf_path = stem_to_pdf.get(stem)
            if pdf_path and pdf_path.suffix.lower() == ".pdf" \
                    and pdf_path.exists() and pdf_path.stat().st_size > 0:
                page_texts = []
                with fitz.open(str(pdf_path)) as doc:
                    for i, page in enumerate(doc):
                        t = page.get_text("text") or ""
                        if t.strip():
                            page_texts.append((i + 1, t))
                if page_texts:
                    try:
                        pt_dir = page_text_dir
                        pt_dir.mkdir(parents=True, exist_ok=True)
                        for pg_num, pg_txt in page_texts:
                            (pt_dir / f"p{pg_num-1:04d}.txt").write_text(
                                pg_txt.strip(), encoding="utf-8")
                    except Exception:
                        pass
                    return _build_output(page_texts), stem
        except Exception as e:
            logger.warning(f"[summarize] fitz fallback 실패 stem={stem!r}: {e}")

        try:
            from config import PATHS as _PATHS
            cap_dir = Path(_PATHS["TRICHEF_DOC_EXTRACT"]) / "captions" / stem
            if cap_dir.is_dir():
                import json as _json
                cap_files = sorted(cap_dir.glob("*.json"), key=lambda p: p.name)
                page_texts = []
                for cf in cap_files:
                    try:
                        d = _json.loads(cf.read_text(encoding="utf-8"))
                        txt = (d.get("caption") or d.get("text") or
                               d.get("description") or "").strip()
                        if txt:
                            pg = int(cf.stem[1:]) + 1 if cf.stem.startswith("p") else len(page_texts) + 1
                            page_texts.append((pg, txt))
                    except Exception:
                        continue
                if page_texts:
                    return _build_output(page_texts), stem
        except Exception as e:
            logger.warning(f"[summarize] caption fallback 실패 stem={stem!r}: {e}")

        return "", stem
    except Exception as e:
        logger.warning(f"[summarize] _load_full_doc_text: {e}")
        return "", ""


def _load_file_content_for_summary(file_type: str, trichef_id: str,
                                    file_path: str, segments: list | None = None
                                    ) -> tuple[str, str]:
    """요약용 파일 본문 로드."""
    if file_type in ("doc", "doc_page") and trichef_id:
        text, _stem = _load_full_doc_text(trichef_id, max_chars=18000)
        return text, "pdf_pages"

    if file_type == "image" and trichef_id:
        try:
            from services.location_resolver import _img_location
            loc = _img_location(trichef_id) or {}
            parts = [
                f"[제목] {loc.get('title','')}",
                f"[한줄 요약] {loc.get('tagline','')}",
                f"[줄거리] {loc.get('synopsis','')}",
                f"[설명] {loc.get('caption','')}",
            ]
            txt = "\n".join(p for p in parts if p.strip().endswith("]") is False)
            return txt.strip(), "image_caption"
        except Exception as e:
            logger.warning(f"[summarize] image caption: {e}")
            return "", "image_caption"

    if file_type in ("video", "movie", "audio", "music"):
        segs = segments or []
        chunks = []
        for s in segs[:80]:
            t0 = s.get("start") or s.get("start_sec") or 0
            t1 = s.get("end") or s.get("end_sec") or 0
            txt = (s.get("text") or s.get("label") or "").strip()
            if txt:
                chunks.append(f"[{int(t0//60):02d}:{int(t0%60):02d}-{int(t1//60):02d}:{int(t1%60):02d}] {txt}")
        return ("\n".join(chunks))[:18000], "av_segments"

    return "", "unknown"


def _build_summary_prompt(file_type: str, fname: str, content: str) -> str:
    type_label = {
        "doc": "PDF 문서", "doc_page": "PDF 문서",
        "image": "이미지", "video": "동영상", "movie": "동영상",
        "audio": "음성", "music": "음원",
    }.get(file_type, "파일")
    return f"""당신은 로컬 파일 상세 분석·해설 전문 AI 어시스턴트입니다.
아래 [{type_label}] 의 본문을 한국어 **논문체 보고서** 형식으로 작성하세요.
단순 요약이 아니라 본문의 흐름·논리·근거를 자연스러운 문단으로 풀어쓰는 것이 목표입니다.

파일명: {fname}
본문:
---
{content if content else '(본문이 추출되지 않았습니다)'}
---

작성 형식 (반드시 아래 6개 섹션 모두 ## Markdown 헤딩으로 시작):

## 1. 개요
- 이 파일의 정체·작성주체·목적·작성시기를 **2~4문장의 자연스러운 문단** 으로 작성.

## 2. 배경 및 목적
- 본문이 다루는 배경·맥락·문제의식·필요성을 **3~5문장 1~2개 문단** 으로 서술.

## 3. 주요 내용
- 본문의 흐름을 따라가면서 **장/절/주제별로 문단 단위로** 서술.
- 각 주제마다 ### 소제목 + **3~6문장의 문단** (불릿 점만 있는 것 금지).
- 가능하면 5~8개 소제목으로 구성 (본문 분량에 따라 조정).

## 4. 수치·날짜·고유명사
- 본문에 등장하는 숫자를 그대로 인용.
- 날짜·연도·기간·인명·기관명·지명·법령명·문헌명 그대로 보존.

## 5. 분석 및 시사점
- 본문이 도출하는 결론·권고·향후 계획·한계점을 **연결된 문단** 으로 분석.

## 6. 종합
- 위 내용을 4~6문장으로 통합 정리하는 마무리 문단 1개.

작성 규칙 (엄격 준수):
- 핵심 키워드는 **굵게** (`**용어**`) 강조.
- 단순 불릿 나열 지양 — **문단 위주**, 4번 섹션만 예외적으로 불릿 허용.
- 본문에 없는 정보는 추측 금지.
- 충실하게 작성 — 전체 합산 약 4,000~8,000자.
- 한국어, Markdown (제목 `##`/`###`, 강조 `**`, 인용 `>` 사용)."""


def _summarize_sse(file_type: str, trichef_id: str, file_path: str,
                   segments: list | None, file_name: str | None
                   ) -> Generator[str, None, None]:
    """파일 요약 SSE 제너레이터."""
    def emit(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    model = _get_ollama_model()
    if not model:
        yield emit({"type": "error", "message": "Ollama 미연결 또는 모델 없음."})
        return

    fname = file_name or (file_path or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "?"
    yield emit({"type": "info", "model": model, "file_type": file_type, "file_name": fname})

    content, kind = _load_file_content_for_summary(file_type, trichef_id, file_path, segments)
    if not content or len(content.strip()) < 20:
        yield emit({"type": "error",
                    "message": f"본문을 추출할 수 없습니다 (kind={kind}). 인덱싱 필요."})
        return

    yield emit({"type": "content_loaded", "length": len(content), "kind": kind})

    sys_prompt = _build_summary_prompt(file_type, fname, content)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user",   "content": "이 파일을 위 원칙에 따라 요약해줘."},
    ]

    full = ""
    t0 = time.time()
    stream_error: str | None = None
    try:
        for tok in _ollama_stream(messages, model, num_predict=7500, temperature=0.25):
            full += tok
            yield emit({"type": "token", "text": tok})
    except Exception as e:
        stream_error = str(e)
        logger.warning(f"[summarize] stream 중단: {e}")

    try:
        logger.info(
            f"[summarize] file={fname[:40]!r} type={file_type} "
            f"content_len={len(content)} summary_len={len(full)} "
            f"dt={time.time()-t0:.2f}s err={stream_error!r}"
        )
    except Exception:
        pass

    yield emit({
        "type":    "done",
        "summary": full,
        "model":   model,
        "length":  len(content),
        "kind":    kind,
        "error":   stream_error,
    })


@aimode_bp.post("/summarize")
def summarize():
    """POST /api/aimode/summarize — 파일 요약 SSE 스트리밍."""
    body       = request.get_json(silent=True) or {}
    file_type  = (body.get("file_type") or "").strip()
    trichef_id = (body.get("trichef_id") or body.get("rid") or "").strip()
    file_path  = (body.get("file_path") or "").strip()
    file_name  = (body.get("file_name") or "").strip()
    segments   = body.get("segments") or []

    if not file_type:
        return jsonify({"error": "file_type 필수"}), 400

    return Response(
        _summarize_sse(file_type, trichef_id, file_path, segments, file_name),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
