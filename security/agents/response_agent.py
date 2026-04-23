"""
agents/response_agent.py
──────────────────────────────────────────────────────────────────────────────
응답 생성 에이전트.

ABC 권한: [C] 외부 통신 (Ollama/Qwen 호출)
금지:     [A] 신뢰불가 입력 직접 처리  /  [B] DB 직접 접근

v2 변경점:
  - generate_from_secure 제거 (단일 인덱스로 원문 직접 접근 가능)
  - SENSITIVE 기본 경로: LLM에 마스킹 응답 지시 프롬프트 사용
  - 원문 청크가 있으므로 LLM이 내용을 파악하되 응답에서만 마스킹
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List

import config
from harness.safe_tools import CAP_C, enforce_abc

logger = logging.getLogger(__name__)

# ── 프롬프트 템플릿 ───────────────────────────────────────────────────────────

_RAG_PROMPT = """아래 문서 내용을 참고하여 사용자 질문에 답하세요.
문서에 없는 내용은 모른다고 답하세요. 답변은 한국어로 작성하세요.

[참고 문서]
{context}

[사용자 질문]
{question}

[답변]"""

_MASKED_PREVIEW_PROMPT = """아래 문서에는 개인정보가 포함되어 있습니다.
질문에 답할 때 개인정보(주민번호, 여권번호, 계좌번호, 전화번호 등)는
반드시 ●●● 또는 [개인정보] 로 대체하여 답하세요.
문서에 없는 내용은 모른다고 답하세요.

[참고 문서]
{context}

[사용자 질문]
{question}

[답변 (개인정보 마스킹 버전)]"""


class ResponseAgent:
    """
    허용된 결과를 기반으로 최종 답변을 생성한다.

    ABC 원칙:
      capabilities = {CAP_C}  →  C 만 보유 (Ollama 호출)
      DB 직접 조회 금지
      사용자 원문 입력을 직접 받지 않음 (Orchestrator가 필터링 후 전달)

    v2 SENSITIVE 처리:
      - 원문 청크를 받아 LLM에게 마스킹 응답을 지시
      - full_view=True: 원문 그대로 응답
      - UI 카드: display_masked 플래그로 별도 시각 마스킹
    """

    CAPABILITIES = {CAP_C}

    def __init__(
        self,
        model: str = config.QWEN_MODEL,
        ollama_url: str = config.OLLAMA_URL,
        timeout: int = config.QWEN_TIMEOUT_SEC,
    ) -> None:
        enforce_abc("ResponseAgent", self.CAPABILITIES)
        self._model   = model
        self._url     = ollama_url.rstrip("/") + "/api/generate"
        self._timeout = timeout

    # ── 공개 API ───────────────────────────────────────────────────────────────

    def generate(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        masked: bool = False,
    ) -> str:
        """
        검색된 청크를 컨텍스트로 사용하여 답변을 생성한다.

        Args:
            question: (Orchestrator가 검증한) 사용자 질문
            chunks:   RetrievalAgent가 반환한 원문 청크 리스트
            masked:   True이면 LLM에게 PII 마스킹 응답 지시

        Returns:
            생성된 답변 문자열
        """
        if not chunks:
            return "관련 문서를 찾지 못했습니다."

        context  = self._build_context(chunks)
        template = _MASKED_PREVIEW_PROMPT if masked else _RAG_PROMPT
        prompt   = template.format(context=context, question=question)
        return self._call_ollama(prompt)

    def generate_masked_preview(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
    ) -> str:
        """
        SENSITIVE 기본 경로: LLM에게 PII를 마스킹하여 응답하도록 지시한다.
        원문 청크를 받지만 응답에서는 PII를 ●●●로 대체한다.
        """
        return self.generate(question, chunks, masked=True)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_context(chunks: List[Dict[str, Any]]) -> str:
        """청크 텍스트를 컨텍스트 문자열로 합친다."""
        parts = []
        for chunk in chunks:
            text = chunk.get("text", "")
            doc  = chunk.get("doc_name") or chunk.get("file_name") or ""
            page = chunk.get("source_page", "?")
            parts.append(f"[출처: {doc} p.{page}]\n{text}")
        return "\n\n".join(parts)

    def _call_ollama(self, prompt: str) -> str:
        """Ollama generate API를 호출한다."""
        payload = json.dumps({
            "model":  self._model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("response", "(응답 없음)").strip()
        except urllib.error.URLError as exc:
            logger.error("Ollama 연결 실패: %s", exc)
            return "Ollama 서버에 연결할 수 없습니다. `ollama serve`를 실행했는지 확인하세요."
        except Exception as exc:
            logger.error("응답 생성 오류: %s", exc)
            return f"응답 생성 중 오류가 발생했습니다: {exc}"
