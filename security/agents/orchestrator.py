"""
agents/orchestrator.py
──────────────────────────────────────────────────────────────────────────────
전체 흐름을 제어하는 오케스트레이터.

ABC 원칙:
  Orchestrator는 A·B·C를 동시에 가져서는 안 됨.
  각 하위 에이전트에 권한을 위임하되, 자신은 '흐름 제어'만 수행.

  실제 권한 행사:
    - 파일 검사   → UploadSecurityAgent  (A)
    - DB 검색     → RetrievalAgent        (B)
    - 응답 생성   → ResponseAgent         (C)
    - 보안 분류   → QwenClassifier        (A, 단독)
    - 정책 판단   → SecurityPolicy
    - Grounding   → GroundingGate
    - 감사 기록   → AuditLogger

리팩토링 변경점 (v2 단일 인덱스):
  - 마스킹 텍스트 저장 방식 제거
  - 원문 그대로 저장 + PII 유형 태그
  - UI 렌더링 단계에서만 마스킹/모자이크 적용
  - SecureRetrievalGateway, meta_index 제거
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import config
from agents.retrieval_agent import RetrievalAgent
from agents.upload_security import UploadScanResult, UploadSecurityAgent
from audit.logger import AuditLogger
from document.chunker import Chunk
from security.grounding_gate import GroundingGate
from security.pii_detector import PIIDetector
from security.policy import SecurityPolicy, UploadPolicy
from security.qwen_classifier import QwenClassifier
from vectordb.store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class QueryResponse:
    """질문에 대한 최종 응답 구조"""
    answer: str
    label: str
    action: str
    blocked: bool
    masked_preview: bool
    reason: str
    retrieved_chunk_ids: List[int] = field(default_factory=list)
    retrieved_chunks: List[Dict[str, Any]] = field(default_factory=list)  # UI 소스 카드용


class Orchestrator:
    """
    전체 RAG 파이프라인을 조율하는 메인 컨트롤러.

    사용법:
        orch = Orchestrator.build()
        scan = orch.handle_upload("my_doc.pdf")
        orch.commit_upload(scan, user_choice="mask_and_embed")
        response = orch.handle_query("여권 사진 찾아줘")
    """

    def __init__(
        self,
        upload_agent:    UploadSecurityAgent,
        retrieval_agent: RetrievalAgent,
        qwen:            QwenClassifier,
        policy:          SecurityPolicy,
        store:           VectorStore,
        audit:           AuditLogger,
        grounding_gate:  GroundingGate,
    ) -> None:
        self._upload_agent    = upload_agent
        self._retrieval_agent = retrieval_agent
        self._qwen            = qwen
        self._policy          = policy
        self._store           = store
        self._audit           = audit
        self._grounding_gate  = grounding_gate

    # ── 팩토리 ────────────────────────────────────────────────────────────────

    @classmethod
    def build(cls) -> "Orchestrator":
        """의존성을 자동 생성하여 Orchestrator를 반환한다."""
        store    = VectorStore()
        qwen     = QwenClassifier()
        detector = PIIDetector(qwen_classifier=qwen)
        audit    = AuditLogger()

        return cls(
            upload_agent    = UploadSecurityAgent(pii_detector=detector),
            retrieval_agent = RetrievalAgent(store=store),
            qwen            = qwen,
            policy          = SecurityPolicy(),
            store           = store,
            audit           = audit,
            grounding_gate  = GroundingGate(),
        )

    # ── 업로드 흐름 ───────────────────────────────────────────────────────────

    def handle_upload(self, file_path: str | Path) -> UploadScanResult:
        """
        Step 1: 파일을 받아 보안 스캔 결과를 반환한다 (저장 안 함).
        UI는 이 결과를 보고 브레이크 모달을 표시한다.
        """
        return self._upload_agent.scan_file(file_path)

    def commit_upload(
        self,
        scan_result: UploadScanResult,
        user_choice: str,
    ) -> Dict[str, Any]:
        """
        Step 2: 사용자 선택에 따라 원문을 임베딩 저장한다.

        v2 변경점:
          - 텍스트 마스킹 없이 원문 그대로 저장
          - PII 유형·민감도를 메타데이터 태그로만 기록
          - display_masked=True이면 UI 카드에서만 마스킹 렌더링

        user_choice 별 동작:
          mask_and_embed   → 원문 저장 + display_masked=True (UI 마스킹)
          skip_pii_chunks  → PII 청크 제외 후 나머지 저장
          embed_all        → 전부 원문 저장 (display_masked=False)
          cancel           → 저장 안 함

        Args:
            scan_result: handle_upload() 결과
            user_choice: UploadPolicy 상수 중 하나

        Returns:
            결과 요약 dict
        """
        directive = UploadPolicy.resolve(user_choice)

        if not directive["proceed"]:
            self._audit.log_upload(
                filename=scan_result.filename,
                pii_types=[],
                user_choice=user_choice,
            )
            return {"status": "cancelled", "message": "업로드가 취소되었습니다."}

        chunks    = scan_result.chunks
        pii_types: List[str] = []

        processed_chunks: List[Chunk] = []
        # chunk.index → PII 메타 태그
        pii_metadata: Dict[int, Dict[str, Any]] = {}

        for chunk, scan_r in zip(chunks, scan_result.scan_results):
            # PII 청크 제외 옵션
            if directive["exclude_pii_chunks"] and scan_r.has_pii:
                pii_types.extend(scan_r.pii_types)
                continue

            # PII 태그 구성 (텍스트는 원문 그대로 유지)
            if scan_r.has_pii:
                pii_types.extend(scan_r.pii_types)
                sensitivity = self._calc_sensitivity(scan_r.pii_types)
                pii_metadata[chunk.index] = {
                    "has_pii":           True,
                    "pii_types":         list(scan_r.pii_types),
                    "sensitivity_score": sensitivity,
                    # display_masked: 마스킹 모드 선택 시 True (UI 렌더링만 제어)
                    "display_masked":    bool(directive.get("mask", False)),
                    # 이미지 전용 메타데이터
                    "is_image":          scan_result.is_image,
                    "image_path":        scan_result.image_path,
                    "pii_regions":       scan_result.image_pii_regions,
                }
            else:
                pii_metadata[chunk.index] = {
                    "has_pii":           False,
                    "pii_types":         [],
                    "sensitivity_score": 0.0,
                    "display_masked":    False,
                    "is_image":          scan_result.is_image,
                    "image_path":        scan_result.image_path,
                    "pii_regions":       [],
                }

            processed_chunks.append(chunk)

        # 원문 임베딩 저장 (마스킹 없음)
        self._store.add_chunks(processed_chunks, pii_metadata=pii_metadata)

        self._audit.log_upload(
            filename=scan_result.filename,
            pii_types=list(set(pii_types)),
            user_choice=user_choice,
        )

        masked_count = sum(
            1 for m in pii_metadata.values() if m.get("display_masked")
        )

        return {
            "status":          "ok",
            "total_chunks":    len(chunks),
            "embedded_chunks": len(processed_chunks),
            "pii_tagged":      sum(1 for m in pii_metadata.values() if m.get("has_pii")),
            "ui_masked":       masked_count,
        }

    # ── 질문 흐름 ─────────────────────────────────────────────────────────────

    def handle_query(
        self,
        user_query: str,
        full_view: bool = False,
    ) -> QueryResponse:
        """
        사용자 질문 처리 파이프라인 (v2 단일 인덱스).

        Steps:
          1. Query Rewrite (Qwen, 옵션)
          2. RetrievalAgent: 단일 인덱스 원문 검색
          3. QwenClassifier: 보안 분류
          4. SecurityPolicy: 정책 판단
          5. GroundingGate:  근거 확인
          6a. NORMAL    → 원문 청크로 답변
          6b. SENSITIVE → 마스킹 미리보기 (default) 또는 전체 보기
          6c. DANGEROUS → 차단
          7. AuditLogger 기록

        Args:
            user_query: 사용자 입력 질문
            full_view:  True이면 SENSITIVE에서 원본 전체 보기

        Returns:
            QueryResponse
        """
        # ── Step 1: Query Rewrite ─────────────────────────────────────────────
        rewritten_query = user_query
        if config.QUERY_REWRITE_ENABLED and self._qwen.is_available():
            rewritten_query = self._qwen.rewrite_query(
                user_query,
                max_chars=config.QUERY_REWRITE_MAX_CHARS,
            )
            if rewritten_query != user_query:
                logger.info("Query rewrite: '%s' → '%s'", user_query, rewritten_query)

        # ── Step 2: 원문 검색 ─────────────────────────────────────────────────
        retrieval_result = self._retrieval_agent.retrieve(rewritten_query)
        feature_map = retrieval_result.feature_map
        chunks      = retrieval_result.chunks

        # ── Step 3: Qwen 보안 분류 ────────────────────────────────────────────
        if self._qwen.is_available():
            classification = self._qwen.classify_query(user_query, feature_map)
        else:
            classification = self._fallback_classify(user_query, feature_map)

        label  = classification.label
        reason = classification.reason

        # ── Step 4: 정책 판단 ─────────────────────────────────────────────────
        decision         = self._policy.evaluate(label, feature_map)
        effective_action = self._policy_action(decision, full_view)

        chunk_ids = [c.get("id", 0) for c in chunks]

        # ── Step 5: DANGEROUS 차단 ───────────────────────────────────────────
        if not decision.allow:
            self._audit.log_query(
                query_text=user_query, label=label,
                action=effective_action, blocked=True, retrieved_ids=chunk_ids,
            )
            # 내용은 차단하되 파일명·경로만 카드에 전달 (텍스트 제거)
            path_only_chunks = [
                {
                    "id":          c.get("id"),
                    "doc_name":    c.get("doc_name", ""),
                    "file_name":   c.get("file_name", ""),
                    "source_path": c.get("source_path", ""),
                    "source_page": c.get("source_page", ""),
                    "text":        "",   # 내용 차단
                    "has_pii":     c.get("has_pii", False),
                    "pii_types":   c.get("pii_types", []),
                    "display_masked": False,
                    "is_image":    c.get("is_image", False),
                    "image_path":  c.get("image_path", ""),
                    "pii_regions": c.get("pii_regions", []),
                    "score":       c.get("score"),
                    "_blocked":    True,  # UI 카드에서 차단 메시지 표시용
                }
                for c in chunks
            ]
            return QueryResponse(
                answer="", label=label, action=effective_action,
                blocked=True, masked_preview=False, reason=reason,
                retrieved_chunk_ids=chunk_ids, retrieved_chunks=path_only_chunks,
            )

        # ── Step 5b: GroundingGate ────────────────────────────────────────────
        grounded = self._grounding_gate.check(
            user_query=user_query,
            chunks=chunks,
            label=label,
        )
        self._audit.log_query(
            query_text=user_query, label=label,
            action=effective_action, blocked=False,
            retrieved_ids=chunk_ids, full_view_requested=full_view,
        )

        # GroundingGate 미통과 → 빈 결과 반환 (소스 카드 없음)
        if not grounded:
            return QueryResponse(
                answer="", label=label, action=effective_action,
                blocked=False, masked_preview=False, reason=reason,
                retrieved_chunk_ids=[], retrieved_chunks=[],
            )

        # ── Step 6: 검색 결과 반환 (LLM 답변 없음) ───────────────────────────
        masked_preview = bool(label == "SENSITIVE" and decision.masked_preview and not full_view)
        return QueryResponse(
            answer="", label=label, action=effective_action,
            blocked=False, masked_preview=masked_preview, reason=reason,
            retrieved_chunk_ids=chunk_ids, retrieved_chunks=chunks,
        )

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_sensitivity(pii_types: List[str]) -> float:
        """PII 유형 목록에서 민감도 점수를 계산한다 (0.0 ~ 1.0)."""
        _WEIGHTS = {
            "KR_RRN": 1.0, "KR_PASSPORT": 0.9, "KR_DRIVER_LICENSE": 0.8,
            "KR_BANK_ACCOUNT": 0.85, "KR_BRN": 0.6,
            "PERSON": 0.4, "EMAIL_ADDRESS": 0.5, "PHONE_NUMBER": 0.6,
        }
        if not pii_types:
            return 0.0
        base = max((_WEIGHTS.get(t, 0.3) for t in pii_types), default=0.0)
        if len(pii_types) > 1:
            base = min(1.0, base + 0.05 * (len(pii_types) - 1))
        return round(base, 4)

    @staticmethod
    def _fallback_classify(user_query: str, feature_map: Dict[str, Any]):
        """Ollama 없을 때 키워드 기반 간이 분류."""
        from security.qwen_classifier import ClassificationResult
        q = user_query.lower()
        dangerous_kw = ["전부", "모두", "전체 출력", "dump", "export", "삭제", "all records"]
        sensitive_kw = [
            "계좌번호", "주민번호", "비밀번호", "카드번호", "패스워드",
            "여권", "passport", "운전면허", "사업자번호", "사업자등록",
        ]
        if any(kw in q for kw in dangerous_kw) or feature_map.get("bulk_request"):
            return ClassificationResult(
                label="DANGEROUS", reason="위험 키워드 감지 (폴백)", action="block",
            )
        if any(kw in q for kw in sensitive_kw) or feature_map.get("contains_pii"):
            return ClassificationResult(
                label="SENSITIVE", reason="민감 키워드 감지 (폴백)", action="confirm",
            )
        return ClassificationResult(
            label="NORMAL", reason="일반 질문 (폴백)", action="allow",
        )

    @staticmethod
    def _policy_action(decision: Any, full_view: bool) -> str:
        """UI/로그 표시는 최종 정책 action으로 통일한다."""
        if not decision.allow:
            return "block"
        if decision.require_confirm and not full_view:
            return "confirm"
        return "allow"
