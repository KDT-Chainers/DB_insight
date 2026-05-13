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
SUPPORTED_GEMMA_MODELS = ("gemma3:12b", "gemma3:4b", "gemma3:4b-it-qat")
SCAN_DELAY  = 0.05   # [v3.2 speed] 파일 스캔 간 UI 애니메이션 딜레이 — 0.25 → 0.05 (-1s/turn)


# ── LangGraph 통합 ────────────────────────────────────────────────
_LANGGRAPH_OK = False


def _add_messages(left: list, right: list) -> list:
    return (left or []) + (right or [])


try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

    class RAGState(TypedDict, total=False):
        # 입력
        question:                str
        thread_id:               str
        topk:                    int
        model:                   str
        # router_node 출력 [v3] route 는 "rag" | "followup" 만
        route:                   str
        prev_sources:            list[dict]   # followup 시 이전 턴 matched_sources
        fallback_from_followup:  bool         # followup → rag 사이클 폴백 마커 (무한루프 방지)
        # intent_node 출력
        intent_message:          str
        file_keywords:           list[str]
        detail_keywords:         list[str]
        rag_mode:                str          # [v3] "structured" | "open"
        # search_node 출력
        candidates:              list[dict]
        # scan_node 출력
        scan_results:            list[dict]
        # select_node 출력
        matched_sources:         list[dict]
        # [v3] extract_node 출력
        references:              list[dict]   # [{src, type, page, timestamp, snippet, score}]
        # generate_node 출력
        answer:                  str
        # [legacy] qa_generate_node 출력 (v3 그래프 미사용)
        qa_question:             str
        qa_answer:               str
        qa_attempts:             int

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
    """[v3] LangGraph store 시도 후 비어있으면 fallback dict 확인.

    이전 버전: LangGraph 가 성공 응답해도 messages 필드가 비어있으면 빈 리스트 반환 →
    router 가 history 없음으로 판단 → followup 분류 실패.
    수정: LangGraph 결과가 비어있으면 fallback dict 까지 확인 (이중 보장).
    """
    g = _get_history_graph()
    if g is not None:
        try:
            cfg = {"configurable": {"thread_id": thread_id}}
            st = g.get_state(cfg)
            if st and st.values:
                msgs = st.values.get("messages") or []
                if msgs:
                    out = []
                    for m in msgs:
                        role = "user" if m.__class__.__name__ == "HumanMessage" else "assistant"
                        out.append({"role": role, "content": getattr(m, "content", "")})
                    return out
        except Exception as e:
            logger.debug(f"[aimode] history load 실패: {e}")
    # LangGraph 가 비어있거나 실패 → fallback dict (in-memory)
    with _fallback_lock:
        h = list(_fallback_history.get(thread_id, []))
    if h:
        return h
    # [v3 sidebar] in-memory 도 비어있으면 SQLite 에서 복원 (백엔드 재시작 후 사이드바 클릭 시)
    db_h = _load_chat_history_from_db(thread_id)
    if db_h:
        # in-memory 캐시도 복원 (다음 호출 시 SQLite 안 거치게)
        with _fallback_lock:
            _fallback_history[thread_id] = [
                {"role": m["role"], "content": m["content"]} for m in db_h
            ]
        return [{"role": m["role"], "content": m["content"]} for m in db_h]
    return []


def _save_history(thread_id: str, question: str, answer: str):
    """[v3] LangGraph store + fallback dict + SQLite 3중 저장.

    - LangGraph: thread state (검증된 path 지만 messages silent drop 가능)
    - fallback dict: in-memory 보강 (즉시 읽기용)
    - SQLite: 영속 (백엔드 재시작 후에도 사이드바 채팅방 목록·history 복원)
    """
    # 1) LangGraph store 시도 (실패해도 무시)
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
        except Exception as e:
            logger.debug(f"[aimode] LangGraph history save 실패 (fallback 사용): {e}")

    # 2) fallback dict (in-memory)
    with _fallback_lock:
        h = _fallback_history.setdefault(thread_id, [])
        h.append({"role": "user",      "content": question})
        h.append({"role": "assistant", "content": answer})
        if len(h) > 40:
            _fallback_history[thread_id] = h[-40:]

    # 3) SQLite 영속 저장 — 사이드바 채팅방 목록 / 재시작 후 복원
    try:
        _persist_chat_turn(thread_id, question, answer)
    except Exception as e:
        logger.warning(f"[aimode] SQLite 저장 실패: {e}")


# ══════════════════════════════════════════════════════════════════════
# [v3 sidebar] SQLite 채팅방·메시지 영속화
# ══════════════════════════════════════════════════════════════════════

def _generate_thread_title(first_question: str, model: str) -> str:
    """[v3] 첫 질문 → 짧은 한국어 채팅방 제목 (LLM 1회 호출).

    [v3.1] 길이 무관 항상 LLM 호출 — "산업 동향 알려줘" 같은 짧은 질문도 의미 정제.
    LLM 실패 시 truncate fallback.
    """
    q = (first_question or "").strip()
    if not q:
        return "새 대화"
    try:
        prompt = (
            "사용자의 질문을 보고 짧은 채팅방 제목(한국어, 12자 이내)을 만들어.\n"
            "규칙:\n"
            "- 물음표·따옴표 금지\n"
            "- 핵심 주제 명사만 (동사 '알려줘'·'찾아줘' 제거)\n"
            "- 질문이 짧아도 정제해서 명사구로\n\n"
            "예시:\n"
            "질문: SW산업 보고서에서 취업유발효과 찾아줘 → SW산업 취업유발효과\n"
            "질문: DBMS 시장 세계 전망 알려줘 → DBMS 시장 전망\n"
            "질문: 삼성전자 ESG 보고서의 탄소중립 목표는? → 삼성전자 탄소중립\n"
            "질문: 산업 동향 알려줘 → 산업 동향\n"
            "질문: 보이저호가 나오는 부분 알려줘 → 보이저호 등장 부분\n"
            "질문: SW산업 수출액은 얼마야? → SW산업 수출액\n\n"
            f"질문: {q}\n"
            "제목:"
        )
        raw = _ollama_oneshot(prompt, model, num_predict=20).strip()
        # 정리: 첫 줄만, 특수문자 제거
        title = raw.split("\n")[0].strip().strip('"').strip("'").strip(".").strip(":")
        # 최소/최대 길이 체크
        if 2 <= len(title) <= 30:
            logger.info(f"[thread_title] LLM 제목 생성: {q[:30]!r} → {title!r}")
            return title
        logger.debug(f"[thread_title] LLM 결과 길이 이상 ({len(title)}자): {title!r}")
    except Exception as e:
        logger.debug(f"[thread_title] LLM 실패, truncate fallback: {e}")
    # 폴백: 질문에서 검색 동사 제거 후 truncate
    import re as _re_tt
    cleaned = _re_tt.sub(r"(알려줘|찾아줘|보여줘|어디|있어|있나|뭐야|얼마야|어떻게|왜)", "", q).strip()
    cleaned = _re_tt.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = q
    return (cleaned[:28] + "…") if len(cleaned) > 28 else cleaned


def _persist_chat_turn(thread_id: str, question: str, answer: str) -> None:
    """[v3] aimode_threads + aimode_messages 에 한 turn 영속화.

    - thread 가 없으면 INSERT (제목 자동 생성)
    - 있으면 updated_at + msg_count UPDATE
    - aimode_messages 에 user/assistant 2개 INSERT
    """
    from db.init_db import get_connection
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        # thread 존재 여부 확인
        row = conn.execute(
            "SELECT thread_id, msg_count FROM aimode_threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()

        if row is None:
            # 새 thread → 제목 자동 생성
            model = _get_ollama_model() or "gemma3:4b"
            title = _generate_thread_title(question, model)
            conn.execute(
                """INSERT INTO aimode_threads
                       (thread_id, title, created_at, updated_at, msg_count, first_query)
                   VALUES (?, ?, ?, ?, 2, ?)""",
                (thread_id, title, now, now, question),
            )
            logger.info(f"[chat_turn] 새 thread 생성: {thread_id[:16]}... title={title!r}")
        else:
            conn.execute(
                """UPDATE aimode_threads
                       SET updated_at = ?, msg_count = msg_count + 2
                       WHERE thread_id = ?""",
                (now, thread_id),
            )

        # messages 누적
        conn.execute(
            """INSERT INTO aimode_messages (thread_id, role, content, created_at)
               VALUES (?, 'user', ?, ?)""",
            (thread_id, question, now),
        )
        conn.execute(
            """INSERT INTO aimode_messages (thread_id, role, content, created_at)
               VALUES (?, 'assistant', ?, ?)""",
            (thread_id, answer, now),
        )
        conn.commit()


def _load_chat_history_from_db(thread_id: str) -> list[dict]:
    """[v3] SQLite 에서 thread 메시지 복원 (사이드바 클릭 시 turn 복원용)."""
    from db.init_db import get_connection
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT role, content, created_at
                   FROM aimode_messages
                   WHERE thread_id = ?
                   ORDER BY id ASC""",
                (thread_id,),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
                for r in rows]
    except Exception as e:
        logger.debug(f"[load_chat_history] {e}")
        return []


def _list_threads(limit: int = 50) -> list[dict]:
    """[v3] 사이드바 채팅방 목록 (updated_at 내림차순)."""
    from db.init_db import get_connection
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT thread_id, title, created_at, updated_at, msg_count, first_query
                   FROM aimode_threads
                   ORDER BY updated_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"[list_threads] {e}")
        return []


def _update_thread_title(thread_id: str, new_title: str) -> bool:
    from db.init_db import get_connection
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    new_title = (new_title or "").strip()[:60]
    if not new_title:
        return False
    try:
        with get_connection() as conn:
            r = conn.execute(
                "UPDATE aimode_threads SET title = ?, updated_at = ? WHERE thread_id = ?",
                (new_title, now, thread_id),
            )
            conn.commit()
            return r.rowcount > 0
    except Exception as e:
        logger.warning(f"[update_thread_title] {e}")
        return False


def _delete_thread_from_db(thread_id: str) -> None:
    from db.init_db import get_connection
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM aimode_messages WHERE thread_id = ?", (thread_id,))
            conn.execute("DELETE FROM aimode_threads WHERE thread_id = ?", (thread_id,))
            conn.commit()
    except Exception as e:
        logger.warning(f"[delete_thread_db] {e}")


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
    # [v3 sidebar] SQLite 영속 데이터도 삭제
    _delete_thread_from_db(thread_id)


# ── 이전 턴 파일 소스 저장소 (followup 용) ────────────────────────────
_prev_sources_store: dict[str, list[dict]] = {}
_prev_sources_lock = threading.Lock()


# ── Ollama 함수 ────────────────────────────────────────────────────
def _is_supported_gemma_model(name: str) -> bool:
    lowered = name.lower()
    return any(model in lowered for model in SUPPORTED_GEMMA_MODELS)


def _get_ollama_model(task: str | None = None) -> str | None:
    """설치된 Ollama 모델 중 태스크에 맞는 최적 모델 반환.

    허용 모델: qwen2.5:1.5b / qwen2.5:3b / gemma3:4b / gemma3:4b-it-qat / gemma3:12b
    한국어 품질·VRAM 미검증 모델(llama3, mistral, phi4 등)은 fallback 에서 제외.

    task="summarize" : gemma3:4b(설치 시 우선) → qwen2.5:3b(VRAM 스왑 없이 공존) → gemma3:4b-it-qat → qwen2.5:1.5b → gemma3:12b
                       [이유] gemma3:4b-it-qat(4.2GB)는 VRAM 스왑+디스크 재로드로 30~60s 소요 → 90s 타임아웃 위험.
                             qwen2.5:3b(2.0GB)는 임베더와 공존 가능(스왑 불필요) → GPU ~40 tok/s 즉시 추론.
    task="generate"  : gemma3:4b-it-qat → gemma3:4b → qwen2.5:3b → qwen2.5:1.5b → gemma3:12b
    task=None        : gemma3:4b-it-qat → gemma3:4b → qwen2.5:3b → qwen2.5:1.5b → gemma3:12b
    """
    try:
        r = _req.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        models = r.json().get("models", [])
        # summarize: gemma3:4b 우선(3.5GB) → qwen2.5:3b(2.0GB, 스왑 불필요) → gemma3:4b-it-qat(폴백)
        # 현재 gemma3:4b 미설치 환경: qwen2.5:3b 선택 → VRAM 스왑 없이 즉시 GPU 추론 → 타임아웃 해소.
        # gemma3:4b 설치 시 자동으로 gemma3:4b 우선 적용.
        # 미검증 모델(llama3, mistral, phi4 등) 제외 — 한국어 품질·VRAM 보장 불가.
        if task == "summarize":
            # 1순위: 이미 로드돼 있는 모델 재사용 (재로드 30~60s 방지)
            loaded = _get_loaded_model_names()
            for cand in ("gemma3:4b", "gemma3:4b-it-qat", "qwen2.5:3b", "qwen2.5:1.5b"):
                if any(cand in n for n in loaded):
                    logger.info(f"[model_select] 이미 로드됨 → {cand} 재사용")
                    for m in models:
                        if cand in m.get("name", "").lower():
                            return m["name"]
            # 2순위: VRAM 잔여 확인. gemma3:4b 우선, 부족 시 qwen2.5:3b 폴백
            free_mb = _get_free_vram_mb()
            # 안전 임계치: 4500MB (gemma3:4b 3.5GB + context 1GB 버퍼)
            if free_mb >= 4500:
                preferred = ["gemma3:4b", "gemma3:4b-it-qat", "qwen2.5:3b",
                             "qwen2.5:1.5b", "gemma3:12b"]
                logger.info(f"[model_select] VRAM 충분({free_mb}MB) → gemma3:4b 우선")
            else:
                preferred = ["qwen2.5:3b", "qwen2.5:1.5b", "gemma3:4b",
                             "gemma3:4b-it-qat", "gemma3:12b"]
                logger.info(f"[model_select] VRAM 부족({free_mb}MB) → qwen2.5:3b 폴백")
        else:
            preferred = ["gemma3:4b-it-qat", "gemma3:4b", "qwen2.5:3b", "qwen2.5:1.5b",
                         "gemma3:12b"]
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
        return None
    except Exception:
        return None


# 모델별 예상 VRAM 사용량 (MB) — VRAM 스왑 필요 여부 판단용
_MODEL_VRAM_MB: dict[str, int] = {
    "qwen2.5:1.5b":    1200,
    "qwen2.5:3b":      2000,
    "gemma3:4b":       3500,
    "gemma3:4b-it-qat": 4200,
    "gemma3:12b":      8300,
}


def _get_free_vram_mb() -> int:
    """현재 GPU 잔여 VRAM (MB). nvidia-smi 호출.

    1) 이미 로드된 모델 고려 (Ollama가 재사용)
    2) 임베더 점유분 고려
    측정 실패 시 0 반환 → 폴백(작은 모델) 선택.
    """
    try:
        import subprocess as _sp
        r = _sp.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=3, text=True,
        )
        if r.returncode == 0:
            # 멀티 GPU 가능 — 첫 번째 GPU 값 사용
            line = r.stdout.strip().split("\n")[0].strip()
            return int(line) if line.isdigit() else 0
    except Exception as e:
        logger.debug(f"[vram] nvidia-smi 실패: {e}")
    return 0


def _get_loaded_model_names() -> set[str]:
    """현재 Ollama에 로드돼 있는 모델 이름 집합 (재사용 가능 판단)."""
    try:
        r = _req.get(f"{OLLAMA_URL}/api/ps", timeout=2)
        return {m.get("name", "") for m in (r.json().get("models") or [])}
    except Exception:
        return set()


def _ollama_oneshot(prompt: str, model: str, num_predict: int = 150,
                    keep_alive: int = 0) -> str:
    """단발 Ollama 추론.

    [VRAM 최적화] keep_alive=0 기본값: 추론 완료 즉시 모델 언로드.
    임베딩/검색 모델(SigLIP2+BGE-M3 ~5GB)과 VRAM 경합 방지.
    AI 검색 세션 내 연속 호출 시 재로드 오버헤드(~2s)는 감수.
    """
    try:
        r = _req.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False,
                  "keep_alive": keep_alive,
                  # [v3.2 fix] num_ctx=8192 — 기본 4096 으로는 긴 프롬프트 silent hang
                  "options": {"temperature": 0.1, "num_predict": num_predict, "num_ctx": 8192}},
            timeout=30,
        )
        r.raise_for_status()
        raw = (r.json().get("response") or "").strip()
        # [v3] Gemma3 special token (<unused344> 등) 노출 차단
        return _strip_special_tokens(raw)
    except Exception as e:
        logger.warning(f"[aimode] Ollama oneshot 실패: {e}")
        return ""


# [v3] Gemma3 special token 정규식 — 모델이 vocab 의 unused/제어 토큰을 문자 그대로
# 출력하는 케이스 차단. 예: "<unused344>", "<pad>", "<eos>", "<start_of_turn>" 등.
import re as _re_spec
_GEMMA_SPECIAL_RE = _re_spec.compile(
    r"<(?:unused\d+|pad|eos|bos|/s|s|end_of_turn|start_of_turn|im_start|im_end)>",
    _re_spec.IGNORECASE,
)


def _strip_special_tokens(text: str) -> str:
    """Gemma3 등 LLM 이 텍스트로 흘려보내는 vocab 특수 토큰 제거."""
    if not text:
        return text
    return _GEMMA_SPECIAL_RE.sub("", text)


def _ollama_stream(messages: list[dict], model: str,
                   num_predict: int = -1,
                   temperature: float = 0.3,
                   chunk_size: int = 80,
                   keep_alive: int = -1) -> Generator[str, None, None]:
    """Ollama 스트리밍 응답.

    chunk_size>0 이면 토큰을 buffer 에 모아 N자 이상이거나 줄바꿈을 만나면 한 번에 yield.
    한 글자씩 떠오르는 답답함을 줄이고 "줄 단위로 차라락" 나오는 UX 제공.
    chunk_size=0 이면 토큰을 받는 즉시 yield (기존 동작).
    keep_alive: Ollama 모델 메모리 유지 시간(초). 0=즉시 해제, -1=기본값(5분).

    [v3] 모든 yield 전에 _strip_special_tokens 적용 — Gemma3 의 <unused344> 같은
    vocab 토큰이 답변에 그대로 노출되는 케이스 차단.
    """
    try:
        with _req.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model":      model,
                "messages":   messages,
                "stream":     True,
                # [v3.2 fix] num_ctx 명시 — Ollama 기본 4096 토큰으로는 system prompt+history+
                # PDF 본문 합치면 초과 → silent hang. 8192 로 늘려서 여유 확보.
                "options":    {"temperature": temperature, "num_predict": num_predict, "num_ctx": 8192},
                "keep_alive": keep_alive,
            },
            stream=True, timeout=600,
        ) as resp:
            resp.raise_for_status()
            buf = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                tok = d.get("message", {}).get("content", "")
                if tok:
                    if chunk_size <= 0:
                        cleaned = _strip_special_tokens(tok)
                        if cleaned:
                            yield cleaned
                    else:
                        buf += tok
                        if "\n" in buf or len(buf) >= chunk_size:
                            cleaned = _strip_special_tokens(buf)
                            if cleaned:
                                yield cleaned
                            buf = ""
                if d.get("done"):
                    break
            if buf:
                cleaned = _strip_special_tokens(buf)
                if cleaned:
                    yield cleaned
    except Exception as e:
        logger.warning(f"[aimode] Ollama stream 실패: {e}")


# ══════════════════════════════════════════════════════════════════════
# [v3.3] 노드 종료 시 자원 해제 + 안정화 대기 헬퍼
# ══════════════════════════════════════════════════════════════════════

def _release_and_wait(
    node_name: str,
    seconds: float = 2.0,
    release_embedders: bool = False,
    release_ollama_model: str | None = None,
    empty_cache: bool = True,
) -> None:
    """노드 작업 끝나면 GPU 자원 해제하고 N초 대기.

    8GB VRAM 환경에서 임베더 ↔ LLM 동시 적재 시 OOM 발생 → 사이에 강제 해제 + 대기 삽입.

    Args:
        node_name: 로그용 노드 이름
        seconds: 해제 후 대기 시간 (실제 GPU 메모리 release 보장)
        release_embedders: True 면 검색 임베더 4개 (SigLIP2/BGE-M3/DINOv2/Reranker) 해제
        release_ollama_model: 모델 이름 주면 Ollama keep_alive=0 요청으로 unload
        empty_cache: torch.cuda.empty_cache() + synchronize 호출
    """
    actions = []

    # 1) 임베더 해제 (Python 프로세스 GPU 메모리)
    if release_embedders:
        try:
            free_before = _get_free_vram_mb()
            _release_search_embedders()
            actions.append(f"임베더 해제 ({free_before}MB)")
        except Exception as e:
            logger.debug(f"[release_and_wait] {node_name}: 임베더 해제 실패: {e}")

    # 2) Ollama 모델 unload (별도 프로세스)
    if release_ollama_model:
        try:
            _req.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": release_ollama_model, "keep_alive": 0,
                      "prompt": "", "stream": False},
                timeout=5,
            )
            actions.append(f"Ollama({release_ollama_model}) unload")
        except Exception as e:
            logger.debug(f"[release_and_wait] {node_name}: Ollama unload 실패: {e}")

    # 3) torch cache 비우기 + 동기화 (실제 GPU 메모리 release)
    if empty_cache:
        try:
            import torch as _t
            if _t.cuda.is_available():
                _t.cuda.empty_cache()
                _t.cuda.synchronize()
                actions.append("cuda cache 비움")
        except Exception:
            pass

    # 4) 안정화 대기 — GPU 메모리 실제 release 가 비동기라 시간 필요
    if seconds > 0:
        time.sleep(seconds)
        actions.append(f"{seconds}s 대기")

    if actions:
        free_after = _get_free_vram_mb()
        logger.info(f"[release_and_wait] {node_name}: {' + '.join(actions)} → 여유 VRAM {free_after}MB")


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
    # [v2] 일반 동사·부사 — 고유명사가 아니라 대부분 문서에 등장해 오탐 유발
    # 예: "보이저호가 나오는 부분" → "나오", "부분" 이 SW중심사회PDF 에서도 매칭
    "나오", "나온", "나와", "나오는", "나왔", "나옵",
    "부분", "구간", "장면", "순간", "구절", "단락",
    "모든", "전체", "각각", "일부", "여러", "다양", "특히", "또한",
    "처음", "마지막", "이번", "다음", "이전", "현재", "최근",
    "것을", "것은", "것도", "이것", "그것", "저것",
    "경우", "방법", "방식", "결과", "과정", "상황", "이유",
))


def _classify_query_mode(question: str, model: str) -> str:
    """[v3] 사용자 query 분류 — structured vs open.

    structured: "X에서 Y 찾아줘" — 파일이 명시됨 (file 후보 좁히기 → 본문 매칭)
    open:       "Y 찾아줘"       — 파일 미지정 (모든 색인 청크에서 substring 직접 매칭)
    """
    prompt = (
        "사용자 질문을 두 가지 모드로 분류해. 다른 글자 절대 금지.\n\n"
        "structured → 질문에 '~에서', '~에 있는', '~보고서의', '~문서의' 등으로 특정 파일/문서를 명시한 경우\n"
        "              예: 'SW산업 보고서에서 취업유발효과 찾아줘'\n"
        "              예: '삼성전자 ESG 보고서의 탄소중립 목표는?'\n"
        "              예: '코스모스 다큐에서 보이저호 나오는 부분 알려줘'\n"
        "open       → 질문에 파일이 명시되지 않고 키워드만 있는 경우\n"
        "              예: '취업유발효과 찾아줘'\n"
        "              예: '보이저호 어디 나와?'\n"
        "              예: 'DBMS 시장 전망'\n"
        "              예: '삼성전자 재생에너지 전환율'\n\n"
        f"질문: {question}\n"
        "분류 결과 (structured 또는 open):"
    )
    raw = _ollama_oneshot(prompt, model, num_predict=10).strip().lower()
    return "structured" if "structured" in raw else "open"


def _extract_open_keywords(question: str) -> list[str]:
    """[v3] open mode 키워드 추출 — 동사·조사 제거 후 명사구.

    [v3.1] phrase + 단어 둘 다 반환:
    - 동사 제거 후 남은 cleaned 가 다단어면 phrase("산업 동향") 를 1순위
    - 그리고 개별 토큰("산업", "동향") 도 추가
    - fulltext_search 가 distinct 매칭 단어 수로 점수 → phrase + 단어 둘 다 매칭 시 점수 ↑

    예:
      "산업 동향 알려줘"   → ["산업 동향", "산업", "동향"]
      "취업유발효과 찾아줘" → ["취업유발효과"]
      "SW산업 연간보고서"  → ["SW산업 연간보고서", "SW산업", "연간보고서"]
      "DBMS 시장 세계 전망" → ["DBMS 시장 세계 전망", "DBMS", "시장", "세계", "전망"]
    """
    import re as _re_ok
    # 검색 동사 제거
    _SEARCH_VERBS = (
        "찾아줘", "찾아 줘", "찾아주", "찾아봐", "찾고", "찾을",
        "보여줘", "보여 줘", "보여주", "보여",
        "알려줘", "알려 줘", "알려",
        "어디", "있어", "있나", "있을", "있는",
        "나와", "나오", "나타",
    )
    cleaned = question
    for v in _SEARCH_VERBS:
        cleaned = cleaned.replace(v, " ")
    # 의문 부호 제거
    cleaned = _re_ok.sub(r"[?？!]", "", cleaned)

    # 조사 제거 헬퍼
    _JOSA = ("에서의", "에서", "에는", "에게", "한테", "부터", "까지",
             "이랑", "과의", "와의", "으로", "로서", "으로서",
             "의", "에", "과", "와", "이", "가", "을", "를", "은", "는",
             "도", "로", "만")
    def _strip(w: str) -> str:
        for j in _JOSA:
            if w.endswith(j) and len(w) > len(j) + 1:
                return w[:-len(j)]
        return w

    # 1) 단어 단위 토큰 추출
    tokens = _re_ok.findall(r"[가-힣A-Za-z0-9]{2,}", cleaned)
    words: list[str] = []
    seen: set = set()
    for t in tokens:
        s = _strip(t)
        if len(s) >= 2 and s not in _STOPWORDS and s.lower() not in seen:
            seen.add(s.lower())
            words.append(s)

    # 2) [v3.1] phrase 만들기 — 공백 포함 + 공백 제거 두 형태 모두
    #    한국어 PDF 는 "산업 동향" / "산업동향" 양쪽 표기가 흔함 → 둘 다 매칭.
    #    예: ["산업", "동향"] → ["산업동향", "산업 동향"]
    kws: list[str] = []
    if len(words) >= 2:
        phrase_spaced = " ".join(words[:4])      # "산업 동향"
        phrase_joined = "".join(words[:4])       # "산업동향"
        # 공백 제거 형태를 1순위로 (더 구체적인 매칭)
        if phrase_joined != phrase_spaced and phrase_joined not in kws:
            kws.append(phrase_joined)
        if phrase_spaced not in kws:
            kws.append(phrase_spaced)
    # 개별 단어도 추가 — phrase 매칭 안 되는 페이지에서 fallback
    for w in words:
        if w not in kws:
            kws.append(w)
    return kws[:6]


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
def _scan_pdf_pages(file_path: str, keywords: list[str],
                    window: int = 400, max_chunks: int = 6
                    ) -> list[dict]:
    """[v3] PDF 를 페이지 단위로 fitz 추출 + 키워드 매칭 → 페이지 정보 포함 chunks.

    각 chunk: {"text": str, "page": int (1-indexed), "score": int}

    - 페이지마다 fitz 추출
    - 페이지 내부에서 키워드 매칭 위치 ±window 자 윈도우
    - 페이지별 점수 = 매칭된 distinct 키워드 수 (목차/색인은 보통 키워드 1~2종만 cluster → 낮은 점수)
    - 본문 섹션은 키워드 cluster + 단위 숫자(%, 억, 만, 원) 보너스
    - max_chunks 개 반환 (페이지 점수 내림차순)
    """
    from pathlib import Path
    import re as _re

    fp = Path(file_path)
    if not fp.exists() or fp.suffix.lower() != ".pdf" or not keywords:
        return []

    kws_lower = [k.lower() for k in keywords if k]
    if not kws_lower:
        return []

    page_hits: list[tuple[int, int, str]] = []  # (page_num, score, chunk_text)
    try:
        import fitz as _fitz
        with _fitz.open(str(fp)) as doc:
            for page_idx, page in enumerate(doc):
                page_text = (page.get_text("text") or "").strip()
                if not page_text:
                    continue
                tl = page_text.lower()

                # 페이지 내 키워드 위치
                positions: dict[str, list[int]] = {}
                for kw in kws_lower:
                    plist = []
                    start = 0
                    while True:
                        p = tl.find(kw, start)
                        if p < 0:
                            break
                        plist.append(p)
                        start = p + 1
                    if plist:
                        positions[kw] = plist

                if not positions:
                    continue

                # distinct 매칭 키워드 수 = 페이지 기본 점수
                distinct = len(positions)
                # 단위 포함 숫자 보너스 (본문 섹션 우대) — 목차는 페이지번호만 있어서 단위 없음
                unit_nums = len(_re.findall(r"\d+\.?\d*\s*(?:%|억|만|천|원|달러|건|개)", page_text))
                # 목차 점선 패널티
                toc_dots = page_text.count("…")
                score = distinct * 3 + min(unit_nums, 5) - min(toc_dots // 5, 5)

                # 페이지에서 키워드 가장 dense 한 위치 ±window 자 chunk
                # composite center 잡기 (페이지 내부에서 키워드 모인 곳)
                centers: list[tuple[int, int]] = []  # (score, pos)
                for kw, pos_list in positions.items():
                    for pos in pos_list:
                        nearby = sum(
                            1 for other_kw, other_list in positions.items()
                            if other_kw != kw and any(abs(p2 - pos) <= window * 2 for p2 in other_list)
                        )
                        centers.append((nearby + 1, pos))
                if not centers:
                    continue
                centers.sort(key=lambda x: -x[0])
                best_pos = centers[0][1]
                c_start = max(0, best_pos - window)
                c_end = min(len(page_text), best_pos + window)
                chunk_text = page_text[c_start:c_end].strip()
                chunk_text = _re.sub(r"\n{3,}", "\n\n", chunk_text)

                if chunk_text:
                    page_hits.append((page_idx + 1, score, chunk_text))  # 1-indexed page
    except Exception as e:
        logger.debug(f"[scan_pdf_pages] {fp.name}: {e}")
        return []

    # 점수 내림차순 → top max_chunks
    page_hits.sort(key=lambda x: -x[1])
    return [
        {"text": text, "page": page_num, "score": score}
        for page_num, score, text in page_hits[:max_chunks]
    ]


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
    elif file_type in ("video", "movie", "audio", "music", "bgm"):
        # AV: snippet + 모든 STT 세그먼트 텍스트를 합쳐 검색
        parts = [source.get("snippet") or ""]
        for seg in (source.get("segments") or []):
            t = (seg.get("text") or seg.get("preview") or "").strip()
            if t:
                parts.append(t)
        full_text = " ".join(parts)
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


def _fmt_seg_ts(seconds) -> str:
    """초를 MM:SS 또는 HH:MM:SS 로 변환. 비디오/오디오 segment 타임스탬프용."""
    try:
        s = int(float(seconds or 0))
    except (TypeError, ValueError):
        return "00:00"
    if s >= 3600:
        return f"{s//3600}:{(s%3600)//60:02d}:{s%60:02d}"
    return f"{s//60}:{s%60:02d}"


def _build_av_chunk_with_timestamps(src: dict, max_segments: int = 8) -> str:
    """비디오/오디오 source 의 segments 를 [MM:SS] 텍스트 형태로 직렬화.

    LLM 이 forced-quote 에서 timestamp 와 STT 텍스트를 함께 보고 답변에 인용 가능하도록.
    답변 예: "보이저호의 골든디스크 펄사 지도는 [32:21] 부분에서 언급됩니다"
    """
    segments = src.get("segments") or []
    seg_lines = []
    for seg in segments[:max_segments]:
        text = (seg.get("text") or seg.get("preview") or "").strip()
        if not text:
            continue
        ts = _fmt_seg_ts(seg.get("start"))
        seg_lines.append(f"[{ts}] {text}")
    return "\n".join(seg_lines)


def _build_rag_messages(
    question: str,
    context: str,
    matched_sources: list[dict],
    prior_history: list[dict],
    extracted: str = "",
    key_facts: list[str] | None = None,
    references: list[dict] | None = None,
) -> list[dict]:
    """RAG 시스템 프롬프트 + 대화 이력 + 사용자 질문 → messages 리스트.

    [v7] forced-quote: key_facts 이중 노출.
    [v3] references: extract_node 가 만든 (page/timestamp 메타) → 인용 형식 강제.
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

    # [v3.1] 위치 정보 블록 — 답변에 페이지/timestamp 인용 강제. 사용 가능한 태그만 명시.
    refs_block = ""
    available_tags: list[str] = []
    if references:
        ref_lines = []
        for r in references[:8]:
            src = r.get("src", "?")
            if r.get("page") is not None:
                tag = f"({r['page']}페이지)"
                available_tags.append(tag)
            elif r.get("timestamp"):
                tag = f"[{r['timestamp']}]"
                available_tags.append(tag)
            else:
                tag = ""
            snip = (r.get("snippet") or "")[:120]
            ref_lines.append(f"  {tag} {src}: {snip}")
        if ref_lines:
            tags_str = ", ".join(dict.fromkeys(available_tags)) if available_tags else "(없음)"
            refs_block = (
                "[원본 위치 정보 — 답변에서 출처 표시 시 아래 태그 그대로 사용]\n"
                + "\n".join(ref_lines)
                + f"\n사용 가능한 태그: {tags_str}\n\n"
            )

    # 비디오/오디오 출처 포함 여부
    has_av = any(
        s.get("file_type") in ("video", "movie", "audio", "music", "bgm")
        for s in matched_sources
    )
    has_doc = any(s.get("file_type") == "doc" for s in matched_sources)
    citation_rules = []
    if has_doc:
        citation_rules.append("- 문서 인용 시: 각 문장 또는 항목 끝에 반드시 (XX페이지) 형식으로 페이지 번호 표시. 페이지 번호 누락 금지.")
    if has_av:
        citation_rules.append("- 비디오/오디오 인용 시: 반드시 [MM:SS] 또는 [HH:MM:SS] 타임스탬프 표기. 타임스탬프 누락 금지.")
    if has_doc or has_av:
        citation_rules.append("- 위 [원본 위치 정보] 에 나열된 페이지/타임스탬프 외에 새 페이지·시각을 만들면 안 됩니다.")
    citation_block = "[인용 형식 — 반드시 준수]\n" + "\n".join(citation_rules) + "\n" if citation_rules else ""

    sys_msg = f"""[CRITICAL — 언어 규칙]
반드시 한국어(한글)로만 답변하세요. **영어·스페인어·일본어·중국어·한자·기타 외국어 절대 금지**.
숫자와 단위 외 모든 단어는 한글로만 쓸 것. 예: "달러" OK, "dólares" 절대 금지.
답변 첫 글자부터 마지막 글자까지 한글이어야 합니다.

당신은 아래 [문서 발췌]를 보고 [질문]에 답하는 AI입니다.
{forced_block}{refs_block}{citation_block}
[절대 규칙]
1. **한국어만 사용**. 외국어 단어 한 개라도 섞이면 답변 무효.
2. [핵심 인용] 또는 [문서 발췌]에 관련 내용이 있으면 **반드시 그 내용을 사용해 답변** 하세요.
3. 숫자·비율·날짜는 반드시 [핵심 인용] 또는 [문서 발췌]에 있는 것만 쓰세요.
4. 학습 데이터에서 알고 있는 수치/사실을 쓰면 안 됩니다. 문서 내용만 사용.
5. 발췌에 없는 내용 추가 금지.
6. **답변의 모든 사실 진술 뒤에 반드시 (XX페이지) 또는 [MM:SS] 태그를 붙이세요.** 태그는 위 [원본 위치 정보] 에 나열된 것만 사용 가능.
7. [핵심 인용]·[문서 발췌] 모두 비어있는 경우에만 "제공 문서에 해당 정보가 없습니다"라고 쓰세요.

[답변 형식 — 반드시 준수]
- **간결한 마크다운(Markdown)** 으로 답변. 총 분량은 짧게 (도입 1줄 + 핵심 3~4 bullet + 마무리 1줄).
- 답변 길이는 **최대 8~10줄 / 약 3~4문장 분량**. 장황한 부연·반복 금지.
- 마크다운 규칙:
  · 핵심 키워드는 **굵게** (`**텍스트**`).
  · 항목 나열은 `- ` 불릿 (3~4개).
  · 필요하면 작은 소제목 `## 제목` 한 개까지 허용.
  · 표는 사용하지 말 것.
- 첫 줄은 핵심 한 줄 요약, 그 다음 빈 줄 후 `- ` 불릿으로 핵심 사실 3~4개, 마지막에 한 줄 마무리.
- 각 불릿은 **1~2문장 이내**로 짧고 단정하게.

[답변 형식 예시 — 이 정도 분량/구조로만]
2016년 세계 **DBMS 시장**은 빅데이터 수요 확대로 성장세에 진입했습니다 (40페이지).

- **시장 규모**: 2016년 317억 달러, 전년 대비 **6.4% 성장** 예상 (40페이지).
- **성장률 전망**: 2014~2019년 연평균 **5.2%**, 2019년 384억 달러 도달 (40페이지).
- **주요 동인**: 빅데이터·인메모리 DB·DB 어플라이언스 수요 확대 (40페이지).

빅데이터 확산이 안정적인 6%대 성장세를 이끌 전망입니다.

[참고 파일]
{source_list if source_list else '  (매칭 파일 없음)'}

[문서 발췌]
{doc_body if doc_body else '(발췌 없음)'}"""

    messages: list[dict] = [{"role": "system", "content": sys_msg}]
    if prior_history:
        messages.extend(prior_history[-6:])

    # 유저 메시지에도 핵심 인용을 앞에 박음 (이중 노출)
    answer_length_req = (
        "\n\n[답변 요구사항 — 반드시 준수]\n"
        "- 한국어로만 답변 (외국어 단어 절대 금지)\n"
        "- **간결한 마크다운**: 도입 1줄 + 핵심 불릿 3~4개 + 마무리 1줄. 총 8~10줄 / 3~4문장 분량.\n"
        "- 핵심은 `**굵게**`, 항목은 `- ` 불릿. 표·코드블록·긴 문단 금지.\n"
        "- 각 불릿은 1~2문장 이내로 짧고 단정하게. 같은 내용 반복 금지.\n"
        "- 배경·맥락 부연은 최소화하고 **핵심 사실 위주**로 간결하게."
    )
    if key_facts:
        quotes = "\n".join(f'- "{f}"' for f in key_facts if f.strip())
        user_content = (
            f"[문서 핵심 인용]\n{quotes}\n\n"
            f"위 인용문의 수치를 그대로 사용해서 다음 질문에 답하세요:\n{question}"
            f"{answer_length_req}"
        )
    else:
        user_content = f"{question}{answer_length_req}"

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

    # 줄바꿈 정규화 — fitz 소프트 줄바꿈으로 끊긴 문장 재결합.
    # "생산량은\n3,035.5백만톤으로\n5.8% 증가..." 처럼 한 문장이 여러 줄로 쪼개진 경우,
    # 직전 줄이 문장 종결자로 끝나지 않고 현재 줄이 불릿/괄호로 시작 안 하면 결합.
    # 단, 직전 줄이 "* 생산량 전망치..." 같은 불릿 라인이면 다음 줄 절대 병합 X
    # (불릿은 한 줄로 닫혀야 다음 narrative 와 분리됨).
    _SENT_END = ('다', '요', '죠', '함', '임', '.', '!', '?', '。', ':')
    _BULLET_RE = _re.compile(r'^\s*(?:[\*·•\-\(\[①②③④⑤]|\d+[.)]\s)')
    _normalized = []
    _prev_is_bullet = False
    for _ln in full_text.split('\n'):
        if not _ln.strip():
            _prev_is_bullet = False
            continue
        _is_bullet = bool(_BULLET_RE.match(_ln))
        if (_normalized
                and not _prev_is_bullet                                  # 불릿 다음엔 새 문장 시작
                and not _normalized[-1].rstrip().endswith(_SENT_END)
                and not _is_bullet):
            _normalized[-1] += ' ' + _ln.strip()
        else:
            _normalized.append(_ln)
            _prev_is_bullet = _is_bullet
    full_text = '\n'.join(_normalized)

    # 줄바꿈 / 문장 종결 기준으로 문장 분리
    raw_sents = _re.split(r'\n|(?<=[다요함임])\.\s*|(?<=[.!?])\s+', full_text)
    sentences = [s.strip() for s in raw_sents if len(s.strip()) > 20]

    # 질문 키워드 (2자 이상 한글 + 숫자)
    q_tokens = set(_re.findall(r'[가-힣]{2,}|\d+', question))

    # 결론형 패턴 — "X.X%(...) 증가/감소/상승/하락/기록/전망/예상/달성"
    # 분해 표 행보다 narrative 결론 문장을 forced-quote 에 우선 노출.
    # NOTE: lazy `.` 사용 — 십진수 마침표("167.8") 가 %와 동사 사이에 끼어도 통과.
    ANSWER_PATTERN = _re.compile(
        r'\d+\.?\d*\s*%.{0,40}?'
        r'(?:증가|감소|상승|하락|기록|전망|예상|달성|확대|축소|개선)'
    )

    scored = []
    for sent in sentences:
        score = 0
        # 숫자/비율/날짜 포함 시 가산점 — 단 raw 데이터 테이블이 점수 독식 못하게 cap=5.
        # (식량가격지수 표 한 줄에 25개 숫자 박혀 75점 먹는 케이스 차단)
        nums = _re.findall(r'\d+\.?\d*\s*%|\d{4}년|\d+\.\d+|\d+백만', sent)
        score += min(len(nums), 5) * 3
        # 질문 토큰 포함 시 가산점
        kw_hits = sum(1 for tok in q_tokens if tok in sent)
        score += kw_hits
        # 결론형 narrative 가산점 (분해 표 행 대신 결과 문장 우선)
        # 분해 표 행은 숫자수×3 으로 22점대 까지 올라가므로 +10 이상 필요.
        if ANSWER_PATTERN.search(sent):
            score += 10
        # 불릿/표 행 감점 ("* 쌀 563.3 / 잡곡 ..." 같은 분해 행 억제)
        if _re.match(r'^\s*[\*·•\-]', sent):
            score -= 3
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
    """[v3] 단순화: RAG / FOLLOWUP 2가지만 분류. chat·qa_gen 라우트 제거.

    핵심 규칙:
    - history 비어있음 (새 채팅 첫 메시지)  → 무조건 RAG
    - history 있음 + 이전 파일 있음          → LLM 분류 (RAG / FOLLOWUP)
    - history 있음 + 이전 파일 없음          → RAG
    - state["fallback_from_followup"] = True → FOLLOWUP 사이클 폴백 직후 → RAG 강제 (무한루프 방지)
    """
    question  = state["question"]
    model     = state["model"]
    thread_id = state["thread_id"]

    # [무한루프 방지] followup → rag 폴백 한 번 발생 후 다시 진입한 경우 RAG 강제.
    if state.get("fallback_from_followup"):
        logger.info("[router_node] fallback_from_followup → rag 강제")
        _emit({"type": "route", "mode": "rag"})
        return {"route": "rag", "prev_sources": []}

    # 이전 대화 이력
    history = _load_history(thread_id)

    # [v3 핵심] 새 채팅 (history 비어있음) → 무조건 RAG.
    if not history:
        logger.info("[router_node] history empty → rag (새 채팅)")
        _emit({"type": "route", "mode": "rag"})
        return {"route": "rag", "prev_sources": []}

    # 이전 파일 목록
    with _prev_sources_lock:
        prev_sources = list(_prev_sources_store.get(thread_id, []))

    # 이전 파일 없으면 followup 불가 → RAG
    if not prev_sources:
        logger.info("[router_node] prev_sources empty → rag")
        _emit({"type": "route", "mode": "rag"})
        return {"route": "rag", "prev_sources": []}

    history_text = ""
    for m in history[-6:]:
        role = "사용자" if m["role"] == "user" else "AI"
        history_text += f"{role}: {m['content'][:300]}\n"
    prev_files_text = ", ".join(s.get("file_name", "?") for s in prev_sources[:5])

    # LLM 분류 — RAG / FOLLOWUP 2가지만
    prompt = (
        "아래 질문을 딱 하나로만 분류해. 다른 글자 절대 금지.\n\n"
        "분류 기준:\n"
        "followup  → 이전 답변·파일에 대한 추가 요청. 이전 파일 본문 안에서 다시 찾을 수 있는 내용.\n"
        "            예: '쉽게 설명해줘', '요약해줘', '더 자세히', '그게 뭐야',\n"
        "                '거기서 ~는?', '방금 그거', '취업유발계수가 뭐야?' (이전 답변에 언급된 용어)\n"
        "rag       → 새로운 주제·다른 파일을 찾는 질문. 이전 파일과 무관한 내용.\n\n"
        "예시:\n"
        "이전 파일: SW산업.pdf / 질문: 쉽게 설명해줘 → followup\n"
        "이전 파일: SW산업.pdf / 질문: 취업유발계수가 뭐야? → followup\n"
        "이전 파일: SW산업.pdf / 질문: 거기서 DBMS 시장은? → followup\n"
        "이전 파일: SW산업.pdf / 질문: 전년대비 얼마나 상승했어? → followup\n"
        "이전 파일: SW산업.pdf / 질문: 전년대비 얼마야? → followup\n"
        "이전 파일: SW산업.pdf / 질문: 그 수치 근거는? → followup\n"
        "이전 파일: SW산업.pdf / 질문: 어떻게 변했어? → followup\n"
        "이전 파일: SW산업.pdf / 질문: 양자컴퓨터 동향은? → rag\n"
        "이전 파일: SW산업.pdf / 질문: 삼성전자 ESG 보고서 찾아줘 → rag\n\n"
        f"이전 대화:\n{history_text}\n"
        f"이전에 찾은 파일: {prev_files_text}\n"
        f"현재 질문: {question}\n\n"
        "분류 결과 (followup 또는 rag):"
    )

    raw = _ollama_oneshot(prompt, model, num_predict=10).strip().lower()
    route = "followup" if "followup" in raw else "rag"

    # [강제 RAG] 명백한 새 검색 의도 키워드가 있으면 LLM 분류 무시하고 RAG 강제.
    # 예: "○○ 찾아줘", "○○에 대한 자료" 등.
    _FORCE_RAG_KW = (
        "찾아줘", "찾아 줘", "찾아주", "찾아봐",
        "에 대한", "에 관한", "에 관련",
        "자료", "정보를",
    )
    if route == "followup" and any(kw in question for kw in _FORCE_RAG_KW):
        logger.info(f"[router_node] followup → rag 강제 (새 검색 의도)")
        route = "rag"

    # [강제 FOLLOWUP] 짧고 트리거 단어 + 새 고유명사 없으면 followup 강제.
    import re as _re_r
    if route == "rag":
        _FOLLOWUP_TRIGGERS = [
            "쉽게", "다시", "요약", "정리", "자세히", "설명해", "풀어줘",
            "더 알려줘", "그게", "거기서", "방금", "한국어로", "예시", "예를",
            # [v3.1] 후속 의문문 패턴
            "얼마", "얼마야", "어떻게", "어떤", "왜", "근거",
            "전년", "전년대비", "올해", "작년", "이전",
            "성장률", "증가율", "비율", "비교",
            "그 수치", "그게 어떤",
        ]
        q_len = len(question.strip())
        has_trigger = any(t in question for t in _FOLLOWUP_TRIGGERS)
        new_nouns = _re_r.findall(r"[가-힣A-Z][가-힣A-Za-z]{3,}", question)
        if q_len <= 30 and has_trigger and len(new_nouns) == 0:
            route = "followup"
            logger.info(f"[router_node] fallback followup (short+trigger)")

    # [v3.1] **마지막 보강** — history+prev_sources 있는 상태에서 짧은 의문문이고
    # 명시적 새 검색 의도(찾아줘/자료 등) 없으면 followup default.
    # "전년대비 얼마야?" 같은 일반 의문문이 LLM 에서 rag 로 잘못 분류되는 케이스 차단.
    if route == "rag" and history and prev_sources:
        q_stripped = question.strip()
        q_len = len(q_stripped)
        has_force_rag = any(kw in question for kw in _FORCE_RAG_KW)
        # 짧은 의문문 (≤25자) + 새 검색 의도 없음 → followup
        is_question_form = q_stripped.endswith(("?", "야?", "어?", "지?", "까?", "나?",
                                                 "?", "야", "어", "지", "까", "나"))
        if q_len <= 25 and not has_force_rag:
            route = "followup"
            logger.info(f"[router_node] 짧은 후속 질문 → followup 강제 (q_len={q_len})")

    logger.info(f"[router_node] raw={raw!r} → route={route}")
    _emit({"type": "route", "mode": route})

    return {
        "route":        route,
        "prev_sources": prev_sources if route == "followup" else [],
    }


def _route_edge(state: dict) -> str:
    """[v3] router 이후 — rag / followup 만."""
    route = state.get("route", "rag")
    return "followup" if route == "followup" else "rag"


def _after_followup_search_edge(state: dict) -> str:
    """[v3] followup_search 이후 — 이전 파일에서 매칭됐으면 extract, 아니면 RAG 사이클."""
    matched = state.get("matched_sources") or []
    if matched:
        return "exist"
    return "none"


def _after_intent_edge(state: dict) -> str:
    """[v3] RAG intent 이후 — rag_mode 에 따라 분기.

    structured: 기존 search → scan → select 경로
    open:       fulltext_search 1노드로 (search/scan/select 압축)
    """
    return "open" if state.get("rag_mode") == "open" else "structured"


# ── 노드 1: 의도 파악 + 키워드 추출 ─────────────────────────────────
def intent_node(state: dict) -> dict:
    """[v3] RAG intent — mode 분류 (structured / open) + 키워드 추출.

    - structured: "X에서 Y 찾아줘" → 기존 _extract_rag_intent (file_kw + detail_kw 분리)
    - open:       "Y 찾아줘"       → _extract_open_keywords (단순 명사구)
    """
    question = state["question"]
    model    = state["model"]

    # [v3] mode 분류
    mode = _classify_query_mode(question, model)
    logger.info(f"[intent_node] mode={mode} | question={question[:50]!r}")

    if mode == "structured":
        intent_msg, file_kws, detail_kws = _extract_rag_intent(question, model)
    else:  # open
        kws = _extract_open_keywords(question)
        if not kws:
            # LLM 백업 — 마지막 폴백
            _, f1, d1 = _extract_rag_intent(question, model)
            kws = list(dict.fromkeys((f1 or []) + (d1 or [])))[:3]
        intent_msg = f"'{', '.join(kws) or question}' 키워드로 모든 자료에서 찾아볼게요."
        file_kws   = kws
        detail_kws = kws

    _emit({
        "type":            "intent",
        "message":         intent_msg,
        "file_keywords":   file_kws,
        "detail_keywords": detail_kws,
        "mode":            mode,
    })

    # [v3.3] 노드 종료: intent LLM oneshot 끝났으니 GPU 캐시 비우고 대기
    # 다음 노드는 search (임베더 사용) — LLM 안 쓰니까 cache 만 비우면 충분
    _emit({"type": "node_done", "node": "intent", "next": "search/fulltext_search"})
    _release_and_wait("intent_node", seconds=2.0, release_embedders=False)

    return {
        "intent_message":  intent_msg,
        "file_keywords":   file_kws,
        "detail_keywords": detail_kws,
        "rag_mode":        mode,
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

    # [v3.3] 노드 종료: 검색 임베더 해제 + 2초 안정화 대기
    # 검색 끝났으니 임베더는 더 이상 필요 없음. LLM 이 GPU 자리 잡을 수 있게 비움.
    _emit({"type": "node_done", "node": "search", "next": "scan"})
    _release_and_wait("search_node", seconds=2.0, release_embedders=True)

    return {"candidates": candidates}


# ── 노드 3: 파일 하나씩 내용 확인 ────────────────────────────────────
def _scan_one(src: dict, detail_kws: list[str]) -> tuple[bool, list[dict]]:
    """[v3] 파일 1개 스캔 → (found, chunks). chunks 는 메타 포함 dict 리스트.

    chunk dict 스키마:
      doc:   {"text", "page" (1-indexed), "score"}
      video/audio/movie/music: {"text", "timestamp" (MM:SS or null), "score"}
      image: {"text", "page": None, "score"}
    """
    file_type = src.get("file_type", "")

    # ── doc: 페이지 단위 fitz 스캔 (원본 PDF 직접 읽기) ─────────────
    if file_type == "doc":
        file_path = (src.get("file_path") or "").strip()
        if file_path:
            chunks_meta = _scan_pdf_pages(file_path, detail_kws)
            if chunks_meta:
                return True, chunks_meta
        # 폴백: 페이지 단위 스캔 실패 시 기존 fulltext 스캔
        found, chunk_texts = _scan_file_for_keywords(src, detail_kws)
        return found, [{"text": t, "page": None, "score": 1} for t in chunk_texts]

    # ── video/audio: STT segments 에서 detail_kws 실제 매칭만 found=True ──
    # [v3.2 fix] 이전엔 segments 있기만 하면 무조건 True → 무관 AV 가 references 오염.
    # 이제 키워드 1개라도 segment·snippet·file_name 에 등장해야 found=True.
    _av_types = ("video", "movie", "audio", "music")
    if file_type in _av_types:
        kws_lower = [k.lower() for k in (detail_kws or []) if k and len(k) >= 2]
        if not kws_lower:
            return False, []

        av_chunks: list[dict] = []
        # 1) STT segments 안에서 키워드 매칭
        for seg in (src.get("segments") or [])[:30]:  # 5 → 30 (더 많은 segment 검사)
            text = (seg.get("text") or seg.get("preview") or "").strip()
            if not text:
                continue
            tl = text.lower()
            hits = sum(1 for kw in kws_lower if kw in tl)
            if hits == 0:
                continue  # 키워드 없는 segment 건너뜀
            ts_sec = seg.get("start")
            ts = _fmt_seg_ts(ts_sec) if ts_sec is not None else None
            av_chunks.append({"text": text, "timestamp": ts, "score": hits})

        # 2) segments 매칭 0개면 snippet 도 확인 (rare fallback)
        if not av_chunks:
            snip = (src.get("snippet") or "").strip()
            if snip:
                sl = snip.lower()
                hits = sum(1 for kw in kws_lower if kw in sl)
                if hits > 0:
                    av_chunks.append({"text": snip, "timestamp": None, "score": hits})

        # 3) 그래도 매칭 없으면 file_name 만 (제목 매칭만 있는 경우 — 약한 매칭)
        if not av_chunks:
            fname = (src.get("file_name") or "").lower()
            name_hits = sum(1 for kw in kws_lower if kw in fname)
            if name_hits >= 1:
                # 파일명만 매칭 → 낮은 score 로만 (1순위에서 밀려나기 좋게)
                av_chunks.append({"text": src.get("file_name", ""), "timestamp": None, "score": name_hits * 0.3})

        # 매칭 없으면 found=False
        if not av_chunks:
            return False, []
        # score 내림차순 top 5
        av_chunks.sort(key=lambda c: -c.get("score", 0))
        return True, av_chunks[:5]

    # ── image: snippet (캡션) 매칭 ─────────────────────────────────
    snip = src.get("snippet") or ""
    if not snip:
        return False, []
    sl = snip.lower()
    hits = sum(1 for kw in detail_kws if kw and kw.lower() in sl)
    if hits == 0:
        return False, []
    return True, [{"text": snip, "page": None, "score": hits}]


def scan_node(state: dict) -> dict:
    """[v3] 페이지/타임스탬프 메타 포함 chunks 생성."""
    from concurrent.futures import ThreadPoolExecutor

    candidates  = state.get("candidates") or []
    detail_kws  = state.get("detail_keywords") or []
    scan_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(_scan_one, src, detail_kws)
            for src in candidates
        ]

        for i, (src, fut) in enumerate(zip(candidates, futures)):
            file_id   = src.get("trichef_id") or str(i)
            file_name = src.get("file_name")  or "?"
            file_type = src.get("file_type")  or "?"

            _emit({
                "type":      "scanning",
                "index":     i,
                "file_id":   file_id,
                "file_name": file_name,
                "file_type": file_type,
            })

            try:
                found, chunks_meta = fut.result(timeout=30)
            except Exception as e:
                logger.debug(f"[scan_node] {file_name}: {e}")
                found, chunks_meta = False, []

            # SSE: 프론트엔드 호환 위해 chunks 는 text 만 평탄화. 메타는 chunks_meta 로.
            _emit({
                "type":        "scan_result",
                "index":       i,
                "file_id":     file_id,
                "found":       found,
                "chunks":      [c.get("text", "") for c in chunks_meta],
                "chunks_meta": chunks_meta,
            })

            scan_results.append({
                **src,
                "found":          found,
                "matched_chunks": [c.get("text", "") for c in chunks_meta],
                "chunks_meta":    chunks_meta,
            })
            time.sleep(SCAN_DELAY)

    # [v3.3] 노드 종료: scan 은 CPU(fitz) 만 쓰지만 다음 select→extract→generate 로 LLM 들어감.
    # GPU 정리 + 안정화.
    _emit({"type": "node_done", "node": "scan", "next": "select"})
    _release_and_wait("scan_node", seconds=2.0, release_embedders=True)

    return {"scan_results": scan_results}


# ── 노드 4: 내용 있는 파일만 선택 ────────────────────────────────────
def select_node(state: dict) -> dict:
    scan_results = state.get("scan_results") or []
    candidates   = state.get("candidates")   or []

    # [v2] found=True 이더라도 reranker 극단 부정(< -5.0) → 오탐 제거.
    # 문제: "나오" 같은 흔한 단어 매칭으로 SW중심사회 PDF 가 "코스모스 보이저호" 검색에서
    #   found=True 반환 → LLM 컨텍스트에 무관한 내용 주입 → 오답 또는 혼동 발생.
    # doc 한정 적용 (image/video/audio 는 snippet 기반 스캔이라 reranker 신뢰도 충분).
    _RR_REJECT = -5.0
    def _passes_rerank(r: dict) -> bool:
        if r.get("file_type") == "doc":
            rr = r.get("rerank_score")
            if rr is not None and float(rr) < _RR_REJECT:
                return False
        return True

    matched = [r for r in scan_results if r.get("found") and _passes_rerank(r)]

    # [v3.2 fix] 문서 매칭이 강하면 약한 AV 매칭 컷 — references 오염 방지.
    # 시나리오: PDF 가 페이지 단위 매칭(score 8+)인데 AV 가 파일명만 매칭(score 0.3)이면
    # AV 는 무관한 출처. doc score 가 top AV score 의 3배 이상이면 AV 컷.
    def _src_top_score(r: dict) -> float:
        chs = r.get("chunks_meta") or []
        if not chs:
            return 0.0
        return float(max(c.get("score", 0) for c in chs) or 0)

    doc_scores = [_src_top_score(r) for r in matched if r.get("file_type") == "doc"]
    av_types = {"video", "movie", "audio", "music", "bgm"}
    if doc_scores and max(doc_scores) >= 3.0:
        top_doc = max(doc_scores)
        before = len(matched)
        matched = [
            r for r in matched
            if r.get("file_type") not in av_types
            or _src_top_score(r) >= top_doc / 3.0
        ]
        if before != len(matched):
            logger.info(f"[select_node] AV 약한 매칭 컷: {before} → {len(matched)} (top_doc={top_doc:.1f})")

    # 매칭 파일 없으면 → rerank 통과한 후보 중 1위 강제 선택 (fallback)
    if not matched and candidates:
        logger.info("[select_node] 매칭 없음 → 1위 fallback")
        rr_ok = [c for c in candidates if _passes_rerank(c)]
        best = (rr_ok or candidates)[0]
        matched = [{**best, "found": True,
                    "matched_chunks": [best.get("snippet") or ""]}]

    _emit({"type": "selected", "sources": matched})

    # [v3.3] 노드 종료: VRAM 정리 + 2초 대기
    _emit({"type": "node_done", "node": "select", "next": "extract"})
    _release_and_wait("select_node", seconds=2.0, release_embedders=False)

    return {"matched_sources": matched}


# ── 노드 4-b: [legacy] followup 시 이전 파일 재사용 ───────────────────
#   v3 그래프에서는 followup_search_node 사용. 아래는 fallback 용으로 남겨둠.
def followup_select_node(state: dict) -> dict:
    """이전 턴의 파일을 그대로 matched_sources 로 사용."""
    prev = state.get("prev_sources") or []
    _emit({"type": "selected", "sources": prev})
    # [v3.2 speed] 0.1 → 0
    return {"matched_sources": prev}


# ── 노드 [v3] followup_intent: 후속 질문에서 키워드 추출 ──────────────
def followup_intent_node(state: dict) -> dict:
    """[v3] 후속 질문 → 이전 본문에서 찾을 키워드 추출.

    예: 이전 답이 "취업유발계수" 언급 → "취업유발계수가 뭐야?" → keywords=["취업유발계수"]
    """
    question = state["question"]
    model    = state["model"]
    thread_id = state["thread_id"]

    # 이전 대화 이력으로 컨텍스트 보강
    history = _load_history(thread_id)
    last_ai = ""
    if history:
        for m in reversed(history):
            if m.get("role") == "assistant":
                last_ai = (m.get("content") or "")[:600]
                break

    # [v3] 핵심 보강: 이전 답변의 **주제어**(고유명사·수치 명·문서 영역) + 현재 질문의
    # **묻는 측면**(증가율·정의·원인 등)을 결합해서 검색 키워드 만들기.
    # 사용자가 후속 질문할 땐 보통 이전 답변 주제 위에서 깊이 들어가는 거라,
    # 키워드에 이전 답변 주제어가 빠지면 followup_search 가 엉뚱한 청크 매칭.
    # 예) 이전 답: "SW산업 수출액 92억달러" / 질문: "전년대비 얼마나 상승?"
    #     → 키워드: ["SW산업 수출액 전년대비"] (단순 "전년대비"만 뽑으면 CRM 등 다른 시장 매칭 위험)
    prompt = (
        "이전 답변에서 다루던 주제어와 현재 질문의 의도를 결합해서 본문 검색용 키워드 1~3개를 만들어.\n"
        "출력은 쉼표로만 구분. 다른 글자 금지.\n\n"
        "규칙:\n"
        "- 이전 답변에서 핵심 주제(고유명사·수치 명·문서 영역)를 base 로 사용\n"
        "- 현재 질문이 묻는 측면(증가율·정의·근거·원인 등)을 base 에 덧붙임\n"
        "- 이전 답변 주제가 키워드에 반드시 포함되어야 함 (단독으로 '전년대비'·'정의'·'근거' 같은 일반어만 출력 금지)\n\n"
        "예시:\n"
        "이전 답변: 'SW산업 수출액은 2015년 92억달러로 ...' / 질문: '전년대비 얼마나 상승한거야?'\n"
        "  → SW산업 수출액 전년대비, 수출액 증감, SW산업 수출\n"
        "이전 답변: '취업유발계수는 0.816으로 제조업보다 높다' / 질문: '그게 뭐야?'\n"
        "  → 취업유발계수 정의, 취업유발계수\n"
        "이전 답변: 'DBMS 시장은 6.4% 성장' / 질문: '그 근거?'\n"
        "  → DBMS 시장 성장 근거, DBMS 시장 전망\n"
        "이전 답변: '삼성전자 2030 탄소중립 목표' / 질문: '거기서 재생에너지 전환율은?'\n"
        "  → 삼성전자 재생에너지 전환율, 재생에너지\n\n"
        f"이전 답변:\n{last_ai or '(없음)'}\n"
        f"현재 질문: {question}\n"
        "키워드:"
    )
    raw = _ollama_oneshot(prompt, model, num_predict=30).strip()
    # 쉼표/공백 분리 + 정리
    import re as _re_fi
    parts = _re_fi.split(r"[,、\n]+", raw)
    keywords: list[str] = []
    for p in parts:
        p = p.strip().strip(".").strip(":").strip("'").strip('"')
        if 2 <= len(p) <= 40 and p not in keywords:
            keywords.append(p)
    keywords = keywords[:3]

    # LLM 실패 → 질문에서 2자 이상 명사 추출
    if not keywords:
        import re as _re_fi2
        toks = _re_fi2.findall(r"[가-힣A-Za-z0-9]{2,}", question)
        keywords = [t for t in toks if t not in _STOPWORDS][:3]

    intent_msg = f"이전 파일에서 '{', '.join(keywords) or question}' 관련 부분을 찾아볼게요."
    _emit({
        "type":            "intent",
        "message":         intent_msg,
        "file_keywords":   keywords,
        "detail_keywords": keywords,
        "mode":            "followup",
    })

    # [v3.3] 노드 종료: followup_intent oneshot 끝 — GPU 정리 + 2초 대기
    _emit({"type": "node_done", "node": "followup_intent", "next": "followup_search"})
    _release_and_wait("followup_intent_node", seconds=2.0)

    return {
        "intent_message":  intent_msg,
        "file_keywords":   keywords,
        "detail_keywords": keywords,
    }


# ── 노드 [v3] followup_search: 이전 source 본문에서만 키워드 매칭 ─────
def followup_search_node(state: dict) -> dict:
    """[v3] 이전 turn 의 prev_sources 본문에서 새 키워드 매칭.

    매칭된 source 들만 matched_sources 로. 매칭 0이면 빈 리스트 → RAG 사이클 폴백.

    [v3.1] phrase 토큰 분해 추가: followup_intent 가 "SW산업 수출액 전년대비" 같은
    multi-word phrase 를 만들어내면, PDF 본문에 그 phrase 그대로 안 나타나 매칭 실패
    하는 케이스가 빈번. → phrase + 분해된 단어 모두 키워드 리스트에 넣고
    distinct 매칭 단어 수로 점수 매김.
    """
    from concurrent.futures import ThreadPoolExecutor

    prev_sources = state.get("prev_sources") or []
    detail_kws   = state.get("detail_keywords") or []
    if not prev_sources or not detail_kws:
        _emit({"type": "followup_search_result", "matched": 0, "tried": len(prev_sources)})
        return {"matched_sources": []}

    # [v3.1] phrase 토큰 분해 — multi-word 키워드를 단어 단위로도 매칭 시도
    _STOP_TOKENS = {"의", "는", "은", "이", "가", "을", "를", "와", "과", "에",
                    "정의", "근거", "원인", "변화", "추이", "현황"}
    expanded: list[str] = []
    seen: set = set()
    for kw in detail_kws:
        if not kw:
            continue
        # 원본 phrase 그대로 (정확 매칭 시 가산점 받음)
        k_lower = kw.lower()
        if k_lower not in seen:
            seen.add(k_lower)
            expanded.append(kw)
        # 공백 포함이면 단어 분해
        if " " in kw:
            for w in kw.split():
                w = w.strip()
                wl = w.lower()
                if len(w) >= 2 and wl not in seen and w not in _STOP_TOKENS:
                    seen.add(wl)
                    expanded.append(w)

    logger.info(
        f"[followup_search] original kws={detail_kws} → expanded={expanded}"
    )

    matched: list[dict] = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(_scan_one, src, expanded)
            for src in prev_sources
        ]
        for i, (src, fut) in enumerate(zip(prev_sources, futures)):
            try:
                found, chunks_meta = fut.result(timeout=30)
            except Exception as e:
                logger.debug(f"[followup_search] {src.get('file_name','?')}: {e}")
                continue
            if found and chunks_meta:
                matched.append({
                    **src,
                    "found":          True,
                    "matched_chunks": [c.get("text", "") for c in chunks_meta],
                    "chunks_meta":    chunks_meta,
                })

    _emit({
        "type":    "followup_search_result",
        "matched": len(matched),
        "tried":   len(prev_sources),
        "expanded_kw_count": len(expanded),
    })
    if matched:
        _emit({"type": "selected", "sources": matched})

    # [v3.3] followup_search 노드 종료: 임베더 해제 + 2초 대기
    _emit({"type": "node_done", "node": "followup_search", "next": "extract" if matched else "fallback"})
    _release_and_wait("followup_search_node", seconds=2.0, release_embedders=True)

    return {"matched_sources": matched}


# ══════════════════════════════════════════════════════════════════════
# [v3 open mode] 전체 색인 캐시에서 substring 매칭
# ══════════════════════════════════════════════════════════════════════

def fulltext_search_node(state: dict) -> dict:
    """[v3 open mode] 모든 색인된 doc 페이지 캐시 본문 + 파일명에서 키워드 substring 매칭.

    - page_text 캐시 (`TRICHEF_DOC_EXTRACT/page_text/<stem>/p####.txt`) 순회
    - 키워드 substring 매칭 → 페이지 단위 chunk + 점수
    - 파일명에 키워드 substring 있으면 보너스 +20
    - 같은 파일의 페이지들 묶어서 하나의 source 로 정리
    - 결과를 candidates / scan_results / matched_sources 모두에 동일하게 세팅
      (search/scan/select 단계를 압축 — 이후 extract → generate 로 직진)
    """
    from pathlib import Path
    import re as _re_ft

    keywords = state.get("detail_keywords") or state.get("file_keywords") or []
    kws_lower = [k.lower() for k in keywords if k and len(k) >= 2]
    if not kws_lower:
        logger.warning("[fulltext_search] 키워드 없음 — 빈 결과")
        _emit({"type": "candidates", "items": []})
        return {"candidates": [], "scan_results": [], "matched_sources": []}

    # ── 페이지 텍스트 캐시 루트 ─────────────────────────────────────────
    try:
        from config import PATHS
        page_text_root = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text"
    except Exception as e:
        logger.warning(f"[fulltext_search] PATHS 로드 실패: {e}")
        _emit({"type": "candidates", "items": []})
        return {"candidates": [], "scan_results": [], "matched_sources": []}

    if not page_text_root.is_dir():
        logger.warning(f"[fulltext_search] page_text 캐시 없음: {page_text_root}")
        _emit({"type": "candidates", "items": []})
        return {"candidates": [], "scan_results": [], "matched_sources": []}

    # ── doc registry 로드 (파일명 + 절대경로 추출) ─────────────────────
    doc_reg: dict = {}
    try:
        from config import PATHS as _PATHS_R
        import json as _json_r
        reg_path = Path(_PATHS_R["EMBEDDED_DB"]) / "Doc" / "registry.json"
        if reg_path.is_file():
            doc_reg = _json_r.loads(reg_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.debug(f"[fulltext_search] doc registry 로드 실패: {e}")

    # ── 1단계: 모든 페이지 캐시 순회 + substring 매칭 ──────────────────
    matched_pages: dict[str, list[dict]] = {}  # stem → [{page, text, score}]

    for stem_dir in page_text_root.iterdir():
        if not stem_dir.is_dir():
            continue
        stem = stem_dir.name
        for txt_path in sorted(stem_dir.glob("p*.txt")):
            try:
                page_idx = int(txt_path.stem.lstrip("p"))
            except ValueError:
                continue
            try:
                text = txt_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if not text or len(text) < 30:
                continue
            tl = text.lower()
            # substring 매칭 점수 — 키워드 등장 횟수 + distinct 키워드 가산점
            hit_counts = {kw: tl.count(kw) for kw in kws_lower}
            hits = sum(hit_counts.values())
            if hits == 0:
                continue
            distinct = sum(1 for c in hit_counts.values() if c > 0)
            # 단위 포함 숫자 보너스 (본문 우대 — DBMS 케이스 목차 vs 본문 구분)
            unit_nums = len(_re_ft.findall(r"\d+\.?\d*\s*(?:%|억|만|천|원|달러|건|개)", text))
            # 목차 페널티 강화 [v3.1]
            toc_dots = text.count("…")
            # "…42" 같은 페이지 참조 패턴 (목차 핵심 특징)
            toc_page_refs = len(_re_ft.findall(r"…+\s*\d{1,3}\b", text))
            # 목차 의심 강도 (0~1) — 페이지 참조가 많거나 점선 비율 높으면 강한 페널티
            is_toc_strong = (toc_page_refs >= 5) or (toc_dots >= 30)

            # [v3.1] phrase 매칭 보너스 — "산업 동향" 같은 공백 포함 phrase 가
            # 본문에 그대로 substring 매칭되면 큰 가산점. 단어 산발 매칭보다 우대.
            phrase_kws = [k for k in kws_lower if " " in k]
            phrase_hits = sum(tl.count(p) for p in phrase_kws)

            if is_toc_strong:
                # 목차로 확정 → 강한 페널티 (점수 1/4 + 추가 차감)
                score = (hits + distinct + min(unit_nums, 5)) // 2 - toc_page_refs
                # phrase 매칭은 목차 페이지에서도 의미 있음
                score += phrase_hits * 3
            else:
                # 본문 우대: 단위 숫자 가중치 ↑, 점선 가벼운 페널티
                # [v3.1] phrase 매칭 시 +10 (산발 단어 매칭보다 본문 우선)
                score = hits * 2 + distinct * 5 + min(unit_nums, 5) * 3 \
                        + phrase_hits * 10 - toc_dots // 3

            if score <= 0:
                continue

            # 매칭 위치 ±400자 윈도우
            first_pos = next((tl.find(kw) for kw in kws_lower if tl.find(kw) >= 0), 0)
            c_start = max(0, first_pos - 400)
            c_end   = min(len(text), first_pos + 400)
            chunk_text = text[c_start:c_end].strip()
            chunk_text = _re_ft.sub(r"\n{3,}", "\n\n", chunk_text)

            matched_pages.setdefault(stem, []).append({
                "text":  chunk_text,
                "page":  page_idx + 1,  # 1-indexed 사용자 표시
                "score": score,
            })

    # ── 2단계: stem → source 정리 (파일명 매칭 보너스 포함) ─────────────
    def _stem_to_real_name(s: str) -> str:
        """trichef stem '2015_SW산업 연간보고서__491c85c9' → '2015_SW산업 연간보고서.pdf'"""
        real = _re_ft.sub(r"__[a-f0-9]+$", "", s)
        return real + ".pdf"

    def _resolve_path(stem: str) -> str:
        """registry 에서 절대경로 찾기."""
        for key, val in doc_reg.items():
            if key.startswith(stem) or stem in key:
                if isinstance(val, dict):
                    abs_p = val.get("abs") or val.get("path") or ""
                    if abs_p:
                        return abs_p
        return ""

    candidates: list[dict] = []
    for stem, pages in matched_pages.items():
        file_name = _stem_to_real_name(stem)
        file_path = _resolve_path(stem)
        # 파일명 매칭 보너스
        fn_lower = file_name.lower()
        name_bonus = 0
        for kw in kws_lower:
            if kw in fn_lower:
                name_bonus += 20
        pages.sort(key=lambda x: -x["score"])
        top_pages = pages[:6]
        total_score = sum(p["score"] for p in top_pages) + name_bonus
        candidates.append({
            "file_name":      file_name,
            "file_path":      file_path,
            "file_type":      "doc",
            "trichef_id":     stem,
            "similarity":     round(min(1.0, total_score / 100.0), 4),
            "confidence":     round(min(1.0, total_score / 100.0), 4),
            "found":          True,
            "matched_chunks": [p["text"] for p in top_pages],
            "chunks_meta":    top_pages,
            "score":          total_score,
            "name_bonus":     name_bonus,
        })

    # ── 3단계: 파일명만 매칭되고 본문 매칭 없는 파일도 추가 ─────────────
    matched_stems = set(matched_pages.keys())
    for key, val in doc_reg.items():
        if not isinstance(val, dict):
            continue
        # stem 추출 — registry key 가 stem 일 수도 있음
        stem = key
        if stem in matched_stems:
            continue
        file_name = _stem_to_real_name(stem)
        fn_lower = file_name.lower()
        name_hits = sum(1 for kw in kws_lower if kw in fn_lower)
        if name_hits == 0:
            continue
        # 파일명만 매칭 — chunks 없음 (본문 없는 source)
        file_path = val.get("abs") or val.get("path") or ""
        candidates.append({
            "file_name":      file_name,
            "file_path":      file_path,
            "file_type":      "doc",
            "trichef_id":     stem,
            "similarity":     round(min(1.0, (name_hits * 20) / 100.0), 4),
            "confidence":     round(min(1.0, (name_hits * 20) / 100.0), 4),
            "found":          True,
            "matched_chunks": [],
            "chunks_meta":    [],
            "score":          name_hits * 20,
            "name_bonus":     name_hits * 20,
        })

    # ── 정렬 + topk 컷 ────────────────────────────────────────────────
    candidates.sort(key=lambda x: -x.get("score", 0))
    topk = max(5, state.get("topk", 10))
    candidates = candidates[:topk]

    logger.info(
        f"[fulltext_search] keywords={kws_lower} → {len(candidates)} sources "
        f"(top score={candidates[0].get('score') if candidates else 0})"
    )

    _emit({"type": "candidates", "items": candidates})
    if candidates:
        _emit({"type": "selected", "sources": candidates})

    # [v3.3] open 모드 노드 종료: 임베더 해제 + 2초 대기
    _emit({"type": "node_done", "node": "fulltext_search", "next": "extract"})
    _release_and_wait("fulltext_search_node", seconds=2.0, release_embedders=True)

    return {
        "candidates":      candidates,
        "scan_results":    candidates,
        "matched_sources": candidates,
    }


# ── 노드 [v3] extract: chunks 메타 정리 → references ──────────────────

def _looks_like_toc_snippet(text: str) -> bool:
    """[v3.1] 목차/색인 페이지 chunk 감지 — extract 단계에서 제외.

    판정 기준 (OR):
    - 점선 `…` 5개 이상
    - "…42" 같은 페이지 참조 패턴 3개 이상 (목차 핵심 특징)
    - 줄당 평균 길이 짧고 (≤30자) 거의 모든 줄이 숫자로 끝남
    """
    import re as _re_t
    if not text:
        return False
    if text.count("…") >= 5:
        return True
    if len(_re_t.findall(r"…+\s*\d{1,3}\b", text)) >= 3:
        return True
    # 줄 단위 분석
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return False
    short_lines = sum(1 for ln in lines if len(ln) <= 30)
    page_ending = sum(1 for ln in lines if _re_t.search(r"\d{1,3}\s*$", ln))
    # 절반 이상이 짧고 페이지번호로 끝나면 목차
    if len(lines) >= 4 and short_lines / len(lines) > 0.6 and page_ending / len(lines) > 0.5:
        return True
    return False


def extract_node(state: dict) -> dict:
    """[v3] matched_sources 의 chunks_meta 를 정리해서 references 만들기.

    references 형식:
      {"src": file_name, "type": doc/video/audio/image,
       "page": 35 (doc only) | None,
       "timestamp": "MM:SS" (av only) | None,
       "snippet": str (200자), "score": int}

    [v3.1] 목차/색인 chunk 자동 제외 (_looks_like_toc_snippet).
    SSE 'extract' 이벤트로 references 노출. generate 가 인용 시 사용.
    """
    matched = state.get("matched_sources") or []
    references: list[dict] = []
    skipped_toc = 0
    for src in matched:
        ftype = src.get("file_type", "")
        fname = src.get("file_name", "?")
        # [v3.1] 페이지 이미지 URL 구성용 식별자 — frontend 가 사용
        trichef_id = src.get("trichef_id") or ""
        file_path  = src.get("file_path") or ""
        for cm in (src.get("chunks_meta") or []):
            text = (cm.get("text") or "").strip()
            if not text:
                continue
            # [v3.1] 목차/색인 의심 chunk 제외 (doc 한정)
            if ftype == "doc" and _looks_like_toc_snippet(text):
                skipped_toc += 1
                continue
            ref = {
                "src":        fname,
                "type":       ftype,
                "snippet":    text[:200],
                "score":      cm.get("score", 0),
                "trichef_id": trichef_id,  # [v3.1] 페이지 이미지 fetch 용 stem
                "file_path":  file_path,    # [v3.1] PDF 절대 경로 (옵션)
            }
            if ftype == "doc":
                ref["page"] = cm.get("page")
                ref["timestamp"] = None
            elif ftype in ("video", "movie", "audio", "music"):
                ref["page"] = None
                ref["timestamp"] = cm.get("timestamp")
            else:
                ref["page"] = None
                ref["timestamp"] = None
            references.append(ref)

    # score 내림차순 정렬 (forced-quote 에서 상위 노출)
    references.sort(key=lambda r: -r.get("score", 0))

    if skipped_toc:
        logger.info(f"[extract_node] 목차/색인 chunk {skipped_toc}개 제외 → {len(references)} refs")

    _emit({
        "type":        "extract",
        "references":  references,
        "count":       len(references),
        "skipped_toc": skipped_toc,
    })

    # [v3.3] 노드 종료: generate 들어가기 직전 GPU 정리. 임베더 잔여분 마지막으로 비움.
    _emit({"type": "node_done", "node": "extract", "next": "generate"})
    _release_and_wait("extract_node", seconds=2.0, release_embedders=True)

    return {"references": references}


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

    # 하이브리드: 답변 생성은 작은 모델(4b)
    gen_model = _get_ollama_model("generate") or model

    for attempt in range(1, 4):  # 최대 3회
        attempts = attempt
        _emit({"type": "qa_generating", "attempt": attempt, "max": 3})

        raw = _ollama_oneshot(prompt, gen_model, num_predict=500)
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
        "gen_model":     gen_model,
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
        "[답변 형식]\n"
        "- 간결한 마크다운으로 답변. 도입 1줄 + 핵심 불릿 2~4개 + 마무리 1줄. 총 8줄 이내.\n"
        "- 핵심 키워드는 `**굵게**`. 항목은 `- ` 불릿.\n"
        "- 표·코드블록·긴 문단 금지. 각 불릿은 1~2문장 이내.\n"
        "- 모르는 것은 솔직하게 모른다고 말하세요."
    )

    messages: list[dict] = [{"role": "system", "content": sys_msg}]
    if prior_history:
        messages.extend(prior_history[-10:])
    messages.append({"role": "user", "content": question})

    full_answer  = ""
    stream_error = None
    # 하이브리드: 답변 생성은 작은 모델(4b) 사용. fallback 으로 state model 유지.
    gen_model = _get_ollama_model("generate") or model
    try:
        # [v3.1] chunk_size=0 → 토큰 받는 즉시 yield (타이핑 효과)
        # [v3.2] direct chat 도 간결 마크다운 — 300 tok 캡
        for tok in _ollama_stream(messages, gen_model, num_predict=300, chunk_size=0):
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
        "gen_model":     gen_model,
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
            # [v3.2 speed] prompt 길이 단축 — 8000 tok prefill → 3000 tok prefill (5~10s 절약)
            # A) scan_node 청크 (이미 keyword-targeted)
            scan_chunks = src.get("matched_chunks") or []
            scan_text = "\n\n".join(c.strip() for c in scan_chunks if c.strip())[:3000]

            # B) fitz 전체 PDF → 앞 2000자 + 키워드 주변 2000자
            full_text = _read_source_full_text(src, max_chars=200000)  # 800K → 200K (fitz I/O 단축)
            if full_text:
                head = full_text[:2000]                            # 5000 → 2000
                fitz_heads[file_id] = full_text[:3000]
                extra = _keyword_target_paragraphs(
                    full_text[2000:], question, all_keywords, max_chars=2000  # 5000 → 2000
                )
                combined = "\n\n===\n\n".join(
                    p for p in [scan_text, head, extra] if p.strip()
                )
            else:
                combined = scan_text

            logger.info(f"[generate_node] {src.get('file_name','?')}: combined={len(combined)}ch")
            full_sources.append({**src, "matched_chunks": [combined[:6000]]})  # 15000 → 6000
        elif file_type in ("video", "movie", "audio", "music", "bgm"):
            # 비디오/오디오: segments 를 [MM:SS] 형식으로 직렬화 → matched_chunks 주입
            # LLM 이 forced-quote 에서 timestamp 와 STT 를 함께 인용할 수 있게.
            av_chunk = _build_av_chunk_with_timestamps(src, max_segments=8)
            if av_chunk:
                logger.info(f"[generate_node] AV {src.get('file_name','?')}: segments={av_chunk.count(chr(10))+1}개")
                full_sources.append({**src, "matched_chunks": [av_chunk]})
            else:
                full_sources.append(src)
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

    # ── 직접 생성 (핵심 수치 강제 인용 + [v3] 위치 정보 references 포함) ──
    references = state.get("references") or []
    messages = _build_rag_messages(
        question, context, matched_sources, prior_history,
        extracted="", key_facts=key_facts, references=references,
    )

    full_answer  = ""
    stream_error = None
    # 하이브리드: 답변 생성은 작은 모델(4b). 검색/intent/scan 은 state["model"](12b) 유지.
    gen_model = _get_ollama_model("generate") or model

    # video/audio 답변은 타임스탬프 인용 위주로 짧게 — 토큰 상한으로 타임아웃 방지
    has_av = any(
        s.get("file_type", "") in ("video", "movie", "audio", "music", "bgm")
        for s in matched_sources
    )
    # [v3.2 speed] 간결 마크다운 답변 — 토큰 상한 더 낮춤 (350→250 / 250→200)
    np_limit = 200 if has_av else 250

    # ── [v3.3] generate 시작 전 — 임베더 완전 해제 + 2초 안정화 ──
    # 직전 노드들 (extract / followup_search) 에서 이미 해제 시도했지만, 마지막으로 강제 확인.
    # GPU 가 LLM 만 전유하게 만들고 2초 대기로 메모리 release 보장.
    _gen_vram_swapped = False
    _emit({"type": "debug", "stage": "before_vram_check"})
    try:
        import torch as _t
        if _t.cuda.is_available():
            _free_mb = int(_t.cuda.mem_get_info()[0] / 1024 / 1024)
            _emit({"type": "debug", "stage": "vram_check_done", "free_mb": _free_mb})
            if _free_mb < 4500:
                logger.info(f"[generate_node] 여유 VRAM {_free_mb} MB < 4500 → 강제 정리")
                _emit({"type": "info", "message": f"GPU 메모리 확보 중... (현재 {_free_mb}MB)", "free_mb": _free_mb})
                _release_and_wait("generate_node_pre",
                                   seconds=2.0,
                                   release_embedders=True,
                                   release_ollama_model=gen_model)
                _gen_vram_swapped = True
                _free_after = int(_t.cuda.mem_get_info()[0] / 1024 / 1024)
                _emit({"type": "debug", "stage": "vram_after_swap", "free_mb": _free_after})
    except Exception as _ve:
        logger.warning(f"[generate_node] VRAM 처리 실패: {_ve}")
        _emit({"type": "debug", "stage": "vram_error", "error": str(_ve)})

    # 총 prompt 길이 측정 → 사용자에게 prefill 예상시간 알림
    _total_chars = sum(len(m.get("content", "")) for m in messages)
    _emit({"type": "debug", "stage": "ollama_stream_start",
           "model": gen_model, "msg_count": len(messages),
           "prompt_chars": _total_chars})
    _emit({"type": "info",
           "message": f"AI 답변 생성 중... (prompt {_total_chars}자, prefill 약 5~10초)"})

    try:
        _keepalive = 0 if _gen_vram_swapped else -1
        _first_tok_sent = False
        _stream_t0 = time.time()
        for tok in _ollama_stream(messages, gen_model, num_predict=np_limit,
                                  chunk_size=0, keep_alive=_keepalive):
            if not _first_tok_sent:
                _ttft = time.time() - _stream_t0
                _emit({"type": "debug", "stage": "first_token_received",
                       "ttft_sec": round(_ttft, 2)})
                logger.info(f"[generate_node] TTFT (첫 토큰까지): {_ttft:.2f}s")
                _first_tok_sent = True
            full_answer += tok
            _emit({"type": "token", "text": tok})
        if not _first_tok_sent:
            _emit({"type": "debug", "stage": "stream_ended_no_tokens",
                   "elapsed_sec": round(time.time() - _stream_t0, 2)})
            logger.warning(f"[generate_node] 스트림 끝났는데 토큰 0개. 경과={time.time()-_stream_t0:.1f}s")
    except Exception as e:
        stream_error = str(e)
        logger.warning(f"[generate_node] stream 중단: {e}")
        _emit({"type": "debug", "stage": "stream_exception", "error": str(e)})

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
        "gen_model":     gen_model,
        "sources_count": len(matched_sources),
        "error":         stream_error,
    })

    # [v3.3] generate_node 종료: torch cache 정리만 (Ollama 모델은 keep_alive 로 유지)
    _emit({"type": "node_done", "node": "generate", "next": "END"})
    _release_and_wait("generate_node_post", seconds=0.5, release_embedders=False)

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
            # [v3] 노드: chat·qa_gen 제거. followup_intent / followup_search / fulltext_search / extract 신규.
            builder.add_node("router",            router_node)
            builder.add_node("intent",            intent_node)
            builder.add_node("search",            search_node)
            builder.add_node("scan",              scan_node)
            builder.add_node("select",            select_node)
            builder.add_node("fulltext_search",   fulltext_search_node)
            builder.add_node("followup_intent",   followup_intent_node)
            builder.add_node("followup_search",   followup_search_node)
            builder.add_node("extract",           extract_node)
            builder.add_node("generate",          generate_node)

            # START → router
            builder.add_edge(START, "router")

            # router → rag / followup
            builder.add_conditional_edges(
                "router",
                _route_edge,
                {
                    "rag":      "intent",
                    "followup": "followup_intent",
                },
            )

            # RAG intent 후 mode 분기:
            #   structured → search → scan → select → extract
            #   open       → fulltext_search → extract  (search/scan/select 한 노드로 압축)
            builder.add_conditional_edges(
                "intent",
                _after_intent_edge,
                {
                    "structured": "search",
                    "open":       "fulltext_search",
                },
            )

            # structured 경로: intent → search → scan → select → extract → generate
            builder.add_edge("search",  "scan")
            builder.add_edge("scan",    "select")
            builder.add_edge("select",  "extract")

            # open 경로: intent → fulltext_search → extract → generate
            builder.add_edge("fulltext_search", "extract")

            # FOLLOWUP 경로: followup_intent → followup_search
            builder.add_edge("followup_intent", "followup_search")

            # followup_search 분기:
            #   exist → extract → generate
            #   none  → intent (RAG 사이클, fallback_from_followup=True 로 무한루프 방지)
            builder.add_conditional_edges(
                "followup_search",
                _after_followup_search_edge,
                {
                    "exist": "extract",
                    "none":  "_followup_fallback_marker",
                },
            )

            # followup → rag 폴백 마커 노드 (state flag 설정 후 intent 로 진입)
            def _followup_fallback_marker(state: dict) -> dict:
                _emit({"type": "followup_fallback", "reason": "이전 파일에서 못 찾음 → 전체 검색 시작"})
                return {"fallback_from_followup": True, "route": "rag"}

            builder.add_node("_followup_fallback_marker", _followup_fallback_marker)
            builder.add_edge("_followup_fallback_marker", "intent")

            # extract → generate → END
            builder.add_edge("extract",  "generate")
            builder.add_edge("generate", END)

            checkpointer = MemorySaver()
            _rag_graph = builder.compile(checkpointer=checkpointer)
            logger.info("[aimode v3] LangGraph 그래프 빌드 완료 (router/intent/search/scan/select/extract/followup_intent/followup_search/generate)")
        except Exception as e:
            logger.warning(f"[aimode] 그래프 빌드 실패, 폴백 모드: {e}")
            _rag_graph = None
    return _rag_graph


# ══════════════════════════════════════════════════════════════════════
# 메인 RAG SSE 제너레이터
# ══════════════════════════════════════════════════════════════════════

def _run_nodes_fallback(state: dict) -> None:
    """[v3] LangGraph 미설치 시 노드 순차 호출. RAG / FOLLOWUP 2-route."""
    update = router_node(state); state.update(update)
    route = state.get("route", "rag")

    # ── FOLLOWUP ──
    if route == "followup":
        update = followup_intent_node(state); state.update(update)
        update = followup_search_node(state); state.update(update)
        if state.get("matched_sources"):
            update = extract_node(state);    state.update(update)
            generate_node(state)
            return
        # 매칭 없음 → RAG 폴백
        _emit({"type": "followup_fallback", "reason": "이전 파일에서 못 찾음 → 전체 검색 시작"})
        state["fallback_from_followup"] = True
        state["route"] = "rag"
        # 폴백 후 RAG 흐름으로 fall through

    # ── RAG ──
    update = intent_node(state);   state.update(update)

    # [v3] mode 분기: structured (기존) vs open (fulltext_search)
    if state.get("rag_mode") == "open":
        update = fulltext_search_node(state); state.update(update)
        if not state.get("candidates"):
            _emit({"type": "error", "message": "키워드와 일치하는 자료를 찾지 못했습니다."})
            return
        update = extract_node(state);  state.update(update)
        generate_node(state)
        return

    # structured 경로
    update = search_node(state);   state.update(update)
    if not state.get("candidates"):
        _emit({"type": "error", "message": "검색 결과 없음 — 다른 질문을 시도해보세요."})
        return
    update = scan_node(state);     state.update(update)
    update = select_node(state);   state.update(update)
    update = extract_node(state);  state.update(update)
    generate_node(state)


def _rag_sse(question: str, topk: int, thread_id: str,
             secure: bool = False) -> Generator[str, None, None]:
    """LangGraph 그래프를 별도 스레드에서 실행하고, 노드가 투척한 이벤트를 SSE로 전달.

    secure=True 일 때 SecurityCritic 가드:
      - token 누적 버퍼에 빠른 PII 정규식 → 적발 시 스트림 중단 + 'blocked' 송출
      - done 직전 review_final 1회 → reject면 done을 'blocked'로 대체, mask면 마스킹된 답변 송출
    """
    from queue import Queue, Empty
    from services.security_bridge import quick_pii_scan, review_final, mask_pii

    def emit(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    # Ollama 연결 확인
    model = _get_ollama_model()
    if not model:
        yield emit({"type": "error",
                    "message": "Ollama 미연결 또는 지원 Gemma 모델이 없습니다. 'ollama pull gemma3:12b', 'ollama pull gemma3:4b' 실행 후 재시도."})
        return

    yield emit({"type": "info", "model": model, "thread_id": thread_id,
                "langgraph": _LANGGRAPH_OK})

    # 이벤트 큐 생성
    q: Queue = Queue()

    initial_state = {
        "question":               question,
        "thread_id":              thread_id,
        "topk":                   topk,
        "model":                  model,
        "route":                  "",
        "prev_sources":           [],
        "fallback_from_followup": False,
        "intent_message":         "",
        "file_keywords":          [],
        "detail_keywords":        [],
        "rag_mode":               "structured",
        "candidates":             [],
        "scan_results":           [],
        "matched_sources":        [],
        "references":             [],
        "answer":                 "",
        "qa_question":            "",
        "qa_answer":              "",
        "qa_attempts":            0,
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
    # secure 모드: token 누적 버퍼 + 빠른 PII 스캔 + done 시 최종 심사
    token_buf = ""
    last_scan_len = 0
    blocked_emitted = False
    SCAN_INTERVAL = 200  # 누적 200자마다 스캔

    while True:
        try:
            ev = q.get(timeout=180)
        except Empty:
            yield emit({"type": "error", "message": "타임아웃 (180초)"})
            break
        if ev is None:
            break

        # secure 모드: 이미 차단된 후엔 토큰/done을 흘리지 않음
        if secure and blocked_emitted:
            if ev.get("type") in ("token", "done"):
                continue
            yield emit(ev)
            continue

        # secure 모드: 토큰 가드
        if secure and ev.get("type") == "token":
            token_buf += ev.get("text") or ""
            if len(token_buf) - last_scan_len >= SCAN_INTERVAL:
                last_scan_len = len(token_buf)
                hits = quick_pii_scan(token_buf)
                if hits:
                    blocked_emitted = True
                    yield emit({
                        "type": "blocked",
                        "stage": "stream",
                        "reason": f"응답에 보호 개인정보({', '.join(hits)})가 감지되어 출력을 중단했습니다.",
                        "pii_types": hits,
                    })
                    continue
            yield emit(ev)
            continue

        # secure 모드: 종료 직전 최종 심사
        if secure and ev.get("type") == "done":
            full_answer = ev.get("answer") or token_buf
            verdict = review_final(question, full_answer, session_id=thread_id)
            if verdict.get("blocked"):
                yield emit({
                    "type": "blocked",
                    "stage": "final",
                    "reason": verdict.get("reason") or "보안 정책상 응답이 차단되었습니다.",
                    "pii_types": verdict.get("pii_found_in_output", []),
                })
                blocked_emitted = True
                continue
            if verdict.get("masked") and verdict.get("pii_found_in_output"):
                masked = mask_pii(full_answer, verdict.get("pii_found_in_output"))
                ev = dict(ev)
                ev["answer"] = masked
                ev["security"] = {"masked": True, "pii_types": verdict["pii_found_in_output"],
                                  "reason": verdict.get("reason")}
            elif verdict.get("needs_regenerate"):
                # MVP: 재생성은 미지원 → 마스킹으로 fallback
                masked = mask_pii(full_answer, verdict.get("pii_found_in_output", []))
                ev = dict(ev)
                ev["answer"] = masked
                ev["security"] = {"masked": True, "pii_types": verdict.get("pii_found_in_output", []),
                                  "reason": verdict.get("reason"), "note": "regenerate→mask fallback"}

        yield emit(ev)


# ── Flask 엔드포인트 ───────────────────────────────────────────────
_THREAD_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_\-]{1,64}$")


@aimode_bp.post("/chat")
def chat():
    body      = request.get_json(silent=True) or {}
    question  = (body.get("query") or "").strip()
    topk      = max(1, min(int(body.get("topk", 5)), 10))
    thread_id = (body.get("thread_id") or "default").strip()
    secure    = bool(body.get("secure", False))
    if not _THREAD_ID_RE.match(thread_id):
        thread_id = "default"
    if not question:
        return jsonify({"error": "query 필수"}), 400

    return Response(
        _rag_sse(question, topk, thread_id, secure=secure),
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
    model     = _get_ollama_model()              # 검색/intent/router (12b 우선)
    gen_model = _get_ollama_model("generate")    # 답변 생성 (4b 우선)
    return jsonify({
        "version":          "v3",
        "ollama_model":     model,
        "ollama_gen_model": gen_model,
        "ollama_available": model is not None,
        "scan_delay_sec":   SCAN_DELAY,
        "langgraph_ok":     _LANGGRAPH_OK,
    })


# ══════════════════════════════════════════════════════════════════════
# [v3 sidebar] 채팅방 목록 / 제목 수정 API
# ══════════════════════════════════════════════════════════════════════

@aimode_bp.get("/threads")
def list_threads():
    """[v3] 사이드바용 채팅방 목록 (updated_at 내림차순).

    Query params:
      limit: int (default 50, max 200)
    Response:
      { threads: [{thread_id, title, created_at, updated_at, msg_count, first_query}] }
    """
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    threads = _list_threads(limit=limit)
    return jsonify({"threads": threads, "count": len(threads)})


@aimode_bp.patch("/threads/<thread_id>/title")
def patch_thread_title(thread_id: str):
    """[v3] 사이드바에서 채팅방 이름 변경.

    Body: { title: "새 제목" }
    """
    if not _THREAD_ID_RE.match(thread_id):
        return jsonify({"error": "invalid thread_id"}), 400
    body = request.get_json(silent=True) or {}
    new_title = (body.get("title") or "").strip()
    if not new_title:
        return jsonify({"error": "title 필수"}), 400
    ok = _update_thread_title(thread_id, new_title)
    if not ok:
        return jsonify({"error": "thread not found"}), 404
    return jsonify({"ok": True, "thread_id": thread_id, "title": new_title[:60]})


# ══════════════════════════════════════════════════════════════════════
# [v3] 대화 → PDF 정리·요약 export
# ══════════════════════════════════════════════════════════════════════

def _summarize_chat_for_pdf(messages: list[dict], model: str) -> dict:
    """대화 messages 를 LLM 으로 정리·요약.

    반환: {title, overview, key_points: [...], qa_summaries: [{q, a}, ...], conclusion}
    LLM 호출 실패 시 fallback (제목+원본 turn 그대로).
    """
    # 너무 길면 자름
    convo_lines = []
    for m in messages:
        role = "사용자" if m.get("role") == "user" else "AI"
        content = (m.get("content") or "").strip()
        if not content:
            continue
        convo_lines.append(f"[{role}] {content}")
    convo_text = "\n\n".join(convo_lines)
    if len(convo_text) > 12000:
        convo_text = convo_text[:12000] + "\n…(이하 생략)"

    prompt = (
        "다음은 사용자와 AI 의 대화 기록입니다. 이 대화를 바탕으로 "
        "정리 보고서를 작성하세요.\n\n"
        "[필수 출력 형식 — JSON 한 개만, 다른 텍스트 금지]\n"
        "{\n"
        '  "title": "대화 전체를 대표하는 한 줄 제목 (30자 이내, 한국어)",\n'
        '  "overview": "대화의 주제와 맥락을 2~3문장으로 한국어 요약",\n'
        '  "key_points": ["핵심 포인트 1", "핵심 포인트 2", "핵심 포인트 3", "..."],\n'
        '  "qa_summaries": [\n'
        '    {"q": "사용자 질문 요지 (한 줄)", "a": "AI 답변 요지 (2~4문장)"},\n'
        '    ...\n'
        "  ],\n"
        '  "conclusion": "전체 대화의 결론 또는 시사점 (2~3문장)"\n'
        "}\n\n"
        "[작성 규칙]\n"
        "- 반드시 한국어로만 작성 (외국어 단어 금지)\n"
        "- 사실은 대화 안의 내용만 사용 (없는 정보 추가 금지)\n"
        "- 출처/페이지/숫자가 있으면 보존\n"
        "- key_points 는 3~6개, qa_summaries 는 각 turn 별로 1개 생성\n\n"
        f"[대화 기록]\n{convo_text}\n\n"
        "[JSON 출력]"
    )

    raw = _ollama_oneshot(prompt, model=model, num_predict=2048, keep_alive=60)
    raw = (raw or "").strip()
    # JSON 파싱
    try:
        # ```json 펜스 제거
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
        s, e = raw.find("{"), raw.rfind("}")
        if s >= 0 and e > s:
            obj = json.loads(raw[s:e + 1])
            if isinstance(obj, dict):
                return {
                    "title": str(obj.get("title") or "대화 정리").strip()[:80],
                    "overview": str(obj.get("overview") or "").strip(),
                    "key_points": [str(x).strip() for x in (obj.get("key_points") or []) if str(x).strip()][:8],
                    "qa_summaries": [
                        {"q": str(p.get("q") or "").strip(), "a": str(p.get("a") or "").strip()}
                        for p in (obj.get("qa_summaries") or []) if isinstance(p, dict)
                    ][:20],
                    "conclusion": str(obj.get("conclusion") or "").strip(),
                }
    except Exception as e:
        logger.warning(f"[export-pdf] summary parse 실패: {e}")

    # fallback: 그냥 turn 그대로
    qa_fallback = []
    pending_q = None
    for m in messages:
        role, content = m.get("role"), (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            pending_q = content
        elif role == "assistant" and pending_q:
            qa_fallback.append({"q": pending_q[:200], "a": content[:1500]})
            pending_q = None
    return {
        "title": "대화 정리",
        "overview": "AI 요약 생성에 실패하여 원본 대화를 그대로 정리합니다.",
        "key_points": [],
        "qa_summaries": qa_fallback,
        "conclusion": "",
    }


# reportlab 한글 폰트 등록 — 모듈 전역 1회만
_PDF_KO_FONT_REGISTERED = False
_PDF_KO_FONT_NAME = "KOFont"
_PDF_KO_FONT_BOLD = "KOFontBold"


def _ensure_korean_font() -> tuple[str, str]:
    """Windows Malgun Gothic 등록. 반환=(regular, bold) 폰트 이름."""
    global _PDF_KO_FONT_REGISTERED
    if _PDF_KO_FONT_REGISTERED:
        return _PDF_KO_FONT_NAME, _PDF_KO_FONT_BOLD

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os as _os

    win_fonts = _os.path.join(_os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    candidates_regular = ["malgun.ttf", "NanumGothic.ttf", "gulim.ttc", "batang.ttc"]
    candidates_bold = ["malgunbd.ttf", "NanumGothicBold.ttf"]

    reg_path = next((p for p in (_os.path.join(win_fonts, f) for f in candidates_regular) if _os.path.exists(p)), None)
    if not reg_path:
        raise RuntimeError("한글 PDF 폰트를 찾을 수 없습니다 (malgun.ttf 등).")
    bold_path = next((p for p in (_os.path.join(win_fonts, f) for f in candidates_bold) if _os.path.exists(p)), None) or reg_path

    pdfmetrics.registerFont(TTFont(_PDF_KO_FONT_NAME, reg_path))
    pdfmetrics.registerFont(TTFont(_PDF_KO_FONT_BOLD, bold_path))
    _PDF_KO_FONT_REGISTERED = True
    return _PDF_KO_FONT_NAME, _PDF_KO_FONT_BOLD


def _build_chat_pdf(thread_meta: dict, summary: dict) -> bytes:
    """[v3.2] Editorial-magazine 스타일 PDF.

    레이아웃:
      - Cover: 작은 섹션 라벨 + 파란 짧은 바 + 큰 번호 타이틀 + 파란 서브타이틀 + 메타 그리드
      - Key Points: 다이아몬드 마커 + 번호 + 본문
      - Q&A: 굵은 진남색 Q + 들여쓰기 A, 항목 사이 얇은 라인
      - Conclusion: 진남색 풀쿼트 카드 (왼쪽에 큰 따옴표) + 흰 본문
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor, white
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    import datetime as _dt
    import html as _html

    ko, ko_bold = _ensure_korean_font()

    # ── editorial 색상 팔레트 ──
    C_DARK = HexColor("#0a2a52")        # 진한 남색 — 큰 타이틀
    C_BLUE = HexColor("#2563a8")        # 중간 파랑 — 액센트 바·서브타이틀
    C_ACCENT = HexColor("#3b82c4")      # 마커·번호
    C_LIGHT_BLUE = HexColor("#93c5fd")  # quote 마크·attribution
    C_TEXT = HexColor("#1f2937")        # 본문
    C_MUTED = HexColor("#6b7280")       # 메타·푸터
    C_LINE = HexColor("#e5e7eb")        # 얇은 구분선

    def _mk(name, **kw):
        base = dict(fontName=ko, fontSize=10.5, leading=17, textColor=C_TEXT, alignment=TA_LEFT)
        base.update(kw)
        return ParagraphStyle(name=name, **base)

    s_label = _mk("Label", fontName=ko_bold, fontSize=10.5, textColor=C_DARK)
    s_big = _mk("Big", fontName=ko_bold, fontSize=26, leading=34, textColor=C_DARK)
    s_sub = _mk("Sub", fontName=ko_bold, fontSize=13.5, leading=22, textColor=C_BLUE)
    s_body = _mk("Body", fontSize=10.5, leading=18)
    s_meta = _mk("Meta", fontSize=9.5, leading=14, textColor=C_MUTED)
    s_qa_q = _mk("QAQ", fontName=ko_bold, fontSize=12, leading=18, textColor=C_DARK)
    s_qa_a = _mk("QAA", fontSize=10.5, leading=17, leftIndent=14)
    s_kp_mark = _mk("KPMark", fontName=ko_bold, fontSize=11, textColor=C_ACCENT)
    s_quote_mark = _mk("QMark", fontName=ko_bold, fontSize=44, leading=46, textColor=C_LIGHT_BLUE, alignment=TA_CENTER)
    s_quote = _mk("Quote", fontSize=11.5, leading=20, textColor=white)
    s_quote_attr = _mk("QAttr", fontName=ko_bold, fontSize=9.5, textColor=C_LIGHT_BLUE)

    def esc(t):
        return _html.escape((t or "").strip()).replace("\n", "<br/>")

    # ── 셋업 ──
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=22 * mm, bottomMargin=20 * mm,
        title=summary.get("title") or "대화 정리",
        author="DB_insight AIMODE",
    )
    W = doc.width  # 본문 영역 폭

    # ── 헬퍼: 파란 짧은 바 ──
    def blue_bar(width_mm=18, thickness_pt=2.4, color=C_BLUE):
        t = Table([[""]], colWidths=[width_mm * mm], rowHeights=[thickness_pt])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), color),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return t

    # ── 헬퍼: 섹션 헤더 (라벨 → 바 → 번호+타이틀 → 서브타이틀) ──
    def section_header(label, number, title, subtitle=""):
        out = [
            Paragraph(esc(label) + ".", s_label),
            Spacer(1, 10),
            blue_bar(),
            Spacer(1, 24),
            Paragraph(f"{number}. {esc(title)}", s_big),
            Spacer(1, 14),
        ]
        if subtitle:
            out.append(Paragraph(esc(subtitle), s_sub))
            out.append(Spacer(1, 18))
        else:
            out.append(Spacer(1, 8))
        return out

    story = []

    # ══ Cover ══════════════════════════════════════════
    title = summary.get("title") or thread_meta.get("title") or "대화 정리"
    overview = summary.get("overview") or ""
    story.extend(section_header("AIMODE 대화 정리", "01", title, overview))

    # 큰 여백 → 하단에 메타 그리드
    story.append(Spacer(1, 130))
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    created = (thread_meta.get("created_at") or "")[:19].replace("T", " ")
    updated = (thread_meta.get("updated_at") or "")[:19].replace("T", " ")
    msg_count = int(thread_meta.get("msg_count") or 0)
    turns_count = max(0, msg_count // 2)

    meta_cells = [
        Paragraph(f"<font color='#0a2a52'><b>대화방</b></font><br/><br/>{esc(thread_meta.get('title') or '-')}", s_meta),
        Paragraph(f"<font color='#0a2a52'><b>대화 수</b></font><br/><br/>{turns_count}회", s_meta),
        Paragraph(f"<font color='#0a2a52'><b>생성</b></font><br/><br/>{esc(created or '-')}", s_meta),
        Paragraph(f"<font color='#0a2a52'><b>출력 일시</b></font><br/><br/>{esc(now)}", s_meta),
    ]
    meta_tbl = Table([meta_cells], colWidths=[W / 4.0] * 4)
    meta_tbl.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, C_LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(meta_tbl)

    # ══ Key Points ═══════════════════════════════════
    key_points = summary.get("key_points") or []
    if key_points:
        story.append(PageBreak())
        story.extend(section_header(
            "핵심 포인트", "02", "Key points",
            "이번 대화에서 도출된 주요 결론과 인사이트를 한눈에 정리합니다."
        ))
        for i, kp in enumerate(key_points, 1):
            row = Table(
                [[
                    Paragraph("<font color='#3b82c4'><b>&#9670;</b></font>", s_kp_mark),
                    Paragraph(f"<font color='#0a2a52'><b>{i:02d}</b></font> &nbsp;&nbsp;{esc(kp)}", s_body),
                ]],
                colWidths=[16, W - 16],
            )
            row.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, C_LINE),
            ]))
            story.append(row)

    # ══ Q&A ═════════════════════════════════════════
    qas = summary.get("qa_summaries") or []
    if qas:
        story.append(PageBreak())
        story.extend(section_header(
            "질문과 답변", "03", "Q&A summary",
            "사용자 질문과 AI 답변의 핵심을 항목별로 정리합니다."
        ))
        for i, qa in enumerate(qas, 1):
            q = (qa.get("q") or "").strip()
            a = (qa.get("a") or "").strip()
            if not q and not a:
                continue
            story.append(Paragraph(
                f"<font color='#3b82c4'><b>Q{i:02d}.</b></font> &nbsp;{esc(q)}",
                s_qa_q,
            ))
            story.append(Spacer(1, 6))
            story.append(Paragraph(esc(a), s_qa_a))
            story.append(Spacer(1, 16))
            # 항목 사이 얇은 라인
            line_tbl = Table([[""]], colWidths=[W], rowHeights=[0.3])
            line_tbl.setStyle(TableStyle([
                ("LINEABOVE", (0, 0), (-1, -1), 0.3, C_LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(line_tbl)
            story.append(Spacer(1, 14))

    # ══ Conclusion (pull quote) ════════════════════
    conclusion = summary.get("conclusion") or ""
    if conclusion:
        story.append(PageBreak())
        story.extend(section_header(
            "종합 결론", "04", "Conclusion",
            "전체 대화에서 얻은 종합적인 결론과 시사점입니다."
        ))
        quote_tbl = Table(
            [
                [
                    Paragraph("&ldquo;", s_quote_mark),
                    Paragraph(esc(conclusion), s_quote),
                ],
                [
                    "",
                    Paragraph("— DB_insight · AIMODE", s_quote_attr),
                ],
            ],
            colWidths=[46, W - 46],
        )
        quote_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_DARK),
            ("SPAN", (0, 0), (0, 1)),
            ("VALIGN", (0, 0), (0, 0), "TOP"),
            ("VALIGN", (1, 0), (1, 0), "TOP"),
            ("VALIGN", (1, 1), (1, 1), "BOTTOM"),
            ("LEFTPADDING", (0, 0), (-1, -1), 16),
            ("RIGHTPADDING", (0, 0), (-1, -1), 22),
            ("TOPPADDING", (0, 0), (-1, -1), 18),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ]))
        story.append(quote_tbl)

    # ── 헤더/푸터: 매 페이지 작은 라벨 + 페이지 번호 ──
    def _decorate(canvas, _doc):
        canvas.saveState()
        # 푸터 좌측 라벨, 우측 페이지 번호
        canvas.setFont(ko, 8.5)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(22 * mm, 12 * mm, "DB_insight · AIMODE 대화 자동 정리")
        canvas.drawRightString(_doc.pagesize[0] - 22 * mm, 12 * mm, f"{_doc.page:02d}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()


@aimode_bp.post("/export-pdf")
def export_pdf():
    """[v3] 대화 → AI 요약 → PDF 다운로드.

    Body: { thread_id: "..." }
    응답: application/pdf 바이너리.
    """
    body = request.get_json(silent=True) or {}
    thread_id = (body.get("thread_id") or "").strip()
    if not thread_id or not _THREAD_ID_RE.match(thread_id):
        return jsonify({"error": "thread_id 필수"}), 400

    # 메시지 로드
    messages = _load_chat_history_from_db(thread_id)
    if not messages:
        return jsonify({"error": "대화 기록이 없습니다."}), 404

    # 스레드 메타
    from db.init_db import get_connection
    thread_meta = {"thread_id": thread_id, "title": "대화"}
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT thread_id, title, created_at, updated_at, msg_count "
                "FROM aimode_threads WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if row:
                thread_meta = dict(row)
    except Exception as e:
        logger.debug(f"[export-pdf] thread meta {e}")

    # LLM 요약 — 가능하면 답변 모델, 없으면 도구 모델 fallback
    model = _get_ollama_model("answer") or _get_ollama_model(None) or _get_ollama_model("tool")
    if not model:
        return jsonify({"error": "Ollama 모델을 찾을 수 없습니다."}), 503

    try:
        summary = _summarize_chat_for_pdf(messages, model=model)
    except Exception as e:
        logger.exception("[export-pdf] summary 실패")
        return jsonify({"error": f"요약 실패: {e}"}), 500

    # PDF 생성
    try:
        pdf_bytes = _build_chat_pdf(thread_meta, summary)
    except ModuleNotFoundError:
        return jsonify({
            "error": "reportlab 미설치",
            "hint": "백엔드 가상환경에서 'pip install reportlab' 을 실행해주세요.",
        }), 500
    except Exception as e:
        logger.exception("[export-pdf] PDF 생성 실패")
        return jsonify({"error": f"PDF 생성 실패: {e}"}), 500

    # 파일명 — 제목 + 날짜
    import datetime as _dt2
    import re as _re_fname
    from urllib.parse import quote as _url_quote
    safe_title = _re_fname.sub(r"[\\/:*?\"<>|]+", "_", (summary.get("title") or thread_meta.get("title") or "chat"))[:40]
    fname = f"{safe_title}_{_dt2.datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    # ASCII 안전 fallback
    try:
        fname.encode("latin-1")
        cd = f'attachment; filename="{fname}"'
    except UnicodeEncodeError:
        cd = f"attachment; filename*=UTF-8''{_url_quote(fname)}"

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": cd,
            "Content-Length": str(len(pdf_bytes)),
            "X-Suggested-Filename": _url_quote(fname),
        },
    )


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

        # [E13 fix v2] audio/bgm z-score CDF 인플레이션 방지.
        # prebst_cosine = 부스트 전 실제 cosine (≤1.0) 으로 상한 설정.
        # raw_dense = dense_agg(부스트 후) 이므로 인플레이션 보정에 부적합.
        # video 는 도메인 선택 정확도를 위해 보정하지 않음.
        for _av_lst in (audio, bgm):
            for _av_r in _av_lst:
                _raw_dv = float(_av_r.get("prebst_cosine") or _av_r.get("raw_dense") or _av_r.get("dense") or 0)
                if _raw_dv > 0:
                    for _f in ("confidence", "similarity"):
                        if _f in _av_r and _av_r[_f] is not None:
                            _av_r[_f] = round(min(float(_av_r[_f]), _raw_dv), 4)

        for lst in (img_only, doc_only, video, audio, bgm):
            lst.sort(key=lambda r: r.get("confidence", 0), reverse=True)

        # [aimode DEBUG] video 상위 결과 로깅
        try:
            import datetime as _dtt_ai
            _dbg_ai = r"C:\yssong\KDT-FT-team3-Chainers\DB_insight\av_debug.log"
            with open(_dbg_ai, "a", encoding="utf-8") as _lf_ai:
                _lf_ai.write(f"\n[{_dtt_ai.datetime.now()}] [AIMODE] _do_search q={query[:40]!r} topk={topk}\n")
                _lf_ai.write(f"  video 결과 {len(video)}건:\n")
                for _vi, _vr in enumerate(video[:10]):
                    _lf_ai.write(f"    [{_vi}] conf={_vr.get('confidence')} dense={_vr.get('dense')} name={_vr.get('file_name','?')[:60]}\n")
        except Exception:
            pass

        # [aimode v2] video quota 확대: topk//3 최소 2 → video 결과 더 많이 guaranteed
        quota = max(2, topk // 3)
        guaranteed: list[dict] = []
        for lst in (doc_only, img_only, video, audio, bgm):
            guaranteed.extend(lst[:quota])
        # [aimode v2] video/audio 가중치를 1.0으로 동등하게 → extras 정렬에서 불이익 제거
        _DW = {"image": 1.0, "doc": 1.0, "video": 1.0, "audio": 0.75, "bgm": 0.75}
        extras: list[dict] = []
        for lst in (img_only, doc_only, video, audio, bgm):
            extras.extend(lst[quota:])
        extras.sort(
            key=lambda r: r.get("confidence", 0) * _DW.get(r.get("file_type", ""), 1.0),
            reverse=True,
        )
        results = (guaranteed + extras)[:topk * 2]

        # [aimode v2] rerank 전 video top-1 보존 (rerank 후 복원용)
        _top_video = video[0] if video else None
        _top_video_id = _top_video.get("trichef_id") if _top_video else None

        # [aimode DEBUG] rerank 전 상위 결과 로깅
        try:
            import datetime as _dtt_rk
            _dbg_rk = r"C:\yssong\KDT-FT-team3-Chainers\DB_insight\av_debug.log"
            with open(_dbg_rk, "a", encoding="utf-8") as _lf_rk:
                _lf_rk.write(f"  [BEFORE rerank] results {len(results)}건:\n")
                for _ri, _rr in enumerate(results[:topk]):
                    _lf_rk.write(f"    [{_ri}] conf={_rr.get('confidence')} type={_rr.get('file_type')} name={_rr.get('file_name','?')[:50]}\n")
        except Exception:
            pass

        results = maybe_rerank(query, results)

        # [aimode DEBUG] rerank 후 상위 결과 로깅
        try:
            import datetime as _dtt_rk2
            _dbg_rk2 = r"C:\yssong\KDT-FT-team3-Chainers\DB_insight\av_debug.log"
            with open(_dbg_rk2, "a", encoding="utf-8") as _lf_rk2:
                _lf_rk2.write(f"  [AFTER rerank] results {len(results)}건:\n")
                for _ri2, _rr2 in enumerate(results[:topk]):
                    _lf_rk2.write(f"    [{_ri2}] conf={_rr2.get('confidence')} type={_rr2.get('file_type')} name={_rr2.get('file_name','?')[:50]}\n")
        except Exception:
            pass

        # [aimode v2] rerank 후 video top-1이 topk 밖으로 밀린 경우 강제 복원
        if _top_video_id is not None:
            _vid_in_topk = any(
                r.get("trichef_id") == _top_video_id
                for r in results[:topk]
            )
            if not _vid_in_topk:
                # 이미 results 어딘가에 있으면 제거 후 맨앞에 삽입
                results = [_top_video] + [
                    r for r in results if r.get("trichef_id") != _top_video_id
                ]
                logger.debug(f"[aimode v2] video top-1 복원: {_top_video.get('file_name')} id={_top_video_id}")

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
                        ".",   # 마침표 — narrative 와 다음 불릿 분리 위해 추가
                        "!", "?", "。",
                    ])
                    # 진짜 불릿/번호 매김만 매치 — "2025/26", "2.4%", "3,035.5" 같은
                    # 문장 일부 숫자는 불릿으로 오인하면 안 됨. `*` 도 추가.
                    _BULLET = _re.compile(r"^(?:[\*·•\-①②③④⑤]|\d+[.)]\s)")
                    lines = text.split("\n")
                    result = []
                    prev_is_bullet = False
                    for line in lines:
                        is_bullet = bool(_BULLET.match(line.strip()))
                        starts_paren = line.strip().startswith("[") or line.strip().startswith("(")
                        if (result
                                and line
                                and result[-1]
                                and not prev_is_bullet                # 불릿 다음엔 새 문장 시작
                                and result[-1][-1] not in _SENT_END
                                and not is_bullet
                                and not starts_paren
                        ):
                            result[-1] += line  # 이전 줄에 이어붙임
                        else:
                            result.append(line)
                            prev_is_bullet = is_bullet
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
        # [v18.3] 입력 길이 12000→6000자로 재축소:
        #   12000자 ≈ 6,000~9,000 tok → prefill 30~60초 + 생성 25초 = 90초 초과 빈발.
        #   6000자 (≈ 3,000~4,500 tok) 로도 핵심 내용 충분히 포함되고 전체 30초 이내 가능.
        text, _stem = _load_full_doc_text(trichef_id, max_chars=6000)
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
- 간결하게 작성 — 전체 합산 약 800~1,200자 (6개 섹션 각 100~200자 목표).
- 한국어, Markdown (제목 `##`/`###`, 강조 `**`, 인용 `>` 사용)."""


def _release_search_embedders() -> int:
    """검색 임베더(SigLIP2·BGE-M3·DINOv2·Reranker)를 VRAM에서 해제.

    AI 요약처럼 LLM이 대용량 VRAM을 필요로 할 때 검색 모델을 내려 공간을 확보.
    각 임베더는 다음 검색 요청 시 _load() 를 통해 자동 재로드됨.
    반환값: 해제 후 여유 VRAM (MB). GPU 없으면 0.
    """
    import gc
    released: list[str] = []

    # 1) SigLIP2 (Re 축, ~1.0 GB)
    try:
        import embedders.trichef.siglip2_re as _s
        with _s._lock:
            if _s._model is not None:
                try: _s._model.cpu()
                except Exception: pass
                _s._model = None
                _s._proc  = None
                released.append("siglip2")
    except Exception as e:
        logger.warning(f"[vram_swap] siglip2 해제 실패: {e}")

    # 2) BGE-M3 (Im 축, ~2.0 GB)
    try:
        import embedders.trichef.bgem3_caption_im as _b
        with _b._lock:
            if _b._model is not None:
                try:
                    inner = getattr(_b._model, 'model', None)
                    if inner is not None and hasattr(inner, 'cpu'):
                        inner.cpu()
                except Exception: pass
                _b._model = None
                released.append("bgem3")
    except Exception as e:
        logger.warning(f"[vram_swap] bgem3 해제 실패: {e}")

    # 3) DINOv2 (Z 축, ~1.3 GB)
    try:
        import embedders.trichef.dinov2_z as _d
        with _d._lock:
            if _d._model is not None:
                try: _d._model.cpu()
                except Exception: pass
                _d._model = None
                _d._proc  = None
                released.append("dinov2")
    except Exception as e:
        logger.warning(f"[vram_swap] dinov2 해제 실패: {e}")

    # 4) Reranker — shared/reranker.py 싱글턴 탐색
    try:
        import sys
        for mod_name in list(sys.modules.keys()):
            if 'reranker' in mod_name.lower():
                mod = sys.modules[mod_name]
                for attr in ('_model', '_reranker', 'model', '_cross_encoder'):
                    m = getattr(mod, attr, None)
                    if m is not None and hasattr(m, 'cpu'):
                        try: m.cpu()
                        except Exception: pass
                        setattr(mod, attr, None)
                        released.append(f"reranker.{attr}")
    except Exception as e:
        logger.warning(f"[vram_swap] reranker 해제 실패: {e}")

    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            free_mb = int(torch.cuda.mem_get_info()[0] / 1024 / 1024)
            logger.info(f"[vram_swap] 해제 완료: {released}, 여유 VRAM: {free_mb} MB")
            return free_mb
    except Exception:
        pass
    return 0


def _summarize_sse(file_type: str, trichef_id: str, file_path: str,
                   segments: list | None, file_name: str | None,
                   secure: bool = False,
                   ) -> Generator[str, None, None]:
    """파일 요약 SSE 제너레이터.

    secure=True 일 때 SecurityCritic 가드:
      - token 누적 버퍼에 빠른 PII 정규식 → 적발 시 스트림 중단 + 'blocked' 송출
      - done 직전 review_final 1회 → reject면 done을 'blocked'로 대체, mask면 마스킹된 요약 송출
    """
    from services.security_bridge import quick_pii_scan, review_final, mask_pii

    def emit(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    # 요약: VRAM 절약 최우선 — qwen2.5:3b(1.9GB)가 임베더와 공존 가능하면 GPU 추론
    model = _get_ollama_model("summarize")
    if not model:
        yield emit({"type": "error", "message": "Ollama 미연결 또는 지원 Gemma 모델이 없습니다. gemma3:12b 또는 gemma:4b를 설치해 주세요."})
        return

    fname = file_name or (file_path or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "?"
    yield emit({"type": "info", "model": model, "file_type": file_type, "file_name": fname})
    yield emit({"type": "status", "message": "본문 추출 중..."})

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

    # 본문 길이 기반 동적 num_predict
    # qwen2.5:3b GPU(RTX 4070 Laptop) 기준 ~40 tok/s → num_predict 600 ≈ 15초.
    # UX 목표: 모델로드(~10s) + prefill(~3s) + 생성(~15s) = 30초 이내.
    clen = len(content)
    if   clen < 2000:   dynamic_np = 400
    elif clen < 4000:   dynamic_np = 500
    else:               dynamic_np = 600

    # [VRAM 스왑] LLM 호출 전 여유 VRAM 확인.
    # VRAM 스왑 정책 (모델별 동적 임계값):
    # 모델이 GPU에 올라가야 빠른 추론 가능 (GPU ~40 tok/s vs CPU ~3 tok/s).
    # 여유 VRAM < 모델 필요량+300MB 이면 임베더 해제 후 force-unload → GPU 재로드.
    # qwen2.5:3b(1.9GB): 여유 3.6GB → 스왑 불필요 ✅
    # gemma3:4b-it-qat(4.0GB): 여유 3.6GB → 스왑 필요 (임베더 해제 후 GPU 가능)
    _vram_swapped = False
    _model_need_mb = next(
        (v for k, v in _MODEL_VRAM_MB.items() if k in model), 4200
    )
    try:
        import torch as _torch
        if _torch.cuda.is_available():
            _free_mb = int(_torch.cuda.mem_get_info()[0] / 1024 / 1024)
            _threshold = _model_need_mb + 300   # 300 MB 여유분
            if _free_mb < _threshold:
                logger.info(
                    f"[vram_swap] {model}: 여유 {_free_mb} MB < 필요 {_threshold} MB "
                    f"→ 임베더 해제 후 GPU 재로드"
                )
                yield emit({"type": "vram_swap", "message": "GPU 메모리 확보 중...", "free_mb": _free_mb})
                _after_mb = _release_search_embedders()
                _vram_swapped = True
                logger.info(f"[vram_swap] 해제 후 여유 VRAM: {_after_mb} MB")
                # Ollama는 CPU RAM에 로드된 모델을 VRAM이 해제돼도 자동으로 GPU로 이동하지 않음.
                # force-unload → CPU RAM 제거 → 다음 요청 시 디스크→GPU 단 1회 로드.
                try:
                    _req.post(
                        f"{OLLAMA_URL}/api/chat",
                        json={"model": model,
                              "messages": [{"role": "user", "content": "hi"}],
                              "keep_alive": 0, "stream": False},
                        timeout=20,
                    )
                    logger.info("[vram_swap] force-unload 완료 → 다음 요청 시 디스크→GPU 로드")
                except Exception as _ue:
                    logger.warning(f"[vram_swap] force-unload 실패 (무시): {_ue}")
            else:
                logger.info(
                    f"[vram_swap] {model}: 여유 {_free_mb} MB ≥ 필요 {_threshold} MB "
                    f"→ 스왑 불필요, GPU 직접 로드"
                )
    except Exception as _ve:
        logger.warning(f"[vram_swap] VRAM 확인 실패: {_ve}")

    full = ""
    t0 = time.time()
    stream_error: str | None = None
    blocked = False
    last_scan_len = 0
    SCAN_INTERVAL = 200
    try:
        # keep_alive=180 — 모델을 3분간 메모리 유지 (콜드스타트 방지).
        # keep_alive=0이면 매 요청마다 모델 재로드(30~60s)되어 150s 타임아웃 초과.
        # [v3.3] chunk_size=0 — 토큰 받는 즉시 yield (한 글자씩 타이핑 효과).
        # 기존 chunk_size=80 (default) 은 80자 모아 한 번에 → 한 줄씩 뚝뚝 나오는 UX.
        for tok in _ollama_stream(messages, model, num_predict=dynamic_np, temperature=0.25,
                                   chunk_size=0, keep_alive=180):
            full += tok
            if secure:
                if len(full) - last_scan_len >= SCAN_INTERVAL:
                    last_scan_len = len(full)
                    hits = quick_pii_scan(full)
                    if hits:
                        blocked = True
                        yield emit({
                            "type": "blocked",
                            "stage": "stream",
                            "reason": f"요약에 보호 개인정보({', '.join(hits)})가 감지되어 출력을 중단했습니다.",
                            "pii_types": hits,
                        })
                        break
            yield emit({"type": "token", "text": tok})
    except Exception as e:
        stream_error = str(e)
        logger.warning(f"[summarize] stream 중단: {e}")

    try:
        logger.info(
            f"[summarize] file={fname[:40]!r} type={file_type} "
            f"content_len={len(content)} summary_len={len(full)} "
            f"dt={time.time()-t0:.2f}s err={stream_error!r} secure={secure} blocked={blocked}"
        )
    except Exception:
        pass

    if blocked:
        # 스트림 단계에서 이미 차단 — done 송출 안 함
        return

    final_summary = full
    security_meta = None
    if secure and full:
        verdict = review_final(f"파일 요약 요청: {fname}", full,
                               session_id=f"summarize:{trichef_id or fname}")
        if verdict.get("blocked"):
            yield emit({
                "type": "blocked",
                "stage": "final",
                "reason": verdict.get("reason") or "보안 정책상 요약이 차단되었습니다.",
                "pii_types": verdict.get("pii_found_in_output", []),
            })
            return
        if verdict.get("masked") and verdict.get("pii_found_in_output"):
            final_summary = mask_pii(full, verdict.get("pii_found_in_output"))
            security_meta = {"masked": True, "pii_types": verdict["pii_found_in_output"],
                             "reason": verdict.get("reason")}
        elif verdict.get("needs_regenerate"):
            final_summary = mask_pii(full, verdict.get("pii_found_in_output", []))
            security_meta = {"masked": True, "pii_types": verdict.get("pii_found_in_output", []),
                             "reason": verdict.get("reason"), "note": "regenerate→mask fallback"}

    done_ev = {
        "type":    "done",
        "summary": final_summary,
        "model":   model,
        "length":  len(content),
        "kind":    kind,
        "error":   stream_error,
    }
    if security_meta is not None:
        done_ev["security"] = security_meta
    yield emit(done_ev)


@aimode_bp.post("/summarize")
def summarize():
    """POST /api/aimode/summarize — 파일 요약 SSE 스트리밍."""
    body       = request.get_json(silent=True) or {}
    file_type  = (body.get("file_type") or "").strip()
    trichef_id = (body.get("trichef_id") or body.get("rid") or "").strip()
    file_path  = (body.get("file_path") or "").strip()
    file_name  = (body.get("file_name") or "").strip()
    segments   = body.get("segments") or []
    secure     = bool(body.get("secure", False))

    if not file_type:
        return jsonify({"error": "file_type 필수"}), 400

    return Response(
        _summarize_sse(file_type, trichef_id, file_path, segments, file_name, secure=secure),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
