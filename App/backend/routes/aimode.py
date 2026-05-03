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


def _ollama_stream(messages: list[dict], model: str,
                   num_predict: int = 1024,
                   temperature: float = 0.3) -> Generator[str, None, None]:
    try:
        with _req.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model":   model,
                "messages": messages,
                "stream":  True,
                "options": {"temperature": temperature, "num_predict": num_predict},
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


# ── Step 1: 검색어 추출 ────────────────────────────────────────────
# 검색어 추출 시 제거할 의미 없는 동사·조사·일반 표현
_STOPWORDS = frozenset((
    "문서에서", "문서", "이미지에서", "이미지", "영상에서", "영상", "음원에서", "음원",
    "파일에서", "파일", "내용을", "내용", "정보를", "정보",
    "찾아서", "찾아", "찾기", "찾을", "찾는", "찾아줘",
    "알려줘", "알려", "보여줘", "보여", "정리해줘", "정리",
    "해줘", "주세요", "주십시오", "있는", "있을", "있나", "있어",
    "에서", "에게", "에는", "에는", "한테", "에서는",
    "어디", "무엇", "어떤", "어떻게", "왜", "언제",
))


def _domain_hint(question: str) -> str | None:
    """사용자 질문에서 도메인 의도 힌트 추출.

    예: 'PDF 에서 …' → doc, '이미지에서…' → image, '영상에서…' → movie
    """
    q = question.lower()
    if any(k in question for k in ("PDF", "pdf", "문서", "보고서", "리포트", "한글파일", "doc")):
        return "doc"
    if any(k in question for k in ("이미지", "사진", "그림", "image", "photo")):
        return "image"
    if any(k in question for k in ("영상", "동영상", "비디오", "video", "movie", "mp4")):
        return "movie"
    if any(k in question for k in ("음원", "음악", "BGM", "bgm", "노래", "음성", "오디오")):
        return "music"
    return None


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
        meaningful = [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS]
        extracted = " ".join(meaningful[:5])
    return extracted or user_question


# ── Step 2: 검색 ────────────────────────────────────────────────────
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
    """LLM 에 전달할 snippet 채우기 — doc_page 는 PDF page text 직접 로드.

    LRU 캐시 적용 — 같은 rid 반복 호출 시 디스크 I/O / Qwen 호출 중복 제거.
    """
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
    # 미지원 타입 — 기존 로직 fallback
    rid = r.get("trichef_id") or ""
    try:
        from config import PATHS
        from pathlib import Path
        import re

        if file_type == "doc" and rid:
            # page_images/<stem>/p####.jpg → page_text/<stem>/p####.txt
            m = re.match(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$", rid)
            if m:
                stem, page_num = m.group(1), int(m.group(2))
                pt = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text" / stem / f"p{page_num:04d}.txt"
                if pt.is_file():
                    txt = pt.read_text(encoding="utf-8").strip()
                    if txt:
                        # 검색어 매칭 줄 우선 + 인접 컨텍스트 (최대 800자)
                        r["snippet"] = txt[:800]
                        return
        elif file_type == "image":
            # Qwen 5-stage caption (title + tagline + synopsis 결합)
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
    """일반 `/api/search` 와 동일한 파이프라인을 인라인 재현 — AIMODE 결과 일관성 보장.

    재현 항목 (search.py:14-138 기반):
      ① Query expansion ✓
      ② 도메인별 분리 호출 (image / doc_page / movie / music)
      ③ AV legacy fallback (movie/music)
      ④ Domain quota — 각 도메인 top_k/4 보장 + 가중 score 정렬
      ⑤ Cross-encoder rerank (env-gated)
      ⑥ Score adjust (confidence + dense)
      ⑦ Location 부착 (페이지/타임코드)
      ⑧ AIMODE 전용 — snippet 보강 (LLM 본문 컨텍스트)
    """
    try:
        from routes.search import (
            _search_trichef, _search_trichef_av,
            _search_legacy_video, _search_legacy_audio,
        )
        from services.query_expand import expand_bilingual
        from services.score_adjust import adjust_confidence, _generous_curve
        from services.rerank_adapter import maybe_rerank
        from services.location_resolver import extract_location
        from concurrent.futures import ThreadPoolExecutor

        eq = expand_bilingual(query)

        # ② 도메인별 분리 검색 — 4개 도메인 병렬
        with ThreadPoolExecutor(max_workers=4) as ex:
            f_img = ex.submit(_search_trichef,    eq, ["image"],    topk)
            f_doc = ex.submit(_search_trichef,    eq, ["doc_page"], topk)
            f_mov = ex.submit(_search_trichef_av, eq, ["movie"],    topk)
            f_mus = ex.submit(_search_trichef_av, eq, ["music"],    topk)
            img_only = f_img.result() or []
            doc_only = f_doc.result() or []
            video    = f_mov.result() or []
            audio    = f_mus.result() or []

        # ③ AV legacy fallback
        if not video:
            try: video = _search_legacy_video(eq, topk) or []
            except Exception: pass
        if not audio:
            try: audio = _search_legacy_audio(eq, topk) or []
            except Exception: pass

        # ④ Domain quota — 각 도메인 내부 confidence 정렬
        for lst in (img_only, doc_only, video, audio):
            lst.sort(key=lambda r: r.get("confidence", 0), reverse=True)
        quota = max(1, topk // 4)
        guaranteed: list[dict] = []
        for lst in (doc_only, img_only, video, audio):
            guaranteed.extend(lst[:quota])
        _DW = {"image": 1.0, "doc": 1.0, "video": 0.75, "audio": 0.75}
        extras: list[dict] = []
        for lst in (img_only, doc_only, video, audio):
            extras.extend(lst[quota:])
        extras.sort(
            key=lambda r: r.get("confidence", 0) * _DW.get(r.get("file_type", ""), 1.0),
            reverse=True,
        )
        results = (guaranteed + extras)[:topk * 2]

        # ⑤ Cross-encoder rerank (env-gated; 비활성/실패 시 원본 유지)
        results = maybe_rerank(query, results)

        # ⑥ Score adjust + dense generous curve
        for r in results:
            for f in ("confidence", "similarity"):
                if f in r and r[f] is not None:
                    r[f] = round(adjust_confidence(r[f], query), 4)
            if "dense" in r and r["dense"] is not None:
                r["dense"] = round(_generous_curve(r["dense"]), 4)

        # ⑦ Location 부착
        for r in results:
            try:
                loc = extract_location(r, query=query)
                if loc is not None:
                    r["location"] = loc
            except Exception:
                pass

        # ⑧ AIMODE 전용 — LLM 본문 컨텍스트용 snippet 보강 (병렬 디스크 I/O)
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(_enrich_snippet, r, query) for r in results]
            for f in futs:
                try: f.result(timeout=5)
                except Exception: pass

        return results[:topk]
    except Exception:
        logger.exception("[aimode] _do_search 실패")
        return []


def _pick_best_idx(sources: list[dict], query: str) -> int:
    """도메인 의도가 있으면 해당 도메인 1위, 아니면 confidence 1위.

    예: '경주 PDF 에서 조사개요' → file_type=='doc' 1위 카드 우선
    """
    if not sources:
        return 0
    hint = _domain_hint(query)
    if hint:
        ft_map = {"doc": "doc", "image": "image", "movie": "video", "music": "audio"}
        target = ft_map.get(hint, hint)
        for i, s in enumerate(sources):
            if s.get("file_type") == target:
                return i
    return 0


# ── 시스템 프롬프트 ─────────────────────────────────────────────────
def _doc_neighborhood_text(rid: str, max_chars: int = 3600,
                           query: str | None = None, window: int = 2) -> str:
    """doc_page rid 의 인접 페이지(±window) 텍스트 결합 — "조사개요" 같은 멀티페이지 정보 보강.

    개선:
      - 기본 윈도우 ±2 (5쪽), max_chars 3600 으로 확대
      - 잘림 감지 시 "[…본문 일부 생략 — 전체 N자]" 마커 부착
      - query 키워드가 매칭되는 페이지 위주로 우선 적재 (현재는 단순 ±window 적재)
    """
    try:
        from config import PATHS
        from pathlib import Path
        import re
        m = re.match(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$", rid)
        if not m:
            return ""
        stem, p = m.group(1), int(m.group(2))
        page_text_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text" / stem
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
        # 매칭 페이지 우선 — 중심 페이지를 먼저 (LLM 이 잘려도 핵심 보존)
        chunks.sort(key=lambda x: abs(x[0] - (p + 1)))
        rendered_parts = []
        running = 0
        truncated = False
        for page_num, text in chunks:
            piece = f"[p.{page_num}]\n{text}"
            if running + len(piece) > max_chars:
                # 남은 공간만큼만 적재 후 truncated 표시
                remain = max(0, max_chars - running - 80)
                if remain > 200:
                    rendered_parts.append(piece[:remain] + "\n... [본문 일부 생략 — 전체 길이 초과]")
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


def _source_body_text(s: dict, query: str, max_chars: int) -> str:
    """source 1건의 LLM 컨텍스트용 본문 추출.

    doc      : ±2쪽 인접 페이지 결합 (max_chars 까지)
    image    : 이미 _enrich_snippet 에서 채운 Qwen 캡션
    video/audio: AV segment STT 텍스트 (이미 r['snippet'] 에 있음)
    """
    rid = s.get("trichef_id") or ""
    if s.get("file_type") == "doc" and rid:
        t = _doc_neighborhood_text(rid, max_chars=max_chars, query=query, window=2)
        if t:
            return t
    txt = (s.get("snippet") or "").strip()
    return txt[:max_chars] + ("…[잘림]" if len(txt) > max_chars else "")


def _build_system_prompt(selected: dict, all_sources: list[dict],
                         query: str = "", top_n: int = 3) -> str:
    """다중 source 컨텍스트 시스템 프롬프트.

    개선:
      - 상위 N건 (기본 3) 의 본문을 모두 포함 → LLM 이 교차 인용/비교 가능
      - 각 source 마다 본문 길이 제한 (선택=1500자, 보조=600자)
      - 잘림 표시 일관 적용
    """
    domain_label = {"image": "이미지", "doc": "문서", "video": "동영상",
                    "audio": "음성", "bgm": "BGM"}
    fname = selected.get("file_name") or "?"
    domain = domain_label.get(selected.get("file_type", ""), "파일")
    fpath = selected.get("file_path") or ""

    # 후보 목록 라인
    list_lines = []
    sel_idx_label = "?"
    for i, s in enumerate(all_sources, 1):
        is_sel = "★" if s is selected else " "
        if s is selected:
            sel_idx_label = str(i)
        list_lines.append(
            f"  {is_sel} [{i}] {s.get('file_name', '?')} "
            f"({domain_label.get(s.get('file_type', ''), s.get('file_type', ''))}, "
            f"{(s.get('confidence') or 0)*100:.0f}%)"
        )

    # 본문 — 선택 카드는 길게, 나머지는 짧게
    body_blocks = []
    sel_text = _source_body_text(selected, query, max_chars=3000)
    body_blocks.append(
        f"★ 선택 파일 — [{sel_idx_label}] {fname}\n경로: {fpath}\n"
        f"---\n{sel_text or '(본문 텍스트가 추출되지 않았습니다)'}\n---"
    )
    # 나머지 보조 source (선택 제외, 최대 top_n-1 건)
    aux_count = 0
    for i, s in enumerate(all_sources, 1):
        if s is selected or aux_count >= max(0, top_n - 1):
            continue
        aux_text = _source_body_text(s, query, max_chars=600)
        if not aux_text:
            continue
        body_blocks.append(
            f"  보조 [{i}] {s.get('file_name', '?')}\n"
            f"  ---\n{aux_text}\n  ---"
        )
        aux_count += 1

    return f"""당신은 로컬 파일 데이터베이스 전문 AI 어시스턴트입니다.
사용자의 질문에 가장 관련된 [{domain}] 파일을 찾았으며, 아래 본문 내용을 기반으로 한국어로 답변하세요.

검색된 후보 파일 (★ 선택됨):
{chr(10).join(list_lines)}

{chr(10).join(body_blocks)}

답변 원칙:
- 위 본문 내용을 직접 인용하면서 사용자 질문에 답변하세요.
- 정보가 본문에 있으면 명확히 추출해 정리하고, 보조 파일에서도 보강 인용 가능합니다.
- 출처는 "[{sel_idx_label}] {fname}" 형식으로 인용하세요.
- 본문이 비어있거나 질문과 무관하면 솔직히 말하세요.
- "본문 일부 생략" 마커가 보이면 핵심만 요약하고 전체를 추측하지 마세요.
- 한국어로 간결·명확하게 작성하세요."""


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

    # ── Step 3: 가장 관련 카드 자동 선택 (도메인 힌트 인지) ─────
    selected_idx = _pick_best_idx(sources, query)
    selected = sources[selected_idx]
    yield emit({
        "type": "step", "step": 3,
        "label": f"🎯 가장 관련된 결과 선택 (#{selected_idx+1})",
        "selected_idx": selected_idx,
        "selected_name": selected.get("file_name", ""),
        "selected_file_type": selected.get("file_type", ""),
    })
    time.sleep(STEP_DELAY)

    # ── Step 4: 답변 생성 — LangGraph 이전 대화 + 검색 sources 함께 ──
    yield emit({"type": "step", "step": 4, "label": "✨ 답변 정리 중...",
                "selected_idx": selected_idx})

    # 이전 대화 이력 로드 (LangGraph thread_id 기반)
    prior_history = _load_history(thread_id)

    sys_prompt = _build_system_prompt(selected, sources, query=query, top_n=3)
    messages = [{"role": "system", "content": sys_prompt}]
    # 최근 5턴 (user+assistant = 10 메시지)
    if prior_history:
        messages.extend(prior_history[-10:])
    messages.append({"role": "user", "content": query})

    full_answer = ""
    stream_error: str | None = None
    t_stream = time.time()
    try:
        for tok in _ollama_stream(messages, model):
            full_answer += tok
            yield emit({"type": "token", "text": tok})
    except Exception as e:
        stream_error = str(e)
        logger.warning(f"[aimode] stream 중단: {e}")

    # ── State 저장 — 빈/오류 응답은 history 오염 방지 위해 skip ──
    if full_answer and len(full_answer.strip()) >= 10 and not stream_error:
        _save_state(thread_id, query, extracted, sources, selected_idx, full_answer)

    # ── Telemetry — extracted/top1/latency/sources 카운트 ──
    try:
        top1 = (sources[0].get("confidence") or 0) if sources else 0
        logger.info(
            f"[aimode] q={query[:40]!r} extracted={extracted!r} "
            f"sources={len(sources)} sel={selected_idx} top1={top1:.2f} "
            f"answer_len={len(full_answer)} stream_dt={time.time()-t_stream:.2f}s "
            f"err={stream_error!r}"
        )
    except Exception:
        pass

    yield emit({
        "type":         "done",
        "answer":       full_answer,
        "selected_idx": selected_idx,
        "model":        model,
        "extracted":    extracted,
        "thread_id":    thread_id,
        "history_used": len(prior_history),
        "langgraph":    _LANGGRAPH_OK,
        "error":        stream_error,
    })


# ── Flask 엔드포인트 ───────────────────────────────────────────────
_THREAD_ID_RE = __import__("re").compile(r"^[A-Za-z0-9_\-]{1,64}$")


@aimode_bp.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    topk = max(1, min(int(body.get("topk", 5)), 10))
    thread_id = (body.get("thread_id") or "default").strip()
    # thread_id 검증 — 영숫자/_/- 만 허용, 최대 64자 (DoS 방지)
    if not _THREAD_ID_RE.match(thread_id):
        thread_id = "default"
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


# ════════════════════════════════════════════════════════════════════
# 파일 요약 — 상세 페이지에서 [요약] 버튼 클릭 시 호출
# ════════════════════════════════════════════════════════════════════

def _load_full_doc_text(rid: str, max_chars: int = 12000) -> tuple[str, str]:
    """doc_page rid 의 PDF 전체 페이지 텍스트 로드 — 요약용.

    Returns: (combined_text, stem)
    page_images/<stem>/p####.jpg → page_text/<stem>/p*.txt 모두 결합.
    """
    try:
        from config import PATHS
        from pathlib import Path
        import re
        m = re.match(r"^page_images/(.+)/p(\d+)\.(?:jpg|png)$", rid)
        if not m:
            return "", ""
        stem = m.group(1)
        page_text_dir = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / "page_text" / stem
        if not page_text_dir.is_dir():
            return "", stem
        pages = sorted(page_text_dir.glob("p*.txt"),
                       key=lambda p: int(p.stem[1:]))
        chunks: list[str] = []
        running = 0
        truncated = False
        for tp in pages:
            try:
                t = tp.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if not t:
                continue
            page_num = int(tp.stem[1:]) + 1
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
            out += f"\n\n[전체 {len(pages)}쪽 중 일부만 표시]"
        return out, stem
    except Exception as e:
        logger.warning(f"[summarize] _load_full_doc_text: {e}")
        return "", ""


def _load_file_content_for_summary(file_type: str, trichef_id: str,
                                    file_path: str, segments: list | None = None
                                    ) -> tuple[str, str]:
    """요약용 파일 본문 로드 — 도메인별로 다른 소스에서 컨텐츠 추출.

    Returns: (content, content_kind)
      doc      : page_text 전체 결합
      image    : Qwen 5-stage caption (title + tagline + synopsis + caption)
      video    : segments STT 텍스트 + 메타
      audio    : segments STT 텍스트
    """
    if file_type in ("doc", "doc_page") and trichef_id:
        # 상세 요약을 위해 컨텍스트 한도 18000자 (qwen2.5:3b 32K 컨텍스트의 일부)
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
        # segments 가 없으면 file_path 로 lookup 시도
        segs = segments or []
        if not segs:
            try:
                from routes.search import _search_trichef_av
                domain = "movie" if file_type in ("video", "movie") else "music"
                # 빈 쿼리로 lookup 안 되므로, file_path 가 인덱스에 있다고 가정
                # → 실제로는 frontend 가 segments 를 함께 전달해야 함
                pass
            except Exception:
                pass
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
- 단순한 한 줄 메타데이터 형태 금지 — 문장으로 서술.

## 2. 배경 및 목적
- 본문이 다루는 배경·맥락·문제의식·필요성을 **3~5문장 1~2개 문단** 으로 서술.

## 3. 주요 내용
- 본문의 흐름을 따라가면서 **장/절/주제별로 문단 단위로** 서술.
- 각 주제마다 ### 소제목 + **3~6문장의 문단** (불릿 점만 있는 것 금지).
- 표·도표·목록은 그 의미를 풀어서 문단에 녹여서 작성.
- 가능하면 5~8개 소제목으로 구성 (본문 분량에 따라 조정).

## 4. 수치·날짜·고유명사
- 본문에 등장하는 면적·인원·금액·기간·좌표 등 **숫자를 그대로 인용**.
- 날짜·연도·기간·인명·기관명·지명·법령명·문헌명을 그대로 보존.
- 이 섹션만 불릿 사용 가능 (각 항목 끝에 [p.N] 또는 [출처:...] 표기 권장).

## 5. 분석 및 시사점
- 본문이 도출하는 결론·권고·향후 계획·한계점을 **연결된 문단** 으로 분석.
- 단순 결론 나열이 아닌, 인과관계·논리적 흐름이 드러나도록 작성.

## 6. 종합
- 위 내용을 4~6문장으로 통합 정리하는 마무리 문단 1개.

작성 규칙 (엄격 준수):
- 핵심 키워드는 **굵게** (`**용어**`) 강조.
- 단순 불릿 나열 지양 — **문단 위주**, 4번 섹션만 예외적으로 불릿 허용.
- 본문에 없는 정보는 추측 금지 ("본문에 명시되지 않음" 표기).
- "[중략]" 마커 부분은 "(이하 생략)" 로 표시.
- 충실하게 작성 — 각 섹션 충분한 분량, 전체 합산 약 4,000~8,000자.
- 한국어, Markdown (제목 `##`/`###`, 강조 `**`, 인용 `>` 사용)."""


def _summarize_sse(file_type: str, trichef_id: str, file_path: str,
                   segments: list | None, file_name: str | None
                   ) -> Generator[str, None, None]:
    """파일 요약 SSE 제너레이터.

    이벤트:
      info          { model, file_type, file_name }
      content_loaded{ length, kind }
      token         { text }
      done          { summary, model, length }
      error         { message }
    """
    def emit(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    model = _get_ollama_model()
    if not model:
        yield emit({"type": "error", "message": "Ollama 미연결 또는 모델 없음."})
        return

    fname = file_name or (file_path or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "?"
    yield emit({"type": "info", "model": model, "file_type": file_type, "file_name": fname})

    # 본문 로드
    content, kind = _load_file_content_for_summary(file_type, trichef_id, file_path, segments)
    if not content or len(content.strip()) < 20:
        yield emit({"type": "error",
                    "message": f"본문을 추출할 수 없습니다 (kind={kind}). 인덱싱 필요."})
        return

    yield emit({"type": "content_loaded", "length": len(content), "kind": kind})

    # 요약 프롬프트
    sys_prompt = _build_summary_prompt(file_type, fname, content)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "이 파일을 위 원칙에 따라 요약해줘."},
    ]

    full = ""
    t0 = time.time()
    stream_error: str | None = None
    try:
        # 논문체 상세 요약 — num_predict 7500 (한국어 ~12,000자, 약 4~8천자 본문 보장)
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
        "type": "done",
        "summary": full,
        "model": model,
        "length": len(content),
        "kind": kind,
        "error": stream_error,
    })


@aimode_bp.post("/summarize")
def summarize():
    """POST /api/aimode/summarize — 파일 요약 SSE 스트리밍.

    Body:
      file_type   : "doc" | "image" | "video" | "audio" | "movie" | "music"
      trichef_id  : str  (doc_page rid 등)
      file_path   : str  (메타용, 표시 fallback)
      file_name   : str  (선택)
      segments    : list (video/audio 전용)
    """
    body = request.get_json(silent=True) or {}
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
