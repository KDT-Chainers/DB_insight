"""
agents/upload_security.py
──────────────────────────────────────────────────────────────────────────────
업로드 보안 에이전트.

ABC 권한: [A] 신뢰불가 입력(업로드 파일) 처리
금지:     [B] DB 직접 접근  /  [C] 외부 통신 또는 상태 변경

역할:
  1. 파일 유효성 검사 (확장자, 크기)
  2. 텍스트 추출 (PDF / HWPX / 이미지)
  3. 이미지 파일: 영구 복사 + OCR bbox 캡처
  4. 청킹
  5. PII 탐지 (정규식 + Qwen 재검증)
  6. 이미지 PII → 이미지 bbox 좌표 매핑
  7. 탐지 결과 반환 (임베딩 결정은 Orchestrator 가 함)
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
from document.chunker import Chunk, chunk_pages
from document.hwpx_extractor import extract_hwpx_with_metadata
from document.image_extractor import (
    IMAGE_EXTENSIONS,
    extract_image_with_regions,
    map_pii_to_image_regions,
)
from document.pdf_extractor import extract_pdf_with_metadata
from harness.safe_tools import CAP_A, enforce_abc, validate_upload_file
from security.pii_detector import ChunkScanResult, PIIDetector

logger = logging.getLogger(__name__)


@dataclass
class UploadScanResult:
    """업로드 보안 스캔 전체 결과"""
    filename: str
    chunks: List[Chunk] = field(default_factory=list)
    scan_results: List[ChunkScanResult] = field(default_factory=list)
    has_pii: bool = False
    pii_summary: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    # ── 이미지 전용 ──────────────────────────────────────────────────────────
    is_image: bool = False
    image_path: str = ""          # 영구 저장된 이미지 경로 (IMAGE_STORE_DIR)
    image_pii_regions: List[List] = field(default_factory=list)
    # OCR 결과 (bbox, text, conf) — image_pii_regions 재계산용 임시 보관
    _ocr_results: List[Tuple] = field(default_factory=list, repr=False)


class UploadSecurityAgent:
    """
    파일을 받아 텍스트 추출 + PII 탐지까지 수행.

    ABC 원칙:
      capabilities = {CAP_A}  →  A 만 보유
      DB 접근·외부 API 직접 호출 금지
    """

    CAPABILITIES = {CAP_A}

    def __init__(self, pii_detector: Optional[PIIDetector] = None) -> None:
        enforce_abc("UploadSecurityAgent", self.CAPABILITIES)
        self._detector = pii_detector or PIIDetector()

    # ── 공개 API ───────────────────────────────────────────────────────────────

    def scan_file(self, file_path: str | Path) -> UploadScanResult:
        """
        파일 업로드 전 보안 스캔 진입점.

        Args:
            file_path: 업로드된 파일 경로

        Returns:
            UploadScanResult (청크 + PII 탐지 + 이미지 bbox)
        """
        try:
            resolved = validate_upload_file(file_path)
        except (ValueError, FileNotFoundError) as exc:
            return UploadScanResult(filename=str(file_path), error=str(exc))

        filename    = resolved.name
        ext         = resolved.suffix.lower()
        source_path = str(resolved)

        # ── 1. 텍스트 추출 ────────────────────────────────────────────────────
        ocr_results: List[Tuple] = []
        persistent_image_path: str = ""

        try:
            if ext == ".pdf":
                meta_pages = extract_pdf_with_metadata(resolved)
                pages = [(m["page_number"], m["text"]) for m in meta_pages]

            elif ext == ".hwpx":
                meta_pages = extract_hwpx_with_metadata(resolved)
                pages = [(m["page_number"], m["text"]) for m in meta_pages]

            elif ext in IMAGE_EXTENSIONS:
                img_data = extract_image_with_regions(resolved)
                pages       = [(img_data["page_number"], img_data["text"])]
                ocr_results = img_data["ocr_results"]

                # 이미지를 영구 저장소로 복사 (Gradio 임시 파일 소멸 방지)
                persistent_image_path = self._persist_image(resolved)

            else:
                return UploadScanResult(
                    filename=filename,
                    error=f"지원하지 않는 파일 형식: {ext}",
                )

        except Exception as exc:
            logger.error("텍스트 추출 실패: %s", exc)
            return UploadScanResult(filename=filename, error=f"텍스트 추출 오류: {exc}")

        # ── 2. 청킹 ──────────────────────────────────────────────────────────
        chunks = chunk_pages(pages, doc_name=filename, source_path=source_path)

        if not chunks:
            return UploadScanResult(
                filename=filename,
                chunks=[],
                has_pii=False,
                pii_summary={"message": "추출된 텍스트 없음"},
                is_image=(ext in IMAGE_EXTENSIONS),
                image_path=persistent_image_path,
            )

        # ── 3. PII 탐지 ───────────────────────────────────────────────────────
        chunk_texts  = [c.text for c in chunks]
        scan_results = self._detector.scan_chunks(chunk_texts)

        # ── 4. 이미지: PII → bbox 매핑 ────────────────────────────────────────
        image_pii_regions: List[List] = []
        if ext in IMAGE_EXTENSIONS and ocr_results:
            # 모든 청크의 PII findings 수집 (이미지는 보통 1청크)
            all_findings = []
            for sr in scan_results:
                all_findings.extend(sr.findings)
            image_pii_regions = map_pii_to_image_regions(ocr_results, all_findings)
            logger.info(
                "이미지 PII 영역 %d개 감지: %s", len(image_pii_regions), filename
            )

        # ── 5. 요약 ───────────────────────────────────────────────────────────
        has_pii    = any(r.has_pii for r in scan_results)
        pii_summary = self._build_pii_summary(scan_results)

        return UploadScanResult(
            filename=filename,
            chunks=chunks,
            scan_results=scan_results,
            has_pii=has_pii,
            pii_summary=pii_summary,
            is_image=(ext in IMAGE_EXTENSIONS),
            image_path=persistent_image_path,
            image_pii_regions=image_pii_regions,
            _ocr_results=ocr_results,
        )

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _persist_image(src: Path) -> str:
        """
        업로드 이미지를 IMAGE_STORE_DIR 에 영구 복사한다.
        같은 내용의 파일이 이미 있으면 재사용 (SHA-256 기반 중복 제거).

        Returns:
            영구 경로 문자열 (복사 실패 시 원본 경로 반환)
        """
        try:
            data = src.read_bytes()
            file_hash = hashlib.sha256(data).hexdigest()[:16]
            dest = config.IMAGE_STORE_DIR / f"{file_hash}_{src.name}"
            if not dest.exists():
                shutil.copy2(src, dest)
                logger.info("이미지 영구 저장: %s → %s", src.name, dest)
            return str(dest)
        except Exception as exc:
            logger.warning("이미지 영구 저장 실패 (원본 경로 사용): %s", exc)
            return str(src)

    @staticmethod
    def _build_pii_summary(scan_results: List[ChunkScanResult]) -> Dict[str, Any]:
        """탐지된 PII 유형과 청크 수를 요약"""
        type_counts: Dict[str, int] = {}
        affected_chunks = 0

        for result in scan_results:
            if result.has_pii:
                affected_chunks += 1
                for pii_type in result.pii_types:
                    type_counts[pii_type] = type_counts.get(pii_type, 0) + 1

        return {
            "total_chunks":    len(scan_results),
            "affected_chunks": affected_chunks,
            "pii_type_counts": type_counts,
        }
