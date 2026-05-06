"""routes/aimode.py — AIMODE RAG (Retrieval-Augmented Generation) 엔드포인트.

로컬 DB를 두뇌로 쓰는 RAG (Router 분기 포함):
  0. Router → "rag" / "chat" / "followup" 판단
  [rag]
  1. 의도 파악 → "~를 원하시는군요." + 키워드 추출
  2. 벡터 검색 → 후보 파일 카드 표시
  3. 파일별 전문 스캔 → scanning / found / not_found 애니메이션
  4. 컨텍스트 조립 + 출처 번호 부여
  5. Ollama 스트리밍 답변 (출처 인용)
  [chat]
  → 파일 검색 없이 대화 전용 프롬프트로 Ollama 직접 응답
  [followup]
  → 이전 턴 파일 재사용 → generate_node

SSE 이벤트:
  {"type": "info",        "model": "...", "thread_id": "..."}
  {"type": "route",       "mode": "rag"|"chat"|"followup"}
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


# ── LangGraph 통합 ────────────────────────────────────────────────
_LANGGRAPH_OK = False


def _add_messages(left: list, right: list) -> list:
    return (left or []) + (right or [])


try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

    class RAGState(TypedDict):
        # 입력
        question:         str
        thread_id:        str
        topk:             int
        model:            str
        # router_node 출력
        route:            str          # "rag" | "chat" | "followup" | "qa_gen"
        prev_sources:     list[dict]   # followup 시 이전 턴 matched_sources
        # intent_node 출력
        intent_message:   str
        file_keywords:    list[str]
        detail_keywords:  list[str]
        # search_node 출력
        candidates:       list[dict]
        # scan_node 출력
        scan_results:     list[dict]
        # select_node 출력
        matched_sources:  list[dict]
        # generate_node 출력
        answer:           str
        # qa_generate_node 출력
        qa_question:      str
        qa_answer:        str
        qa_attempts:      int
        # ※ 대화 이력은 _load_history/_save_history 로 별도 관리
        #   (LangGraph State에서 제외 — messages reducer 의존성 제거)

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
    _prev_sources_store.pop(thread_id, None)


# ── 이전 턴 파일 소스 저장소 (followup 용) ────────────────────────────
_prev_sources_store: dict[str, list[dict]] = {}
_prev_sources_lock = threading.Lock()


# ── Ollama 함수 ────────────────────────────────────────────────────
def _get_ollama_model() -> str | None:
    try:
        r = _req.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        models = r.json().get("models", [])
        preferred = ["gemma3", "qwen2.5", "llama3.2", "llama3", "mistral", "phi4"]
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
                   num_predict: int = -1,
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
        "사용자 질문을 보고 아래 형식으로만 출력해. 다른 글자 절대 금지.\n\n"
        "의도메시지: (AI가 무엇을 해줄지 짧고 자연스럽게 한 문장. '~해드릴게요' / '~찾아볼게요' / '~확인해드릴게요' 형식)\n"
        "파일검색: (어떤 파일을 찾을지, 고유명사·주제어 위주, 최대 4단어)\n"
        "내용검색: (파일 안에서 찾을 핵심 키워드, 최대 3단어)\n\n"
        "예시1)\n"
        "질문: 김라민 생년월일 뭐더라\n"
        "의도메시지: 김라민의 생년월일을 찾아볼게요.\n"
        "파일검색: 김라민\n"
        "내용검색: 김라민 생년월일\n\n"
        "예시2)\n"
        "질문: 경주 동궁 월지 문서에서 유구가 몇개야\n"
        "의도메시지: 경주 동궁 월지 문서에서 유구 수를 확인해드릴게요.\n"
        "파일검색: 경주 동궁 월지\n"
        "내용검색: 유구\n\n"
        "예시3)\n"
        "질문: 나이테 PDF에서 탄소 측정 방법 알려줘\n"
        "의도메시지: 나이테 문서에서 탄소 측정 방법을 찾아드릴게요.\n"
        "파일검색: 나이테 탄소\n"
        "내용검색: 탄소 측정\n\n"
        "예시4)\n"
        "질문: 삼성전자 재생에너지 전환율이랑 탄소중립 목표 알려줘\n"
        "의도메시지: 삼성전자 탄소중립 목표와 재생에너지 전환율을 문서에서 바로 확인해드릴게요.\n"
        "파일검색: 삼성전자 탄소중립 재생에너지\n"
        "내용검색: 재생에너지 탄소중립\n\n"
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

    # 한국어 조사 제거 (끝에 붙은 조사)
    _JOSA_SUFFIXES = [
        "에서의", "으로의", "에게서", "한테서",
        "에서", "에게", "한테", "부터", "까지", "이랑", "과의", "와의",
        "으로", "로서", "으로서",
        "의", "에", "과", "와", "이", "가", "을", "를", "은", "는",
        "도", "로", "만", "서", "고", "며", "면", "야", "아",
    ]

    def _strip_josa(word: str) -> str:
        for suffix in _JOSA_SUFFIXES:
            if word.endswith(suffix) and len(word) > len(suffix) + 1:
                return word[:-len(suffix)]
        return word

    def _to_list(s: str) -> list[str]:
        words = _re.findall(r"[가-힣A-Za-z0-9]{2,}", s)
        result = []
        for w in words:
            stripped = _strip_josa(w)
            if len(stripped) >= 2 and stripped not in _STOPWORDS:
                result.append(stripped)
        return result

    # Fallback — Ollama 실패 시 질문에서 직접 추출 + 조사 제거
    if not file_q:
        tokens = _re.findall(r"[가-힣A-Za-z0-9]+", question)
        meaningful = [_strip_josa(t) for t in tokens
                      if len(_strip_josa(t)) >= 2 and _strip_josa(t) not in _STOPWORDS]
        # 중복 제거 (순서 유지)
        seen: set[str] = set()
        meaningful = [t for t in meaningful if not (t in seen or seen.add(t))]
        file_q    = " ".join(meaningful[:4])
        content_q = " ".join(meaningful[:3])

    if not intent_msg:
        intent_msg = f"{file_q or question} 관련 내용을 문서에서 찾아드릴게요."

    return (
        intent_msg,
        _to_list(file_q) or _to_list(question),
        _to_list(content_q) or _to_list(file_q),
    )


# ── RAG 파일 스캔 ──────────────────────────────────────────────────
def _scan_file_for_keywords(
    source: dict,
    keywords: list[str],
    max_chars: int = 600000,   # PDF 전체 읽기 (87p ≈ 400,000자)
) -> tuple[bool, list[str]]:
    """source 파일 전문에서 keywords 검색 → (found, [chunk_snippets]).

    doc  : _read_source_full_text 로 전문 추출
    기타 : snippet 기반 처리 (이미지/영상/음악)

    개선점:
    - 여러 키워드가 가까이 있는 구간(복합 매칭)을 우선 반환
    - 단독 매칭은 보조로 추가
    각 chunk 는 키워드 주변 ±400자 텍스트.
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
    kws_lower  = [k.lower() for k in keywords if k]

    # ── 1단계: 복합 매칭 — 여러 키워드가 1000자 이내 공존하는 위치 찾기 ──
    # 각 키워드 위치 수집
    positions: dict[str, list[int]] = {}
    for kw in kws_lower:
        pos_list = []
        start = 0
        while True:
            p = text_lower.find(kw, start)
            if p < 0: break
            pos_list.append(p)
            start = p + 1
        positions[kw] = pos_list

    WINDOW = 1000  # 1000자 창 안에 여러 키워드 있으면 복합 매칭
    composite_centers: list[tuple[int, int]] = []  # (score, center)

    for kw, pos_list in positions.items():
        for pos in pos_list:
            # 이 위치 ±WINDOW 안에 다른 키워드가 몇 개나 있나 점수
            score = sum(
                1 for other_kw, other_list in positions.items()
                if other_kw != kw and any(abs(p2 - pos) <= WINDOW for p2 in other_list)
            )
            if score > 0:
                composite_centers.append((score, pos))

    composite_centers.sort(key=lambda x: -x[0])  # 점수 높은 순

    found_chunks: list[str] = []
    seen_positions: set[int] = set()
    CHUNK_R = 400  # chunk 반경

    def _add_chunk(center: int):
        if any(abs(center - p) < 300 for p in seen_positions):
            return
        seen_positions.add(center)
        c_start = max(0, center - CHUNK_R)
        c_end   = min(len(full_text), center + CHUNK_R)
        chunk   = full_text[c_start:c_end].strip()
        chunk   = _re.sub(r'\n{3,}', '\n\n', chunk)
        if chunk:
            found_chunks.append(chunk)

    for _, pos in composite_centers[:4]:
        _add_chunk(pos)
        if len(found_chunks) >= 3:
            break

    # ── 2단계: 단독 매칭 보조 (복합 3개 미만일 때) ──────────────────
    if len(found_chunks) < 3:
        for kw in kws_lower:
            start = 0
            while True:
                pos = text_lower.find(kw, start)
                if pos < 0: break
                _add_chunk(pos)
                start = pos + 1
                if len(found_chunks) >= 3:
                    break
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
    extracted: str = "",
    key_facts: list[str] | None = None,
) -> list[dict]:
    """RAG 시스템 프롬프트 + 대화 이력 + 사용자 질문 → messages 리스트.

    [재설계 v7] forced-quote:
    - key_facts: Python이 문서에서 직접 추출한 핵심 수치 문장 목록
      → 시스템 프롬프트 맨 앞 + 유저 메시지 앞에 강제 인용으로 배치
    - 모델의 학습 prior를 이기기 위해 핵심 수치를 이중으로 노출
    """
    source_list = "\n".join(
        f"  [출처{i+1}] {s.get('file_name', '?')} ({s.get('file_type', '?')})"
        for i, s in enumerate(matched_sources)
    )

    doc_body = extracted.strip() if extracted.strip() else (context if context else "")

    # 핵심 수치 문장 → 강제 인용 블록
    forced_block = ""
    if key_facts:
        lines = "\n".join(f'  "{f}"' for f in key_facts if f.strip())
        forced_block = f"""
[문서에서 직접 추출한 핵심 인용 — 아래 수치만 사용할 것]
{lines}

"""

    sys_msg = f"""당신은 아래 [문서 발췌]를 보고 [질문]에 답하는 AI입니다. 반드시 한국어로만 답변하세요.
{forced_block}
[절대 규칙]
1. 숫자·비율·날짜는 반드시 [핵심 인용] 또는 [문서 발췌]에 있는 것만 쓰세요.
2. 학습 데이터에서 알고 있는 수치를 쓰면 안 됩니다. 문서 수치만 사용.
3. 발췌에 없는 내용 추가 금지. 외국어 출력 금지.
4. 답을 못 찾으면 "제공 문서에 해당 정보가 없습니다"라고만 쓰세요.

[답변 형식]
- 항목별 번호(1. 2.)와 줄바꿈 사용
- 마크다운(** # `) 사용 금지

[참고 파일]
{source_list if source_list else '  (매칭 파일 없음)'}

[문서 발췌]
{doc_body if doc_body else '(발췌 없음)'}"""

    messages: list[dict] = [{"role": "system", "content": sys_msg}]
    if prior_history:
        messages.extend(prior_history[-6:])

    # 유저 메시지에도 핵심 인용을 앞에 박음 (이중 노출)
    if key_facts:
        quotes = "\n".join(f'- "{f}"' for f in key_facts if f.strip())
        user_content = (
            f"[문서 핵심 인용]\n{quotes}\n\n"
            f"위 인용문의 수치를 그대로 사용해서 다음 질문에 답하세요:\n{question}"
        )
    else:
        user_content = question

    messages.append({"role": "user", "content": user_content})
    return messages


def _python_extract_key_facts(
    full_text: str,
    question: str,
    max_facts: int = 6,
    min_score: int = 1,
) -> list[str]:
    """Python으로 문서에서 핵심 수치 포함 문장을 추출한다 (LLM 불필요).

    질문 토큰과 겹치면서 숫자/비율/날짜를 포함한 문장을 우선 선택.
    모델의 학습 prior를 이기기 위해 generate_node에서 forced-quote로 활용.

    Args:
        min_score: 이 점수 이상인 문장만 포함 (기본 1).
                   fitz_head처럼 무관한 숫자가 많은 소스엔 높은 값(예: 3) 사용.
    """
    import re as _re

    # 줄바꿈 / 문장 종결 기준으로 문장 분리
    raw_sents = _re.split(r'\n|(?<=[다요함임])\.\s*|(?<=[.!?])\s+', full_text)
    sentences = [s.strip() for s in raw_sents if len(s.strip()) > 20]

    # 질문 키워드 (2자 이상 한글 + 숫자)
    q_tokens = set(_re.findall(r'[가-힣]{2,}|\d+', question))

    scored = []
    for sent in sentences:
        score = 0
        # 숫자/비율/날짜 포함 시 가산점
        nums = _re.findall(r'\d+\.?\d*\s*%|\d{4}년|\d+\.\d+|\d+백만', sent)
        score += len(nums) * 3
        # 질문 토큰 포함 시 가산점
        kw_hits = sum(1 for tok in q_tokens if tok in sent)
        score += kw_hits
        # min_score 통과 여부 (kw_hits도 함께 검증)
        if score >= min_score and kw_hits >= 1:
            scored.append((score, sent))

    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_facts]]


def _extract_relevant_passages(question: str, context: str, model: str) -> str:
    """Step 1: 질문과 관련된 문서 구절을 먼저 추출 (Extract-then-Generate 패턴).

    Qwen 7B가 외부 지식을 사용하는 것을 방지하기 위해
    먼저 문서에서 관련 구절을 그대로 복사·추출하게 하고,
    Step 2에서 그 추출 결과만 사용하여 답변을 생성한다.

    Returns:
        추출된 관련 구절 (없으면 빈 문자열)
    """
    extract_prompt = (
        "아래 [질문]에 답하는 데 필요한 문장들을 [문서]에서 찾아 그대로 복사하세요.\n"
        "규칙:\n"
        "- 문서 원문을 그대로 복사 (수정·요약·번역 금지)\n"
        "- 관련 문장만 선택 (최대 15문장)\n"
        "- 수치, 날짜, 원인, 고유명사가 포함된 문장 우선\n"
        "- 관련 문장이 없으면 '해당 없음' 출력\n\n"
        f"[질문]\n{question}\n\n"
        f"[문서]\n{context[:15000]}\n\n"
        "[복사된 관련 문장들]:"
    )
    try:
        extracted = _ollama_oneshot(extract_prompt, model, num_predict=800)
        if not extracted or "해당 없음" in extracted or len(extracted.strip()) < 20:
            return ""
        return extracted.strip()
    except Exception as e:
        logger.warning(f"[extract_passages] 실패: {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════
# LangGraph 노드 정의
# ══════════════════════════════════════════════════════════════════════

# 각 노드가 SSE 이벤트를 실시간으로 보내기 위한 thread-local 큐
_tls = threading.local()


def _emit(obj: dict) -> None:
    """노드 내부에서 SSE 이벤트를 큐에 투척."""
    q = getattr(_tls, "event_queue", None)
    if q is not None:
        q.put(obj)


# ── 노드 0: 라우터 — rag / chat / followup 판단 ──────────────────────
def router_node(state: dict) -> dict:
    """LLM이 대화 맥락을 보고 라우트를 결정한다.

    Returns:
        route: "rag" | "chat" | "followup"
        prev_sources: followup 시 이전 파일 목록
    """
    question  = state["question"]
    model     = state["model"]
    thread_id = state["thread_id"]

    # 이전 대화 이력 (최근 3턴)
    history = _load_history(thread_id)
    history_text = ""
    if history:
        for m in history[-6:]:
            role = "사용자" if m["role"] == "user" else "AI"
            history_text += f"{role}: {m['content'][:300]}\n"

    # 이전 파일 목록
    with _prev_sources_lock:
        prev_sources = list(_prev_sources_store.get(thread_id, []))

    prev_files_text = ""
    if prev_sources:
        names = [s.get("file_name", "?") for s in prev_sources[:5]]
        prev_files_text = ", ".join(names)

    prompt = (
        "아래 질문을 딱 하나로만 분류해. 다른 글자 절대 금지.\n\n"
        "분류 기준:\n"
        "followup  → 이전 답변·파일에 대한 추가 요청. 이전 파일이 있고 질문이\n"
        "            '더 설명해줘', '요약해줘', '쉽게 설명해줘', '다시 정리해줘',\n"
        "            '한국어로 해줘', '예시 들어줘', '좀 더 자세히', '그게 뭐야',\n"
        "            '거기서 ~는?', '방금 그거' 처럼 새 파일 검색 없이 이전 내용\n"
        "            을 다루는 경우. 이전 파일이 있을 때만 가능.\n"
        "qa_gen    → 사용자가 직접 '문제 만들어줘', '퀴즈 내줘', '출제해줘' 같이\n"
        "            시험 문제·퀴즈 생성을 명시적으로 요청한 경우만 해당\n"
        "chat      → 순수 잡담·인사·날씨·프로그래밍 방법 등 파일과 무관한 대화\n"
        "rag       → 특정 회사·수치·사건·문서에 대해 새로운 정보를 탐색하는 질문\n\n"
        "핵심 원칙:\n"
        "- 이전 파일이 있고 현재 질문이 그 내용을 다시 요청하는 것이면 → followup\n"
        "- '문제 만들어줘' 같은 생성 요청이 없으면 qa_gen 절대 금지\n\n"
        "예시:\n"
        "질문: 안녕 → chat\n"
        "질문: 파이썬 문법 알려줘 → chat\n"
        "질문: FAO 식량가격지수는 얼마인가? → rag\n"
        "질문: 삼성전자 재생에너지 전환율은? → rag\n"
        "이전 파일: Samsung.pdf / 질문: 쉽게 설명해줘 → followup\n"
        "이전 파일: Samsung.pdf / 질문: 요약해줘 → followup\n"
        "이전 파일: Samsung.pdf / 질문: 더 자세히 알려줘 → followup\n"
        "이전 파일: Samsung.pdf / 질문: 다시 정리해줘 → followup\n"
        "이전 파일: Samsung.pdf / 질문: 거기서 탄소중립 목표가 뭐야? → followup\n"
        "이전 파일: 없음 / 질문: 쉽게 설명해줘 → chat\n"
        "질문: 삼성전자 문서로 시험 문제 만들어줘 → qa_gen\n\n"
        f"이전 대화:\n{history_text or '없음'}\n"
        f"이전에 찾은 파일: {prev_files_text or '없음'}\n"
        f"현재 질문: {question}\n\n"
        "분류 결과:"
    )

    raw = _ollama_oneshot(prompt, model, num_predict=15).strip().lower()

    if "followup" in raw and prev_sources:
        route = "followup"
    elif "qa_gen" in raw or "qa gen" in raw:
        route = "qa_gen"
    elif "chat" in raw:
        route = "chat"
    else:
        route = "rag"

    # Fallback: 이전 파일이 있고 질문이 짧고 새 고유명사가 없으면 followup 강제
    import re as _re_r
    if route == "rag" and prev_sources:
        _FOLLOWUP_TRIGGERS = [
            "쉽게", "다시", "요약", "정리", "자세히", "설명해", "풀어줘",
            "더 알려줘", "그게", "거기서", "방금", "한국어로", "예시", "예를",
        ]
        q_len = len(question.strip())
        has_trigger = any(t in question for t in _FOLLOWUP_TRIGGERS)
        new_nouns = _re_r.findall(r"[가-힣A-Z][가-힣A-Za-z]{3,}", question)
        if q_len <= 30 and has_trigger and len(new_nouns) == 0:
            route = "followup"
            logger.info(f"[router_node] fallback followup (short+trigger, q_len={q_len})")

    logger.info(f"[router_node] raw={raw!r} → route={route}")
    _emit({"type": "route", "mode": route})

    return {
        "route":        route,
        "prev_sources": prev_sources if route == "followup" else [],
    }


def _route_edge(state: dict) -> str:
    """조건부 엣지 함수 — router_node 결과로 다음 노드 결정."""
    route = state.get("route", "rag")
    # qa_gen도 intent → search → scan → select 파이프라인 사용
    return "rag" if route == "qa_gen" else route


def _after_select_edge(state: dict) -> str:
    """select_node 이후 — qa_gen 이면 qa_generate, 아니면 generate."""
    return "qa_generate" if state.get("route") == "qa_gen" else "generate"


# ── 노드 1: 의도 파악 + 키워드 추출 ─────────────────────────────────
def intent_node(state: dict) -> dict:
    question = state["question"]
    model    = state["model"]

    intent_msg, file_kws, detail_kws = _extract_rag_intent(question, model)

    _emit({
        "type":            "intent",
        "message":         intent_msg,
        "file_keywords":   file_kws,
        "detail_keywords": detail_kws,
    })
    time.sleep(0.3)

    return {
        "intent_message":  intent_msg,
        "file_keywords":   file_kws,
        "detail_keywords": detail_kws,
    }


# ── 노드 2: 벡터 DB 검색 ─────────────────────────────────────────────
def search_node(state: dict) -> dict:
    file_kws = state.get("file_keywords") or []
    question = state["question"]
    topk     = state.get("topk", 5)

    file_query = " ".join(file_kws) if file_kws else question
    candidates = _do_search(file_query, topk=topk)
    if not candidates:
        candidates = _do_search(question, topk=topk)

    _emit({"type": "candidates", "items": candidates})
    time.sleep(0.3)

    return {"candidates": candidates}


# ── 노드 3: 파일 하나씩 내용 확인 ────────────────────────────────────
def scan_node(state: dict) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    candidates  = state.get("candidates") or []
    detail_kws  = state.get("detail_keywords") or []
    scan_results: list[dict] = []

    # 병렬로 스캔 시작 (결과는 순서대로 수집)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(_scan_file_for_keywords, src, detail_kws)
            for src in candidates
        ]

        for i, (src, fut) in enumerate(zip(candidates, futures)):
            file_id   = src.get("trichef_id") or str(i)
            file_name = src.get("file_name")  or "?"
            file_type = src.get("file_type")  or "?"

            # 스캔 시작 이벤트
            _emit({
                "type":      "scanning",
                "index":     i,
                "file_id":   file_id,
                "file_name": file_name,
                "file_type": file_type,
            })

            try:
                found, chunks = fut.result(timeout=20)
            except Exception as _e:
                logger.debug(f"[scan_node] {file_name}: {_e}")
                found, chunks = False, []

            # 스캔 결과 이벤트
            _emit({
                "type":    "scan_result",
                "index":   i,
                "file_id": file_id,
                "found":   found,
                "chunks":  chunks,
            })

            scan_results.append({
                **src,
                "found":          found,
                "matched_chunks": chunks,
            })
            time.sleep(SCAN_DELAY)

    return {"scan_results": scan_results}


# ── 노드 4: 내용 있는 파일만 선택 ────────────────────────────────────
def select_node(state: dict) -> dict:
    scan_results = state.get("scan_results") or []
    candidates   = state.get("candidates")   or []

    matched = [r for r in scan_results if r.get("found")]

    # 매칭 파일 없으면 → 1위 파일 강제 선택 (fallback)
    if not matched and candidates:
        logger.info("[select_node] 매칭 없음 → 1위 fallback")
        best = candidates[0]
        matched = [{**best, "found": True,
                    "matched_chunks": [best.get("snippet") or ""]}]

    _emit({"type": "selected", "sources": matched})
    time.sleep(0.2)

    return {"matched_sources": matched}


# ── 노드 4-b: followup 시 이전 파일 재사용 ───────────────────────────
def followup_select_node(state: dict) -> dict:
    """이전 턴의 파일을 그대로 matched_sources 로 사용."""
    prev = state.get("prev_sources") or []
    _emit({"type": "selected", "sources": prev})
    time.sleep(0.1)
    return {"matched_sources": prev}


# ══════════════════════════════════════════════════════════════════════
# QA 생성 헬퍼 + 노드
# ══════════════════════════════════════════════════════════════════════

def _build_qa_prompt(context: str) -> str:
    """문서 기반 QA 생성 프롬프트 — Qwen 맞춤 '복사+압축' 유도."""
    return (
        "너의 역할은 '문서 기반 QA 데이터 생성기'이다.\n\n"
        "절대 규칙:\n"
        "- 반드시 [입력 문서]에 있는 표현만 사용한다\n"
        "- 외부 지식·일반 지식 사용 금지\n"
        "- 새로운 표현 창작 금지 — 문서 단어를 그대로 가져와 압축\n\n"
        "[문제 생성 규칙]\n"
        "- 서술형 문제 1개만 생성\n"
        "- 질문은 반드시 '설명하시오', '쓰시오', '서술하시오' 중 하나로 끝낼 것\n"
        "- 문서 핵심 개념 1개만 묻기\n\n"
        "[정답 생성 규칙]\n"
        "- 반드시 문서에 있는 표현을 그대로 사용\n"
        "- 절대 요약하지 말 것, 절대 일반화하지 말 것\n"
        "- 2~3문장으로 작성\n"
        "- 문서 핵심 단어 최대한 많이 포함\n\n"
        "[출력 형식] 아래 형식 외 다른 글자 금지:\n"
        "[질문]\n"
        "질문 내용\n\n"
        "[정답]\n"
        "정답 내용\n\n"
        f"[입력 문서]\n{context[:3000]}"
    )


def _validate_qa(question: str, answer: str, context: str) -> tuple[bool, list[str]]:
    """생성된 QA 검증.

    검증 기준:
    1. 질문이 '설명하시오/쓰시오/서술하시오/분석하시오' 형식으로 끝남
    2. 정답이 1~5문장 (적당한 길이)
    3. 정답이 문서 단어 20% 이상 포함 (Qwen 7B 현실적 기준)
    4. 정답이 20자 이상

    Returns:
        (is_valid, issues)
    """
    import re as _re
    issues: list[str] = []

    # 1. 질문 형식
    q = question.strip().rstrip(".")
    valid_endings = ["설명하시오", "쓰시오", "서술하시오", "분석하시오", "기술하시오"]
    if not any(q.endswith(e) for e in valid_endings):
        issues.append(f"질문 형식 불일치 (끝말: '{q[-6:]}')")

    # 2. 정답 길이
    sentences = [s.strip() for s in _re.split(r"[.。!?]\s*", answer.strip()) if len(s.strip()) > 5]
    if len(sentences) < 1:
        issues.append("정답이 너무 짧음 (문장 없음)")
    elif len(sentences) > 6:
        issues.append(f"정답이 너무 김 ({len(sentences)}문장 초과)")

    # 3. 문서 단어 포함률 (한국어 2자 이상 단어 기준)
    ctx_words = set(_re.findall(r"[가-힣]{2,}", context[:3000]))
    ans_words = set(_re.findall(r"[가-힣]{2,}", answer))
    if ctx_words and ans_words:
        overlap = len(ans_words & ctx_words) / max(len(ans_words), 1)
        if overlap < 0.20:
            issues.append(f"문서 단어 포함률 낮음 ({overlap:.0%} < 20%)")

    # 4. 최소 길이
    if len(answer.strip()) < 20:
        issues.append("정답이 너무 짧음 (20자 미만)")

    return len(issues) == 0, issues


def qa_generate_node(state: dict) -> dict:
    """문서 기반 QA 생성 노드 (최대 3회 재시도 + 검증).

    SSE 이벤트:
        {"type": "qa_generating", "attempt": N, "max": 3}
        {"type": "qa_result", "question": "...", "answer": "...",
         "attempts": N, "valid": bool, "issues": [...], "sources": [...]}
        {"type": "done", "answer": "...", "model": "...", "sources_count": N}
    """
    import re as _re

    question        = state["question"]
    model           = state["model"]
    thread_id       = state["thread_id"]
    matched_sources = state.get("matched_sources") or []

    # 파일 전문 읽기 (generate_node와 동일)
    full_sources = []
    for src in matched_sources:
        full_text = _read_source_full_text(src, max_chars=600000)
        full_sources.append({
            **src,
            "matched_chunks": [full_text] if full_text else (src.get("matched_chunks") or []),
        })

    context = _build_rag_context(full_sources if full_sources else matched_sources)
    if not context.strip():
        _emit({"type": "error", "message": "문서 내용을 찾을 수 없어 문제를 생성할 수 없습니다."})
        return {"qa_question": "", "qa_answer": "", "qa_attempts": 0, "answer": ""}

    prompt = _build_qa_prompt(context)

    def _parse_qa(raw: str) -> tuple[str, str]:
        q_m = _re.search(r"\[질문\]\s*(.+?)(?=\n\n|\[정답\]|$)", raw, _re.DOTALL)
        a_m = _re.search(r"\[정답\]\s*(.+?)$", raw, _re.DOTALL)
        return (
            q_m.group(1).strip() if q_m else "",
            a_m.group(1).strip() if a_m else "",
        )

    qa_question = ""
    qa_answer   = ""
    attempts    = 0
    last_issues: list[str] = ["아직 생성 안 됨"]

    for attempt in range(1, 4):  # 최대 3회
        attempts = attempt
        _emit({"type": "qa_generating", "attempt": attempt, "max": 3})

        raw = _ollama_oneshot(prompt, model, num_predict=500)
        logger.info(f"[qa_generate] attempt={attempt} raw={raw[:150]!r}")

        q_text, a_text = _parse_qa(raw)

        if q_text and a_text:
            valid, issues = _validate_qa(q_text, a_text, context)
            qa_question, qa_answer = q_text, a_text   # 항상 최신 결과 보존
            if valid:
                last_issues = []
                logger.info(f"[qa_generate] attempt={attempt} 검증 통과 ✓")
                break
            else:
                last_issues = issues
                logger.info(f"[qa_generate] attempt={attempt} 검증 실패: {issues}")
        else:
            last_issues = ["[질문]/[정답] 형식 파싱 실패"]
            logger.info(f"[qa_generate] attempt={attempt} 파싱 실패: {raw[:80]!r}")

    is_valid = len(last_issues) == 0
    source_names = [s.get("file_name", "?") for s in matched_sources]

    _emit({
        "type":     "qa_result",
        "question": qa_question,
        "answer":   qa_answer,
        "attempts": attempts,
        "valid":    is_valid,
        "issues":   last_issues,
        "sources":  source_names,
    })

    # done 이벤트 (UI 호환)
    answer_text = (
        f"[질문]\n{qa_question}\n\n[정답]\n{qa_answer}"
        if qa_question else "문제 생성에 실패했습니다. 다시 시도해주세요."
    )

    if qa_question and qa_answer:
        _save_history(thread_id, question, answer_text)
        if matched_sources:
            with _prev_sources_lock:
                _prev_sources_store[thread_id] = list(matched_sources)

    _emit({
        "type":          "done",
        "answer":        answer_text,
        "model":         model,
        "sources_count": len(matched_sources),
    })

    return {
        "qa_question": qa_question,
        "qa_answer":   qa_answer,
        "qa_attempts": attempts,
        "answer":      answer_text,
    }


# ── 노드 chat: 파일 검색 없이 직접 LLM 대화 ──────────────────────────
def direct_generate_node(state: dict) -> dict:
    """chat 모드 — 파일 없이 대화 전용 프롬프트로 Ollama 스트리밍."""
    question  = state["question"]
    model     = state["model"]
    thread_id = state["thread_id"]

    prior_history = _load_history(thread_id)

    sys_msg = (
        "당신은 친절하고 유능한 AI 어시스턴트입니다. "
        "반드시 한국어로만 답변하세요. 영어 사용 절대 금지.\n"
        "자연스럽고 대화체로 답변하세요. 마크다운 문법(**, #, `)은 사용하지 마세요.\n"
        "파일이나 문서 없이 일반 지식으로 답변합니다.\n"
        "모르는 것은 솔직하게 모른다고 말하세요."
    )

    messages: list[dict] = [{"role": "system", "content": sys_msg}]
    if prior_history:
        messages.extend(prior_history[-10:])
    messages.append({"role": "user", "content": question})

    full_answer  = ""
    stream_error = None
    try:
        for tok in _ollama_stream(messages, model, num_predict=-1):
            full_answer += tok
            _emit({"type": "token", "text": tok})
    except Exception as e:
        stream_error = str(e)
        logger.warning(f"[direct_generate] stream 중단: {e}")

    if full_answer and len(full_answer.strip()) >= 5 and not stream_error:
        _save_history(thread_id, question, full_answer)

    _emit({
        "type":          "done",
        "answer":        full_answer,
        "model":         model,
        "sources_count": 0,
        "error":         stream_error,
    })
    return {"answer": full_answer}


# ── 노드 5: 답변 생성 (PDF 직접 읽기 + 파이썬 키워드 타게팅) ─────────
def _keyword_target_paragraphs(
    full_text: str,
    question: str,
    keywords: list[str],
    max_chars: int = 12000,
    window: int = 800,
) -> str:
    """전체 PDF 텍스트에서 질문 키워드 주변 슬라이딩 윈도우로 관련 구절 추출.

    fitz 추출 텍스트는 단일 \\n 구분이라 단락 분리가 어렵다.
    키워드가 등장하는 위치마다 ±window 글자를 슬라이스해 유니크하게 수집.
    PDF에 중국어/일본어 등 CJK 섹션이 있으면 사전 필터링.
    """
    import re as _re

    # CJK 문자 비율 30% 이상인 줄 제거 (중국어/일본어 섹션 제거)
    def _filter_cjk(text: str) -> str:
        lines = []
        for line in text.split("\n"):
            cjk = len(_re.findall(r"[一-鿿぀-ヿ]", line))
            total = len(line.strip())
            if total == 0 or cjk / total < 0.25:
                lines.append(line)
        return "\n".join(lines)

    full_text = _filter_cjk(full_text)

    # 질문에서 추가 키워드 추출 (2자 이상 한글 명사/숫자)
    q_tokens = set(_re.findall(r"[가-힣]{2,}|\d+\.?\d*", question))
    kw_set = set(kw.lower() for kw in keywords if kw) | set(t.lower() for t in q_tokens)

    if not kw_set:
        return full_text[:max_chars]

    tl = full_text.lower()
    slices: list[tuple[int, int]] = []  # (start, end)

    for kw in kw_set:
        start = 0
        while True:
            pos = tl.find(kw, start)
            if pos < 0:
                break
            s = max(0, pos - window)
            e = min(len(full_text), pos + len(kw) + window)
            slices.append((s, e))
            start = pos + 1

    if not slices:
        return full_text[:max_chars]

    # 위치 기준 정렬 후 겹치는 구간 병합 (최대 max_chars)
    slices.sort()
    merged: list[tuple[int, int]] = []
    for s, e in slices:
        if merged and s <= merged[-1][1] + 100:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append([s, e])

    # 구간별 점수: distinct 키워드 수 + 수치/날짜 포함 보너스
    def _score(s: int, e: int) -> float:
        chunk = tl[s:e]
        distinct = sum(1 for kw in kw_set if kw in chunk)
        # 퍼센트·숫자 포함 보너스
        import re as _rr
        num_bonus = len(_rr.findall(r"\d+\.?\d*\s*%", chunk)) * 0.5
        return distinct + num_bonus

    scored = sorted(merged, key=lambda se: -_score(se[0], se[1]))

    # 항상 문서 앞 2000자 포함 (요약·핵심 수치 보통 앞에 위치)
    head_chunk = full_text[:2000].strip()
    result_parts = [head_chunk] if head_chunk else []
    total = len(head_chunk) if head_chunk else 0

    for s, e in scored:
        if total >= max_chars:
            break
        chunk = full_text[s:e].strip()
        if not chunk:
            continue
        # 앞부분과 겹치는 구간 건너뜀
        if s < 2100:
            continue
        if total + len(chunk) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                result_parts.append(chunk[:remaining])
            break
        result_parts.append(chunk)
        total += len(chunk)

    return "\n\n---\n\n".join(result_parts) if result_parts else full_text[:max_chars]


def _python_extract_key_sentences(
    context: str,
    question: str,
    keywords: list[str],
    max_chars: int = 5000,
) -> str:
    """Qwen 없이 Python으로 관련 문장 추출.

    1. 컨텍스트를 문장 단위로 분리
    2. 질문 키워드 매칭 점수 계산
    3. 수치/날짜 포함 보너스
    4. 상위 문장들을 max_chars 이내로 반환
    """
    import re as _re

    q_tokens = set(_re.findall(r"[가-힣]{2,}|\d+\.?\d*", question))
    kw_all = set(kw.lower() for kw in keywords if kw) | set(t.lower() for t in q_tokens)

    # 문장 분리 (마침표·줄바꿈 기준)
    raw_sents = _re.split(r"(?<=[다.。])\s*\n+|(?<=다\.)\s+|(?<=다\.\n)", context)
    # 추가: 줄 단위로도 분리
    lines = context.split("\n")
    candidates = []
    for item in raw_sents + lines:
        s = item.strip()
        if len(s) >= 15:
            candidates.append(s)

    # 중복 제거
    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    # 점수 계산
    scored = []
    for sent in unique:
        sl = sent.lower()
        distinct = sum(1 for kw in kw_all if kw in sl)
        if distinct == 0:
            continue
        # 수치 보너스
        num_bonus = len(_re.findall(r"\d+\.?\d*\s*[%％만억조백천]", sent)) * 1.0
        scored.append((distinct + num_bonus, sent))

    scored.sort(key=lambda x: -x[0])

    # 상위 항목들을 max_chars 이내로 수집
    result = []
    total = 0
    for _, sent in scored:
        if total + len(sent) > max_chars:
            break
        result.append(sent)
        total += len(sent)

    return "\n".join(result) if result else ""


def generate_node(state: dict) -> dict:
    """[v6] scan 청크 + fitz 앞부분 직접 조합 → 단순 생성.

    전략:
    - scan_node 청크 (키워드 targeted, scan이 이미 검증)
    - fitz로 원본 PDF 앞 5000자 (보고서 요약·핵심 수치 보통 앞에 위치)
    - 추출 단계 없이 직접 컨텍스트를 Qwen에 전달
    """
    question        = state["question"]
    model           = state["model"]
    thread_id       = state["thread_id"]
    matched_sources = state.get("matched_sources") or []
    detail_keywords = state.get("detail_keywords") or []
    file_keywords   = state.get("file_keywords") or []
    all_keywords    = list(dict.fromkeys(file_keywords + detail_keywords))

    prior_history = _load_history(thread_id)
    route = state.get("route", "rag")
    is_followup = route == "followup"

    # followup 모드: 이전 답변을 질문 앞에 명시 (모델이 무엇을 다뤄야 할지 명확히)
    if is_followup and prior_history:
        prev_turns = []
        for m in prior_history[-4:]:
            role = "사용자" if m.get("role") == "user" else "AI"
            prev_turns.append(f"[{role}]: {m.get('content','')[:500]}")
        prev_ctx = "\n".join(prev_turns)
        question = f"[이전 대화 참고]\n{prev_ctx}\n\n[현재 요청] {question}"

    # ── 컨텍스트 구성 ───────────────────────────────────────────────────
    full_sources = []
    fitz_heads: dict[str, str] = {}   # file_id → fitz 원문 앞 3000자 (key_facts용)

    for src in matched_sources:
        file_type = src.get("file_type", "")
        file_id   = src.get("file_id", src.get("file_name", ""))
        if file_type == "doc":
            # A) scan_node 청크 (이미 keyword-targeted)
            scan_chunks = src.get("matched_chunks") or []
            scan_text = "\n\n".join(c.strip() for c in scan_chunks if c.strip())

            # B) fitz 전체 PDF → 앞 5000자 + 키워드 주변 추가
            full_text = _read_source_full_text(src, max_chars=800000)
            if full_text:
                head = full_text[:5000]
                # fitz 원문 앞 3000자 별도 보관 (key_facts 전용, combined와 독립)
                fitz_heads[file_id] = full_text[:3000]
                extra = _keyword_target_paragraphs(
                    full_text[5000:], question, all_keywords, max_chars=5000
                )
                combined = "\n\n===\n\n".join(
                    p for p in [scan_text, head, extra] if p.strip()
                )
            else:
                combined = scan_text

            logger.info(f"[generate_node] {src.get('file_name','?')}: combined={len(combined)}ch")
            full_sources.append({**src, "matched_chunks": [combined[:15000]]})
        else:
            full_sources.append(src)

    context = _build_rag_context(full_sources if full_sources else matched_sources)

    # ── Python으로 핵심 수치 문장 추출 (forced-quote용) ──────────────────
    # followup 모드에서는 추출 생략 — "쉽게 설명해줘"같은 모호한 질문에서
    # 엉뚱한 숫자를 잡아 오히려 오답 유발. prior_history를 컨텍스트로 사용.
    key_facts: list[str] = []
    if is_followup:
        logger.info("[generate_node] followup 모드 → key_facts 추출 생략")
    else:
        for src in matched_sources:
            file_id = src.get("file_id", src.get("file_name", ""))

            # A) scan_chunks
            scan_chunks = src.get("matched_chunks") or []
            scan_text = "\n".join(c for c in scan_chunks if c)

            # B) fitz 원문 head[:3000] (파일별로 독립 — 다른 파일 숫자 혼입 방지)
            fitz_head = fitz_heads.get(file_id, "")

            # scan_chunks: 기본 임계값(min_score=1) — 이미 키워드 타겟팅됨
            if scan_text:
                facts = _python_extract_key_facts(scan_text, question, max_facts=4, min_score=1)
                key_facts.extend(facts)

            # fitz_head: 엄격한 임계값(min_score=4) — 질문과 강하게 관련된 문장만
            # (FAO head처럼 무관한 숫자가 많은 경우 필터링)
            if fitz_head:
                head_facts = _python_extract_key_facts(fitz_head, question, max_facts=3, min_score=4)
                key_facts.extend(head_facts)

    # 중복 제거 + 최대 6개
    seen: set[str] = set()
    deduped: list[str] = []
    for f in key_facts:
        if f not in seen:
            seen.add(f)
            deduped.append(f)
    key_facts = deduped[:6]
    logger.info(f"[generate_node] key_facts {len(key_facts)}개 추출 (scan+fitz_head3000)")

    # key_facts SSE 이벤트 → UI에서 "📌 핵심 인용" 섹션으로 표시
    if key_facts:
        _emit({"type": "key_facts", "facts": key_facts})

    # generating 시작 알림
    _emit({"type": "generating"})

    # ── 직접 생성 (핵심 수치 강제 인용 포함) ─────────────────────────────
    messages = _build_rag_messages(
        question, context, matched_sources, prior_history,
        extracted="", key_facts=key_facts,
    )

    full_answer  = ""
    stream_error = None
    try:
        for tok in _ollama_stream(messages, model, num_predict=-1):  # 토큰 제한 없음
            full_answer += tok
            _emit({"type": "token", "text": tok})
    except Exception as e:
        stream_error = str(e)
        logger.warning(f"[generate_node] stream 중단: {e}")

    if full_answer and len(full_answer.strip()) >= 10 and not stream_error:
        _save_history(thread_id, question, full_answer)
        # followup을 위해 이번 턴 파일 저장
        if matched_sources:
            with _prev_sources_lock:
                _prev_sources_store[thread_id] = list(matched_sources)

    _emit({
        "type":          "done",
        "answer":        full_answer,
        "model":         model,
        "sources_count": len(matched_sources),
        "error":         stream_error,
    })

    return {"answer": full_answer}


# ══════════════════════════════════════════════════════════════════════
# LangGraph 그래프 빌드
# ══════════════════════════════════════════════════════════════════════

_rag_graph      = None
_rag_graph_lock = threading.Lock()


def _get_rag_graph():
    """RAG 그래프 싱글턴 (lazy init)."""
    global _rag_graph
    if _rag_graph is not None:
        return _rag_graph
    with _rag_graph_lock:
        if _rag_graph is not None:
            return _rag_graph
        try:
            if not _LANGGRAPH_OK:
                raise RuntimeError("LangGraph 미설치")

            builder = StateGraph(RAGState)
            builder.add_node("router",           router_node)
            builder.add_node("intent",           intent_node)
            builder.add_node("search",           search_node)
            builder.add_node("scan",             scan_node)
            builder.add_node("select",           select_node)
            builder.add_node("followup_select",  followup_select_node)
            builder.add_node("direct_generate",  direct_generate_node)
            builder.add_node("generate",         generate_node)
            builder.add_node("qa_generate",      qa_generate_node)

            # START → router
            builder.add_edge(START, "router")

            # router → 조건 분기
            # (qa_gen → _route_edge 내부에서 "rag" 반환 → intent 공유)
            builder.add_conditional_edges(
                "router",
                _route_edge,
                {
                    "rag":      "intent",
                    "chat":     "direct_generate",
                    "followup": "followup_select",
                },
            )

            # rag / qa_gen 공통 경로 (intent → search → scan → select)
            builder.add_edge("intent",  "search")
            builder.add_edge("search",  "scan")
            builder.add_edge("scan",    "select")

            # select 이후 분기: qa_gen → qa_generate, rag → generate
            builder.add_conditional_edges(
                "select",
                _after_select_edge,
                {
                    "generate":    "generate",
                    "qa_generate": "qa_generate",
                },
            )

            # followup 경로
            builder.add_edge("followup_select", "generate")

            # 종료
            builder.add_edge("generate",        END)
            builder.add_edge("direct_generate", END)
            builder.add_edge("qa_generate",     END)

            checkpointer = MemorySaver()
            _rag_graph = builder.compile(checkpointer=checkpointer)
            logger.info("[aimode] LangGraph RAG 그래프 빌드 완료")
        except Exception as e:
            logger.warning(f"[aimode] 그래프 빌드 실패, 폴백 모드: {e}")
            _rag_graph = None
    return _rag_graph


# ══════════════════════════════════════════════════════════════════════
# 메인 RAG SSE 제너레이터
# ══════════════════════════════════════════════════════════════════════

def _run_nodes_fallback(state: dict) -> None:
    """LangGraph 없을 때 노드를 순서대로 직접 호출."""
    update = router_node(state); state.update(update)
    route = state.get("route", "rag")

    if route == "chat":
        direct_generate_node(state)
        return

    if route == "followup":
        update = followup_select_node(state); state.update(update)
        generate_node(state)
        return

    # rag / qa_gen 공통 파이프라인 (intent → search → scan → select)
    update = intent_node(state);   state.update(update)
    update = search_node(state);   state.update(update)
    if not state.get("candidates"):
        _emit({"type": "error", "message": "검색 결과 없음 — 다른 질문을 시도해보세요."})
        return
    update = scan_node(state);     state.update(update)
    update = select_node(state);   state.update(update)

    # 최종 생성 분기
    if route == "qa_gen":
        update = qa_generate_node(state); state.update(update)
    else:
        update = generate_node(state);    state.update(update)


def _rag_sse(question: str, topk: int, thread_id: str) -> Generator[str, None, None]:
    """LangGraph 그래프를 별도 스레드에서 실행하고, 노드가 투척한 이벤트를 SSE로 전달."""
    from queue import Queue, Empty

    def emit(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    # Ollama 연결 확인
    model = _get_ollama_model()
    if not model:
        yield emit({"type": "error",
                    "message": "Ollama 미연결. 'ollama pull qwen2.5:7b' 실행 후 재시도."})
        return

    yield emit({"type": "info", "model": model, "thread_id": thread_id,
                "langgraph": _LANGGRAPH_OK})

    # 이벤트 큐 생성
    q: Queue = Queue()

    initial_state = {
        "question":        question,
        "thread_id":       thread_id,
        "topk":            topk,
        "model":           model,
        "route":           "",
        "prev_sources":    [],
        "intent_message":  "",
        "file_keywords":   [],
        "detail_keywords": [],
        "candidates":      [],
        "scan_results":    [],
        "matched_sources": [],
        "answer":          "",
        "qa_question":     "",
        "qa_answer":       "",
        "qa_attempts":     0,
    }

    def run_graph():
        # thread-local 큐 연결
        _tls.event_queue = q
        try:
            graph = _get_rag_graph()
            if graph is not None:
                cfg = {"configurable": {"thread_id": thread_id}}
                graph.invoke(initial_state, config=cfg)
            else:
                # LangGraph 없으면 노드 직접 순서 실행
                _run_nodes_fallback(dict(initial_state))
        except Exception as e:
            logger.exception(f"[rag_sse] 그래프 실행 오류: {e}")
            q.put({"type": "error", "message": str(e)})
        finally:
            _tls.event_queue = None
            q.put(None)  # 종료 신호

    threading.Thread(target=run_graph, daemon=True).start()

    # 큐에서 이벤트 꺼내서 SSE로 전달
    while True:
        try:
            ev = q.get(timeout=180)
        except Empty:
            yield emit({"type": "error", "message": "타임아웃 (180초)"})
            break
        if ev is None:
            break
        yield emit(ev)


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
      1) file_path 가 .pdf → fitz 직접 읽기 (캐시 없이 항상 원본 PDF)
      2) docx/hwp 등 → converted_pdf/ 에서 변환본 탐색 → fitz
      3) python-docx fallback (.docx)
      4) 텍스트 파일 직접 읽기
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

    rid = source.get("trichef_id") or ""
    m = re.match(r"^page_images/(.+)/p\d+\.(?:jpg|png)$", rid)

    # ── 1순위: PDF → fitz 직접 읽기 (항상 원본 PDF, 캐시 우회) ──────
    if ext == ".pdf":
        if fp.exists() and fp.stat().st_size > 0:
            try:
                import fitz as _fitz
                import re as _re

                def _join_pdf_lines(text: str) -> str:
                    """fitz PDF 소프트 줄바꿈 제거 — 문장 중간 줄바꿈을 공백으로 합침.

                    한국어 PDF는 단어 중간에 줄바꿈이 들어가는 경우가 많다.
                    다음 줄이 소문자·숫자·한글로 시작하고 이전 줄이
                    문장 종결자(다/요/죠/함/임/!/?)로 끝나지 않으면 합침.
                    """
                    _SENT_END = frozenset([
                        "다",  # 다
                        "요",  # 요
                        "죠",  # 죠
                        "함",  # 함
                        "임",  # 임
                        "!", "?", "。",  # 。
                    ])
                    _BULLET = _re.compile(r"^[·•\-\d①②③④⑤]")
                    lines = text.split("\n")
                    result = []
                    for line in lines:
                        if (result
                                and line
                                and result[-1]
                                and result[-1][-1] not in _SENT_END
                                and not _BULLET.match(line.strip())
                                and not line.strip().startswith("[")
                                and not line.strip().startswith("(")
                        ):
                            result[-1] += line  # 이전 줄에 이어붙임
                        else:
                            result.append(line)
                    return "\n".join(result)

                texts = []
                total = 0
                with _fitz.open(str(fp)) as doc:
                    for i, page in enumerate(doc):
                        t = page.get_text("text") or ""
                        t = _join_pdf_lines(t.strip())
                        if t:
                            texts.append(t)
                            total += len(t)
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
