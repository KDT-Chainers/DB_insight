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
from typing import Generator

from flask import Blueprint, Response, jsonify, request
import requests as _req

logger = logging.getLogger(__name__)
aimode_bp = Blueprint("aimode", __name__, url_prefix="/api/aimode")

OLLAMA_URL = "http://localhost:11434"
STEP_DELAY = 1.5   # 각 시각화 단계 사이 (초)


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


# ── 메인 SSE 제너레이터 ─────────────────────────────────────────────
def _aimode_sse(query: str, topk: int) -> Generator[str, None, None]:
    def emit(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    model = _get_ollama_model()
    if not model:
        yield emit({"type": "error", "message": "Ollama 미연결 또는 모델 없음. ollama pull qwen2.5:3b 필요."})
        return

    # ── Step 1: 검색어 추출 (LLM) ─────────────────────────────────────
    yield emit({"type": "step", "step": 1, "label": "🔍 질문에서 검색어 추출 중...",
                "model": model, "user_question": query})
    extracted = _extract_query(query, model)
    yield emit({"type": "step", "step": 1, "label": f"✓ 검색어: {extracted!r}",
                "query": extracted, "done": True})
    time.sleep(STEP_DELAY)

    # ── Step 2: 검색 ─────────────────────────────────────────────────
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

    # ── Step 3: 가장 관련 카드 자동 선택 ──────────────────────────────
    selected_idx = 0  # confidence 최상위
    selected = sources[selected_idx]
    yield emit({
        "type": "step", "step": 3,
        "label": f"🎯 가장 관련된 결과 선택 (#{selected_idx+1})",
        "selected_idx": selected_idx,
        "selected_name": selected.get("file_name", ""),
    })
    time.sleep(STEP_DELAY)

    # ── Step 4: 답변 생성 (Ollama 스트리밍) ───────────────────────────
    yield emit({"type": "step", "step": 4, "label": "✨ 답변 정리 중...",
                "selected_idx": selected_idx})
    sys_prompt = _build_system_prompt(selected, sources)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user",   "content": query},
    ]
    full_answer = ""
    for tok in _ollama_stream(messages, model):
        full_answer += tok
        yield emit({"type": "token", "text": tok})

    yield emit({
        "type":         "done",
        "answer":       full_answer,
        "selected_idx": selected_idx,
        "model":        model,
        "extracted":    extracted,
    })


# ── Flask 엔드포인트 ───────────────────────────────────────────────
@aimode_bp.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    topk = max(1, min(int(body.get("topk", 5)), 10))
    if not query:
        return jsonify({"error": "query 필수"}), 400

    return Response(
        _aimode_sse(query, topk),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@aimode_bp.get("/status")
def status():
    model = _get_ollama_model()
    return jsonify({
        "ollama_model":     model,
        "ollama_available": model is not None,
        "step_delay_sec":   STEP_DELAY,
    })
