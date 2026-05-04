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
    - 요약·출력   → SummaryAgent + SummaryGuard (C; 범용 LLM Q&A/ResponseAgent 없음)
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
import re
import uuid
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
from agents.summary import SummaryAgent, SummaryResult
from security.pii_filter_helpers import sensitivity_from_protected_types
from security.privacy_risk_score import classify_by_prs
from security.qwen_classifier import QwenClassifier
from security.summary_guard import SummaryGuard
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
    summary: Optional[SummaryResult] = None  # 요약 요청일 때만 SummaryAgent 결과


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
        qwen:            Optional[QwenClassifier],
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
        self._summary_agent    = SummaryAgent()
        self._summary_guard    = SummaryGuard(self._summary_agent)
        # 최근 업로드 문서 식별자(source_path/file_name)를 기억해
        # 요약 질의 시 과거 문서와의 혼입을 줄인다.
        self._recent_upload_keys: List[str] = self._store.get_recent_upload_keys()
        if self._recent_upload_keys:
            logger.info(
                "[Orchestrator] 최근 업로드 키 %d개 복원",
                len(self._recent_upload_keys),
            )

    # ── 팩토리 ────────────────────────────────────────────────────────────────

    @classmethod
    def build(cls) -> "Orchestrator":
        """의존성을 자동 생성하여 Orchestrator를 반환한다."""
        store = VectorStore()
        qwen: Optional[QwenClassifier] = QwenClassifier() if config.USE_QWEN else None
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
        content_sha = (getattr(scan_result, "content_sha256", None) or "").strip()

        # 이번 요청 문서 키 후보는 중복 여부와 무관하게 먼저 구성
        fresh_keys: List[str] = []
        for c in chunks:
            if c.source_path:
                fresh_keys.append(str(c.source_path))
            if c.doc_name:
                fresh_keys.append(str(c.doc_name))
        dedup_fresh = list(dict.fromkeys(fresh_keys))

        # 동일 바이트 내용이 이미 인덱스에 있으면 중복 임베딩 방지
        if content_sha and chunks and self._store.has_content_sha256(content_sha):
            if dedup_fresh:
                self._recent_upload_keys = dedup_fresh
                self._store.set_recent_upload_keys(self._recent_upload_keys)
            logger.info(
                "[Orchestrator] 동일 내용 파일 이미 임베딩됨 — 건너뜀: %s",
                scan_result.filename,
            )
            self._audit.log_upload(
                filename=scan_result.filename,
                pii_types=[],
                user_choice="duplicate_skipped",
            )
            return {
                "status":          "duplicate",
                "message":         "동일한 내용의 파일이 이미 인덱스에 있습니다. 중복 임베딩을 건너뜁니다.",
                "total_chunks":    len(chunks),
                "embedded_chunks": 0,
                "pii_tagged":      0,
                "ui_masked":       0,
            }

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

        # 이번 업로드 문서 키를 최신 상태로 갱신 (요약 시 우선 필터링에 사용)
        if dedup_fresh:
            self._recent_upload_keys = dedup_fresh
            self._store.set_recent_upload_keys(self._recent_upload_keys)

        # 원문 임베딩 저장 (마스킹 없음)
        self._store.add_chunks(
            processed_chunks,
            pii_metadata=pii_metadata,
            content_sha256=content_sha,
        )

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
        req_id = uuid.uuid4().hex[:8]
        # ── Step 1: Query Rewrite (USE_QWEN=1 + Ollama 사용 가능할 때만)
        is_summary = Orchestrator.is_summary_request(user_query)
        logger.info(
            "[OBS][%s] query_start summary=%s full_view=%s q=%r",
            req_id, is_summary, full_view, user_query[:120],
        )
        # 요약 질의이고 문서명 힌트가 있으면 해당 문서에 집중 검색한다.
        doc_hint = Orchestrator._extract_doc_hint(user_query, self._store.list_doc_names()) if is_summary else ""
        rewritten_query = user_query
        if (
            config.USE_QWEN
            and config.QUERY_REWRITE_ENABLED
            and self._qwen is not None
            and self._qwen.is_available()
        ):
            rewritten_query = self._qwen.rewrite_query(
                user_query,
                max_chars=config.QUERY_REWRITE_MAX_CHARS,
            )
            if rewritten_query != user_query:
                logger.info("Query rewrite: '%s' → '%s'", user_query, rewritten_query)

        # ── Step 2: 원문 검색 ─────────────────────────────────────────────────
        summary_doc_contains_pii = False
        retrieval_top_k = config.SUMMARY_TOP_K if is_summary else config.TOP_K
        if doc_hint:
            # 문서명 힌트가 있으면 해당 문서 한정 검색 → 다른 문서와 섞이지 않음
            raw_chunks = self._store.search_within_doc(
                rewritten_query,
                doc_name_hint=doc_hint,
                top_k=retrieval_top_k,
            )
            logger.info("[Orchestrator] 문서 집중 검색 (hint=%r): %d청크", doc_hint, len(raw_chunks))
            if raw_chunks:
                feature_map = self._store.build_feature_map(raw_chunks, rewritten_query)
                chunks = raw_chunks
            else:
                # 힌트 검색 결과 없으면 일반 검색으로 폴백
                retrieval_result = self._retrieval_agent.retrieve(rewritten_query, top_k=retrieval_top_k)
                feature_map = retrieval_result.feature_map
                chunks      = retrieval_result.chunks
        else:
            # 요약 질의는 최신 업로드 문서 우선 한정 검색을 먼저 시도한다.
            # (전역 top-k에서 최신 문서가 밀려 누락되어 문서 혼입이 생기는 문제 완화)
            recent_doc_chunks: List[Dict[str, Any]] = []
            if is_summary and self._recent_upload_keys:
                recent_doc_chunks = self._search_recent_upload_docs(
                    rewritten_query,
                    top_k=retrieval_top_k,
                )

            if recent_doc_chunks:
                chunks = recent_doc_chunks
                feature_map = self._store.build_feature_map(chunks, rewritten_query)
                logger.info(
                    "[Orchestrator] 요약 최근문서 우선 검색 적용: %d청크",
                    len(chunks),
                )
            else:
                retrieval_result = self._retrieval_agent.retrieve(
                    rewritten_query,
                    top_k=retrieval_top_k,
                )
                feature_map = retrieval_result.feature_map
                chunks      = retrieval_result.chunks

        # ── Step 2b: 요약 질의 문서명 하드 필터 ────────────────────────────────
        hard_doc_token = self._extract_hard_doc_token(user_query) if is_summary else ""
        if hard_doc_token:
            pre_filter_chunks = chunks
            pre_filter_fm = feature_map
            before = len(chunks)
            chunks = self._hard_filter_chunks_by_doc_token(chunks, hard_doc_token)
            # 하드 필터가 과도해 빈 결과가 되면 기존 검색 결과로 롤백
            if not chunks:
                logger.warning(
                    "[Orchestrator] 하드 필터 결과 0청크(token=%r) → 필터 전 결과로 복원",
                    hard_doc_token,
                )
                chunks = pre_filter_chunks
                feature_map = pre_filter_fm
            logger.info(
                "[Orchestrator] 문서 하드 필터 적용(token=%r): %d -> %d청크",
                hard_doc_token, before, len(chunks),
            )
            feature_map = self._store.build_feature_map(chunks, rewritten_query)
        logger.debug("[DEBUG] chunks after hard filter: %d", len(chunks))
        logger.debug("[DEBUG] feature_map contains_pii: %s", feature_map.get("contains_pii"))
        logger.info(
            "[OBS][%s] retrieval chunks=%d contains_pii=%s pii_types=%s ratio=%.4f sens=%.4f bulk=%s",
            req_id,
            len(chunks),
            feature_map.get("contains_pii"),
            feature_map.get("pii_types"),
            float(feature_map.get("pii_chunk_ratio", 0.0) or 0.0),
            float(feature_map.get("sensitivity_score", 0.0) or 0.0),
            feature_map.get("bulk_request"),
        )

        # 요약 + 문서명 지정 질의는 문서 전체 PII 신호를 feature_map에 보강한다.
        # (상위 검색 청크에 PII가 직접 안 잡혀 PRS가 과소평가되는 문제 완화)
        if is_summary:
            doc_key = hard_doc_token or doc_hint
            if doc_key:
                doc_sig = self._store.get_doc_pii_signal(doc_key)
                if doc_sig.get("contains_pii"):
                    summary_doc_contains_pii = True
                    merged_types: List[str] = list(feature_map.get("pii_types") or [])
                    for t in doc_sig.get("pii_types") or []:
                        if t not in merged_types:
                            merged_types.append(t)
                    feature_map["contains_pii"] = True
                    feature_map["pii_types"] = merged_types
                    feature_map["pii_chunk_ratio"] = max(
                        float(feature_map.get("pii_chunk_ratio", 0.0)),
                        float(doc_sig.get("pii_chunk_ratio", 0.0)),
                    )
                    feature_map["sensitivity_score"] = max(
                        float(feature_map.get("sensitivity_score", 0.0)),
                        float(sensitivity_from_protected_types(merged_types)),
                    )
                logger.debug("[DEBUG] doc pii signal(%r): %s", doc_key, doc_sig)

        # 요약 질의에서 "전체"는 요약 범위 지시일 수 있으므로 bulk 오탐을 완화한다.
        # 실제 유출 의도 키워드(출력/원문/dump/export 등)가 없으면 bulk_request를 해제.
        if is_summary and feature_map.get("bulk_request"):
            ql = (user_query or "").lower()
            has_summary_intent = any(k in ql for k in (
                "요약", "정리", "줄거리", "핵심", "3줄", "세줄", "한줄", "summary", "plot",
            ))
            has_exfil_intent = any(k in ql for k in (
                "출력", "보여줘", "원문", "전부", "모두", "dump", "export", "all records", "raw data",
            ))
            if has_summary_intent and not has_exfil_intent:
                feature_map["bulk_request"] = False
                logger.info("[Orchestrator] summary bulk 오탐 완화: bulk_request=False")

        # ── Step 3: 보안 분류 (Qwen 또는 PRS 규칙 기반)
        if config.USE_QWEN and self._qwen is not None and self._qwen.is_available():
            classification = self._qwen.classify_query(user_query, feature_map)
            if not classification.raw_response.strip():
                logger.warning("[Orchestrator] Qwen 빈 응답(타임아웃 추정) → PRS 규칙 폴백")
                classification = classify_by_prs(user_query, feature_map)
        else:
            classification = classify_by_prs(user_query, feature_map)

        label  = classification.label
        reason = classification.reason

        # 요약 질의에서 "개인정보"를 직접 언급하면 최소 SENSITIVE로 승격.
        # (지시형 질의 + 짧은 텍스트에서 PRS가 NORMAL로 떨어지는 케이스 보완)
        if is_summary and "개인정보" in (user_query or "") and label == "NORMAL":
            label = "SENSITIVE"
            reason = "요약 요청에 개인정보 확인 의도가 포함되어 SENSITIVE로 처리합니다."
        # 요약 대상 문서 자체에 보호 PII 신호가 있으면 최소 SENSITIVE를 보장한다.
        if is_summary and summary_doc_contains_pii and label == "NORMAL":
            label = "SENSITIVE"
            reason = "요약 대상 문서에서 보호 개인정보가 감지되어 SENSITIVE로 처리합니다."
        logger.info("[OBS][%s] classify label=%s reason=%r", req_id, label, reason)

        # ── Step 4: 정책 판단 ─────────────────────────────────────────────────
        decision         = self._policy.evaluate(label, feature_map)
        effective_action = self._policy_action(decision, full_view)

        chunk_ids = [c.get("id", 0) for c in chunks]

        # ── Step 5: DANGEROUS 차단 ───────────────────────────────────────────
        if not decision.allow:
            logger.warning("[OBS][%s] early_return policy_blocked", req_id)
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
                summary=SummaryResult(
                    text="",
                    error="policy_blocked: 보안 정책에 의해 요약이 차단되었습니다.",
                ) if is_summary else None,
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
            logger.warning("[OBS][%s] early_return grounding_failed", req_id)
            notice = (
                "검색은 되었으나 질문과 문서의 연관도(Grounding)가 낮아 소스를 표시하지 않았습니다. "
                "줄거리·요약은 문서 속 인물·장소·고유명사를 질문에 포함해 다시 검색해 보세요."
            )
            return QueryResponse(
                answer=notice, label=label, action=effective_action,
                blocked=False, masked_preview=False, reason=reason,
                retrieved_chunk_ids=[], retrieved_chunks=[],
                summary=SummaryResult(
                    text="",
                    error="grounding_failed: 문서 연관도가 낮아 요약할 수 없습니다.",
                ) if is_summary else None,
            )

        # ── Step 6: 요약 요청 시 SummaryAgent ─────────────────────────────────
        summary_result: Optional[SummaryResult] = None
        answer_txt = ""
        display_chunks = chunks
        if is_summary:
            logger.info("[Orchestrator] 요약 요청 감지 → SummaryAgent 호출")
            summary_input = self._filter_chunks_by_query_hint(user_query, chunks)
            if summary_input is chunks:
                summary_input = self._filter_recent_upload_chunks(chunks)
            summary_chunks = self._select_summary_chunks(summary_input)
            display_chunks = summary_chunks or chunks
            # Summary → (output re-scan) → SecurityCritic 승인 mandatory 경로
            summary_result = self._summary_guard.summarize_secure(
                user_query=user_query,
                chunks=summary_chunks,
                feature_map=feature_map,
            )
            if summary_result.is_ok():
                answer_txt = self._enforce_summary_line_hint(summary_result.text, user_query)
                summary_result = SummaryResult(
                    text=answer_txt,
                    used_llm=summary_result.used_llm,
                    regenerated=summary_result.regenerated,
                    map_reduce_used=summary_result.map_reduce_used,
                    source_chunk_count=summary_result.source_chunk_count,
                    error=summary_result.error,
                )

            # 요약 요청에서 소스 문서에 보호 PII가 있으면 최소 SENSITIVE로 상향
            # (질문 문구가 일반적이어도 "확인 필요" 흐름을 강제)
            summary_has_protected_pii = any(
                bool(c.get("has_pii")) or bool(c.get("pii_types"))
                for c in display_chunks
            )
            if summary_has_protected_pii and label == "NORMAL":
                label = "SENSITIVE"
                reason = (
                    "요약 대상 문서에 보호 개인정보가 포함되어 있어 "
                    "확인 후 마스킹 미리보기로 표시합니다."
                )
                decision = self._policy.evaluate(label, feature_map)
                effective_action = self._policy_action(decision, full_view)

        # ── Step 7: 검색 결과 반환 ───────────────────────────────────────────
        masked_preview = bool(label == "SENSITIVE" and decision.masked_preview and not full_view)
        if masked_preview:
            # 민감 요약 경로에서는 PII 태그 청크를 UI에서 기본 마스킹 렌더링한다.
            patched: List[Dict[str, Any]] = []
            for c in display_chunks:
                c2 = dict(c)
                if bool(c2.get("has_pii")) or bool(c2.get("pii_types")):
                    c2["display_masked"] = True
                patched.append(c2)
            display_chunks = patched
        logger.debug("[DEBUG] label before return: %s", label)
        logger.info(
            "[OBS][%s] query_end label=%s action=%s blocked=%s summary_ok=%s",
            req_id, label, effective_action, False,
            bool(summary_result and summary_result.is_ok()),
        )
        return QueryResponse(
            answer=answer_txt, label=label, action=effective_action,
            blocked=False, masked_preview=masked_preview, reason=reason,
            retrieved_chunk_ids=[c.get("id", 0) for c in display_chunks],
            retrieved_chunks=display_chunks,
            summary=summary_result,
        )

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    @staticmethod
    def is_summary_request(user_query: str) -> bool:
        """요약·줄거리 등 요약 의도가 있는지 규칙 기반 판별."""
        q = (user_query or "").strip().lower()
        if not q:
            return False
        keywords = (
            "요약", "정리", "핵심", "간단히", "줄여", "한줄", "한 줄",
            "3줄", "세줄", "요점", "정리해", "요약해", "summarize",
            "줄거리", "스토리", "내용만",
        )
        return any(k in user_query for k in keywords) or any(k in q for k in ("plot", "summary"))

    @staticmethod
    def _calc_sensitivity(pii_types: List[str]) -> float:
        """정책 보호 PII만 반영한 민감도 점수 (0.0 ~ 1.0)."""
        return sensitivity_from_protected_types(pii_types)

    @staticmethod
    def _policy_action(decision: Any, full_view: bool) -> str:
        """UI/로그 표시는 최종 정책 action으로 통일한다."""
        if not decision.allow:
            return "block"
        if decision.require_confirm and not full_view:
            return "confirm"
        return "allow"

    @staticmethod
    def _select_summary_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        요약 품질을 위해 검색 청크를 단일 문서 중심으로 재정렬한다.
        - 여러 문서가 섞여 있으면 가장 많은 청크를 가진 문서를 우선
        - 동률이면 score 합이 높은 문서 우선
        - 선택된 문서 청크는 페이지 순서로 정렬해 줄거리 흐름을 보존
        """
        if not chunks:
            return []
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for c in chunks:
            key = (
                c.get("source_path")
                or c.get("file_name")
                or c.get("doc_name")
                or "__unknown__"
            )
            groups.setdefault(str(key), []).append(c)
        if len(groups) == 1:
            selected = next(iter(groups.values()))
        else:
            ranked = sorted(
                groups.values(),
                key=lambda arr: (
                    len(arr),
                    sum(float(x.get("score") or 0.0) for x in arr),
                ),
                reverse=True,
            )
            selected = ranked[0]
            logger.info(
                "[Orchestrator] 요약 문서 집중: 총 %d문서 중 1문서(%d청크) 선택",
                len(groups),
                len(selected),
            )
        return sorted(
            selected,
            key=lambda c: (
                int(c.get("source_page") or 0),
                int(c.get("chunk_index") or 0),
                int(c.get("start_char") or 0),
            ),
        )

    def _filter_recent_upload_chunks(
        self,
        chunks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        최근 업로드한 문서(source_path/doc_name)와 일치하는 청크만 우선 선택한다.
        일치 청크가 없으면 원본 검색 결과를 그대로 사용한다.
        """
        if not chunks or not self._recent_upload_keys:
            return chunks
        keys = set(self._recent_upload_keys)
        filtered = [
            c for c in chunks
            if (c.get("source_path") in keys)
            or (c.get("doc_name") in keys)
            or (c.get("file_name") in keys)
        ]
        if filtered:
            logger.info(
                "[Orchestrator] 최근 업로드 문서 우선 적용: %d -> %d청크",
                len(chunks),
                len(filtered),
            )
            return filtered
        return chunks

    def _search_recent_upload_docs(
        self,
        query: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """
        최근 업로드 문서 키(source_path/file_name/doc_name)를 이용해 문서 한정 검색한다.
        전역 검색 이전에 적용해 문서 혼입을 줄인다.
        """
        if not self._recent_upload_keys:
            return []

        seen_ids: set[int] = set()
        merged: List[Dict[str, Any]] = []
        for key in self._recent_upload_keys:
            hint = str(key or "").strip()
            if not hint:
                continue
            partial = self._store.search_within_doc(query, doc_name_hint=hint, top_k=top_k)
            for c in partial:
                cid = int(c.get("id") or 0)
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    merged.append(c)
            # 최근 업로드 문서 하나만으로 충분한 경우 과도한 혼합 방지
            if len(merged) >= top_k:
                break

        if not merged:
            return []
        merged.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
        return merged[:top_k]

    @staticmethod
    def _extract_hard_doc_token(user_query: str) -> str:
        """
        요약 질의에서 명시된 문서 토큰을 추출한다.
        예) "홍길동 문서 3줄 요약해줘" -> "홍길동"
        """
        q = (user_query or "").strip()
        if not q:
            return ""
        m = re.search(r"(.{1,80}?)(?:문서|파일)\b", q)
        if m:
            head = m.group(1).strip()
            # 앞부분에서 의미 있는 후보를 추출하되 일반 단어는 제외
            words = re.findall(r"[0-9A-Za-z가-힣._-]{2,}", head)
            stop = {"개인정보", "요약", "정리", "핵심", "문서", "파일"}
            candidates = [w for w in words if w not in stop]
            if candidates:
                return candidates[0].strip()
            if words:
                return words[0].strip()
        m2 = re.search(
            r"([0-9A-Za-z가-힣._-]{2,}\.(?:pdf|hwpx|png|jpg|jpeg|heic|webp))",
            q,
            re.IGNORECASE,
        )
        if m2:
            return m2.group(1).strip()
        return ""

    @staticmethod
    def _hard_filter_chunks_by_doc_token(
        chunks: List[Dict[str, Any]],
        token: str,
    ) -> List[Dict[str, Any]]:
        """
        문서 토큰 기준으로 요약 후보를 강제 필터링한다.
        1) 메타(file/doc/path) 매칭 우선
        2) 실패 시 본문 텍스트 매칭으로 폴백
        """
        if not chunks or not token:
            return chunks
        tok = re.sub(r"[^0-9A-Za-z가-힣]", "", token).lower()
        if len(tok) < 2:
            return chunks

        def _norm(v: Any) -> str:
            return re.sub(r"[^0-9A-Za-z가-힣]", "", str(v or "")).lower()

        meta_hits: List[Dict[str, Any]] = []
        for c in chunks:
            blob = " ".join([
                str(c.get("file_name") or ""),
                str(c.get("doc_name") or ""),
                str(c.get("source_path") or ""),
            ])
            if tok in _norm(blob):
                meta_hits.append(c)
        if meta_hits:
            return meta_hits

        text_hits = [c for c in chunks if tok in _norm(c.get("text") or "")]
        return text_hits

    @staticmethod
    def _enforce_summary_line_hint(text: str, user_query: str) -> str:
        """
        사용자 질의의 'N줄 요약' 힌트를 결과에도 강제한다.
        현재는 2~5줄 범위만 허용하고, 기본 3줄 요청을 우선 지원한다.
        """
        if not text or not text.strip():
            return text
        m = re.search(r"([2-5])\s*줄", user_query or "")
        if not m:
            return text
        wanted = int(m.group(1))
        lines = [l for l in str(text).splitlines() if l.strip()]
        if len(lines) <= wanted:
            return "\n".join(lines)
        return "\n".join(lines[:wanted])

    # ── 관리자용 인덱스 관리 API ───────────────────────────────────────────────

    def list_indexed_documents(self) -> List[Dict[str, Any]]:
        """관리자 UI에 표시할 인덱스 문서 목록을 반환한다."""
        return self._store.list_indexed_documents()

    def delete_indexed_documents(self, doc_names: List[str]) -> Dict[str, Any]:
        """
        선택된 문서를 벡터 인덱스/메타DB에서 삭제한다.
        원본 파일은 삭제하지 않는다.
        """
        result = self._store.delete_documents(doc_names)
        self._recent_upload_keys = self._store.get_recent_upload_keys()
        return result

    @staticmethod
    def _extract_doc_hint(user_query: str, doc_names: List[str]) -> str:
        """
        DB에 저장된 문서명 목록과 질문을 비교해 가장 잘 매칭되는 문서명을 반환한다.
        매칭 없으면 빈 문자열을 반환한다.

        예) user_query="AI 브리프 자료 요약해줘", doc_names=["AI브리프_3월.pdf", "역사.pdf"]
            → "AI브리프_3월.pdf"
        """
        if not user_query or not doc_names:
            return ""
        q_norm = re.sub(r"[^0-9A-Za-z가-힣]", "", user_query).lower()
        best_doc, best_score = "", 0
        for name in doc_names:
            n_norm = re.sub(r"[^0-9A-Za-z가-힣]", "", name).lower()
            if not n_norm:
                continue
            # 공통 부분 문자열 길이로 점수 계산 (짧은 쪽 기준 비율)
            shorter = min(len(q_norm), len(n_norm))
            overlap = sum(
                1 for ch in set(n_norm) if ch in q_norm
            )
            # 파일명에서 핵심 단어(4자 이상) 추출해 질문 포함 여부 확인
            words = re.findall(r"[가-힣A-Za-z0-9]{2,}", name)
            word_hits = sum(
                1 for w in words
                if len(w) >= 2
                and re.sub(r"[^0-9A-Za-z가-힣]", "", w).lower() in q_norm
            )
            score = overlap + word_hits * 3
            if score > best_score:
                best_score = score
                best_doc = name
        # 최소 점수 미만이면 힌트 없음으로 처리
        if best_score < 3:
            return ""
        logger.info("[Orchestrator] doc_hint 감지: %r (score=%d)", best_doc, best_score)
        return best_doc

    @staticmethod
    def _filter_chunks_by_query_hint(
        user_query: str,
        chunks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        질문에 특정 문서명이 들어있으면 해당 문서 청크를 우선 선택한다.
        예) 'AI 브리프 자료 요약' -> file_name/doc_name/source_path 내 'ai브리프' 매칭.
        매칭이 없으면 원본 리스트를 그대로 반환한다.
        """
        if not user_query or not chunks:
            return chunks
        # 공백/특수문자 제거해 느슨하게 비교
        q_norm = re.sub(r"[^0-9A-Za-z가-힣]", "", user_query).lower()
        if len(q_norm) < 2:
            return chunks
        out: List[Dict[str, Any]] = []
        for c in chunks:
            blob = " ".join([
                str(c.get("file_name") or ""),
                str(c.get("doc_name") or ""),
                str(c.get("source_path") or ""),
            ])
            b_norm = re.sub(r"[^0-9A-Za-z가-힣]", "", blob).lower()
            if not b_norm:
                continue
            # 완전 포함 + 앞 4글자 단서 포함 둘 다 허용
            if b_norm in q_norm or q_norm in b_norm or q_norm[:4] in b_norm:
                out.append(c)
        if out:
            logger.info(
                "[Orchestrator] 질문 문서명 힌트 매칭 적용: %d -> %d청크",
                len(chunks),
                len(out),
            )
            return out
        return chunks
