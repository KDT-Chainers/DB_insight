"""
qwen_classifier.py
──────────────────────────────────────────────────────────────────────────────
Qwen 을 생성형 챗봇이 아닌 보안 분류기로 사용.

역할 1) 사용자 질문을 3가지로 분류
    NORMAL    → allow
    SENSITIVE → confirm
    DANGEROUS → block

역할 2) PII 탐지 보조 (애매한 후보 텍스트 재검증)

중요: 보안 에이전트는 DB 원문이나 청크 전체를 받지 않는다.
      Feature Map 과 메타데이터만 입력받아 정책을 판단한다. (ABC 원칙)
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

import config

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 출력 타입
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    label: str          # NORMAL | SENSITIVE | DANGEROUS
    reason: str         # 판단 이유
    action: str         # allow | confirm | block
    raw_response: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Qwen 분류기
# ──────────────────────────────────────────────────────────────────────────────

class QwenClassifier:
    """
    Ollama 로 실행 중인 Qwen 에 HTTP 요청을 보내 분류 수행.

    ABC 원칙 준수:
      - 이 클래스는 [A] 신뢰불가 입력(사용자 질문)을 받는다.
      - [B] 민감 DB 에 직접 접근하지 않는다.
      - [C] Ollama 외부 통신은 하지만 상태 변경(DB 쓰기 등)은 수행하지 않는다.
      → B가 없으므로 A+C 조합 = 허용 범위
    """

    # 분류 프롬프트 템플릿
    _CLASSIFY_SYSTEM = """당신은 보안 정책 판단 AI입니다.
아래 기준으로 사용자 질문을 분류하고, 반드시 label에 맞는 action을 출력하세요.

분류 기준 및 action 매핑 (절대 변경 금지):
- NORMAL   → action: "allow"    (일반적인 문서 조회, 요약, 검색 요청)
- SENSITIVE → action: "confirm"  (특정 개인정보·여권·계좌·주민번호 등을 요청하는 경우)
- DANGEROUS → action: "block"   (DB 전체 출력, 대량 개인정보 요청, 시스템 명령 시도)

중요: SENSITIVE일 때 action은 반드시 "confirm"이어야 합니다. "allow"는 NORMAL 전용입니다.

언어 규칙 (반드시 준수):
- "reason" 필드는 **한국어로만** 1~2문장 작성합니다.
- 일본어·중국어·영어로 된 문장·설명은 절대 넣지 마세요. (UI가 한국어 전용입니다.)

Feature Map (Retrieval Engine 생성, 원문 아님):
{feature_map}

반드시 아래 JSON 형식으로만 답하세요. 다른 말 금지.
{{
  "label": "NORMAL | SENSITIVE | DANGEROUS",
  "reason": "한국어로만, 판단 이유 1~2문장",
  "action": "allow | confirm | block"
}}"""

    _PII_VERIFY_SYSTEM = """당신은 개인정보 탐지 전문가입니다.
아래 텍스트가 {entity_type} 에 해당하는 실제 개인정보인지 판단하세요.

문맥(앞뒤 텍스트):
{context}

후보 텍스트: "{candidate}"

YES 또는 NO 만 답하세요."""

    _REWRITE_SYSTEM = """당신은 검색 질의 재작성기입니다.
사용자 질문의 의미를 유지한 채, 검색 recall을 높이기 위해 핵심 키워드를 보강한 1줄 질의로 재작성하세요.

규칙:
- 원문 의미를 절대 바꾸지 말 것
- 한국어/영어 혼용 키워드가 필요하면 짧게 추가 가능
- 개인정보를 새로 만들어내지 말 것
- 설명 없이 재작성된 질의 1줄만 출력
"""

    def __init__(
        self,
        model: str = config.QWEN_MODEL,
        url: str = config.OLLAMA_URL,
        timeout: int = config.QWEN_TIMEOUT_SEC,
    ) -> None:
        self._model = model
        self._url = url.rstrip("/") + "/api/generate"
        self._timeout = timeout

    # ── 공개 API ───────────────────────────────────────────────────────────────

    def classify_query(
        self,
        user_query: str,
        feature_map: Dict[str, Any],
    ) -> ClassificationResult:
        """
        사용자 질문 + Feature Map → NORMAL / SENSITIVE / DANGEROUS 분류.

        주의: 원문 청크나 DB 내용은 절대 이 함수에 전달하지 말 것.
        """
        prompt = self._CLASSIFY_SYSTEM.format(
            feature_map=json.dumps(feature_map, ensure_ascii=False, indent=2)
        )
        full_prompt = f"{prompt}\n\n사용자 질문: {user_query}"

        raw = self._call_ollama(full_prompt)
        result = self._parse_classification(raw)
        result.reason = self._normalize_reason_korean(result.reason, result.label)
        return result

    def ask_pii_verification(
        self,
        candidate_text: str,
        entity_type: str,
        context: str,
    ) -> bool:
        """
        후보 텍스트가 entity_type 에 해당하는지 Qwen 에게 확인.
        True = PII 맞음, False = 아님
        """
        prompt = self._PII_VERIFY_SYSTEM.format(
            entity_type=entity_type,
            context=context,
            candidate=candidate_text,
        )
        raw = self._call_ollama(prompt)
        return raw.strip().upper().startswith("YES")

    def rewrite_query(self, user_query: str, max_chars: int = 160) -> str:
        """
        검색 친화 질의로 1회 재작성.
        실패 시 원문 질의를 그대로 반환한다.
        """
        if not user_query.strip():
            return user_query

        prompt = (
            f"{self._REWRITE_SYSTEM}\n\n"
            f"원문 질문: {user_query}\n"
            "재작성 질의:"
        )
        raw = self._call_ollama(prompt).strip()
        if not raw:
            return user_query

        # 모델이 따옴표/번호/설명을 붙이는 경우를 최소 정리
        line = raw.splitlines()[0].strip().strip("\"'`")
        if not line:
            return user_query
        if line.lower().startswith("재작성"):
            parts = line.split(":", 1)
            line = parts[1].strip() if len(parts) == 2 else line

        if len(line) > max_chars:
            line = line[:max_chars].rstrip()

        # 지나치게 짧거나 원문과 사실상 동일하면 원문 유지
        if len(line) < 3:
            return user_query
        return line

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _call_ollama(self, prompt: str) -> str:
        """Ollama /api/generate 엔드포인트 호출"""
        payload = json.dumps({
            "model": self._model,
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
                return body.get("response", "")
        except urllib.error.URLError as exc:
            logger.error("Ollama 연결 실패: %s", exc)
            return ""
        except Exception as exc:
            logger.error("Ollama 호출 오류: %s", exc)
            return ""

    # label → 올바른 action 매핑 (Qwen 응답 보정용)
    _LABEL_ACTION_MAP = {
        "NORMAL":    "allow",
        "SENSITIVE": "confirm",
        "DANGEROUS": "block",
    }

    @staticmethod
    def _default_reason_korean(label: str) -> str:
        """모델이 한국어가 아닌 reason을보낼 때 사용하는 고정 문구."""
        return {
            "NORMAL": (
                "일반적인 문서 검색·조회 요청으로 분류되었습니다."
            ),
            "SENSITIVE": (
                "개인정보·민감정보를 직접적으로 요청하는 질문으로 분류되었습니다."
            ),
            "DANGEROUS": (
                "대량 유출·시스템 조작 등 위험한 요청으로 분류되었습니다."
            ),
        }.get(label.upper(), "보안 정책에 따라 분류되었습니다.")

    @staticmethod
    def _normalize_reason_korean(reason: str, label: str) -> str:
        """
        reason을 UI용 한국어로 맞춘다.
        일본어(가나)·영어 전용 등은 레이블별 기본 한국어 문구로 대체한다.
        """
        text = (reason or "").strip()
        if not text:
            return QwenClassifier._default_reason_korean(label)
        # 히라가나·가타카나 포함 → 일본어 응답으로 간주
        if re.search(r"[\u3040-\u309F\u30A0-\u30FF]", text):
            logger.info("분류 reason 일본어 감지 → 한국어 기본 문구로 대체")
            return QwenClassifier._default_reason_korean(label)
        # 한글 음절이 하나도 없으면(영어만 등) UI 일관성을 위해 대체
        if not re.search(r"[\uAC00-\uD7AF]", text):
            logger.info("분류 reason 비한국어 감지 → 한국어 기본 문구로 대체")
            return QwenClassifier._default_reason_korean(label)
        return text

    @staticmethod
    def _parse_classification(raw: str) -> ClassificationResult:
        """
        Qwen 응답에서 JSON 파싱.

        - label에 맞지 않는 action이 오면 _LABEL_ACTION_MAP으로 자동 보정
          (예: SENSITIVE인데 action="allow" → "confirm"으로 강제 수정)
        - 파싱 실패 시 SENSITIVE/confirm으로 폴백 (안전 우선)
        """
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("JSON 블록 없음")
            data = json.loads(raw[start:end])

            label  = data.get("label", "SENSITIVE").upper()
            reason = data.get("reason", "")

            # label에 맞는 action을 강제 적용 (Qwen이 잘못 내보낼 때 보정)
            correct_action = QwenClassifier._LABEL_ACTION_MAP.get(label, "confirm")
            raw_action     = data.get("action", correct_action).lower()
            # raw_action과 correct_action이 다르면 로그 경고 후 보정
            if raw_action != correct_action:
                logger.warning(
                    "Qwen action 불일치 보정: label=%s raw_action=%s → %s",
                    label, raw_action, correct_action,
                )

            return ClassificationResult(
                label=label,
                reason=reason,
                action=correct_action,
                raw_response=raw,
            )
        except Exception as exc:
            logger.warning("Qwen 응답 파싱 실패 (%s) → SENSITIVE/confirm 폴백", exc)
            return ClassificationResult(
                label="SENSITIVE",
                reason="파싱 실패, 안전 폴백(SENSITIVE)",
                action="confirm",
                raw_response=raw,
            )

    def is_available(self) -> bool:
        """Ollama 서버 기동 확인"""
        try:
            url = config.OLLAMA_URL.rstrip("/") + "/api/tags"
            with urllib.request.urlopen(url, timeout=5):
                return True
        except Exception:
            return False
