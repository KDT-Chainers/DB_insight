"""
pii_detector.py
──────────────────────────────────────────────────────────────────────────────
1차: Presidio(정규식 + 커스텀 한국형 Recognizer) 탐지
2차: 애매한 경우 Qwen 분류기로 재검증

출력: List[PIIFinding]  (위치, 유형, 신뢰도, 원문)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from security.korean_recognizers import ALL_KOREAN_RECOGNIZERS

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PIIFinding:
    """탐지된 개인정보 하나를 표현"""
    entity_type: str          # 예: "KR_RRN", "PHONE_NUMBER"
    text: str                 # 원문 (예: "920101-1234567")
    start: int                # 청크 내 시작 오프셋
    end: int                  # 청크 내 끝 오프셋
    score: float              # 신뢰도 0.0 ~ 1.0
    chunk_index: int = 0      # 어느 청크에서 발견됐는지
    validated_by_llm: bool = False  # Qwen 2차 검증 여부


@dataclass
class ChunkScanResult:
    """청크 하나의 스캔 결과"""
    chunk_index: int
    text: str
    findings: List[PIIFinding] = field(default_factory=list)

    @property
    def has_pii(self) -> bool:
        return len(self.findings) > 0

    @property
    def pii_types(self) -> List[str]:
        return list({f.entity_type for f in self.findings})


# ──────────────────────────────────────────────────────────────────────────────
# 탐지 엔진
# ──────────────────────────────────────────────────────────────────────────────

class PIIDetector:
    """
    Presidio 기반 PII 탐지기.

    사용법:
        detector = PIIDetector()
        results = detector.scan_chunks(["청크1 텍스트", "청크2 텍스트"])
    """

    # Presidio 에서 기본 지원하는 탐지 항목들
    DEFAULT_ENTITIES = [
        "PHONE_NUMBER",
        "EMAIL_ADDRESS",
        "CREDIT_CARD",
        "IBAN_CODE",
        # 한국형 커스텀 추가됨:
        "KR_RRN",
        "KR_PASSPORT",
        "KR_DRIVER_LICENSE",
        "KR_BANK_ACCOUNT",
        "KR_BRN",
        "KR_PHONE",           # 한국 전화번호 (010/02/지역/대표)
    ]

    def __init__(self, qwen_classifier=None, llm_score_threshold: float = 0.5) -> None:
        """
        Args:
            qwen_classifier: security.qwen_classifier.QwenClassifier 인스턴스
                             None 이면 2차 검증 생략
            llm_score_threshold: 이 점수 미만인 결과만 Qwen 에게 재검증 요청
        """
        self._analyzer = self._build_analyzer()
        self._qwen = qwen_classifier
        self._llm_threshold = llm_score_threshold

    # ── 내부: 엔진 빌드 ────────────────────────────────────────────────────────
    @staticmethod
    def _build_analyzer() -> AnalyzerEngine:
        """
        spaCy 모델 없이도 동작하는 경량 NLP 엔진으로 설정.
        패턴 기반 Recognizer 는 NLP 가 필요 없음.
        """
        try:
            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "ko", "model_name": "ko_core_news_sm"}],
            })
            nlp_engine = provider.create_engine()
        except Exception:
            # spaCy 한국어 모델 미설치 시 영어 엔진으로 폴백
            logger.warning("spaCy ko 모델 없음 → en_core_web_sm 폴백 사용")
            try:
                provider = NlpEngineProvider(nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
                })
                nlp_engine = provider.create_engine()
            except Exception:
                logger.warning("spaCy en 모델도 없음 → NLP 없이 실행")
                nlp_engine = None

        engine = AnalyzerEngine(nlp_engine=nlp_engine)

        # 커스텀 한국형 Recognizer 등록
        for recognizer in ALL_KOREAN_RECOGNIZERS:
            engine.registry.add_recognizer(recognizer)

        return engine

    # ── 공개 API ───────────────────────────────────────────────────────────────
    def scan_chunks(
        self,
        chunks: List[str],
        language: str = "ko",
    ) -> List[ChunkScanResult]:
        """
        청크 목록 전체를 스캔하여 각 청크의 PII 결과 반환.

        Args:
            chunks: 텍스트 청크 리스트
            language: Presidio 언어 코드 (기본 "ko")

        Returns:
            List[ChunkScanResult]
        """
        results: List[ChunkScanResult] = []

        for idx, chunk_text in enumerate(chunks):
            chunk_result = ChunkScanResult(chunk_index=idx, text=chunk_text)

            try:
                presidio_results = self._analyzer.analyze(
                    text=chunk_text,
                    language=language,
                    entities=self.DEFAULT_ENTITIES,
                    score_threshold=0.3,   # 낮은 점수도 일단 수집 후 LLM 재검증
                )
            except Exception as exc:
                logger.warning("Presidio 분석 오류 (chunk %d): %s", idx, exc)
                presidio_results = []

            for r in presidio_results:
                finding = PIIFinding(
                    entity_type=r.entity_type,
                    text=chunk_text[r.start:r.end],
                    start=r.start,
                    end=r.end,
                    score=r.score,
                    chunk_index=idx,
                )

                # 신뢰도가 낮으면 Qwen 으로 재검증
                if self._qwen and r.score < self._llm_threshold:
                    finding = self._verify_with_qwen(finding, chunk_text)
                    if finding is None:
                        continue   # Qwen 이 PII 아님으로 판단 → 제외

                chunk_result.findings.append(finding)

            results.append(chunk_result)

        return results

    def _verify_with_qwen(
        self,
        finding: PIIFinding,
        context: str,
    ) -> Optional[PIIFinding]:
        """
        Qwen 에게 "이 텍스트가 {entity_type} 인가?" 묻고 결과 반환.
        Qwen 이 아니라고 하면 None 반환.
        """
        try:
            answer = self._qwen.ask_pii_verification(
                candidate_text=finding.text,
                entity_type=finding.entity_type,
                context=context[:300],   # 긴 문맥 전달하지 않음
            )
            if not answer:
                return None
            finding.validated_by_llm = True
            finding.score = max(finding.score, 0.7)   # Qwen 검증 통과 시 점수 상향
            return finding
        except Exception as exc:
            logger.warning("Qwen PII 재검증 오류: %s", exc)
            return finding   # 오류 시 원래 결과 유지


# ──────────────────────────────────────────────────────────────────────────────
# 마스킹 유틸리티
# ──────────────────────────────────────────────────────────────────────────────

def mask_text(text: str, findings: List[PIIFinding]) -> str:
    """
    findings 목록에 따라 텍스트의 민감 부분을 *** 로 마스킹.
    오프셋 역순으로 처리해 위치 틀어짐 방지.
    """
    chars = list(text)
    for f in sorted(findings, key=lambda x: x.start, reverse=True):
        entity_label = f"[{f.entity_type}]"
        chars[f.start:f.end] = list(entity_label)
    return "".join(chars)
