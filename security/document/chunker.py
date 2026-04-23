"""
chunker.py
──────────────────────────────────────────────────────────────────────────────
페이지/섹션 텍스트를 고정 크기 청크로 분할.

- CHUNK_SIZE: 최대 글자 수 (config.CHUNK_SIZE)
- CHUNK_OVERLAP: 청크 간 중복 글자 수 (config.CHUNK_OVERLAP)

각 청크에 메타데이터(출처 페이지, 청크 인덱스) 부착.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import config


@dataclass
class Chunk:
    """텍스트 청크 하나"""
    index: int                          # 문서 전체 기준 청크 번호
    text: str                           # 본문
    source_page: int                    # 원본 페이지/섹션 번호 (1-indexed)
    start_char: int                     # 페이지 내 시작 위치
    end_char: int                       # 페이지 내 끝 위치
    doc_name: str = ""                  # 문서 파일명 (표시용)
    source_path: str = ""              # 원본 파일 절대 경로 (뷰어용, 파일 미수정)
    bbox: Optional[Dict[str, Any]] = None  # 페이지 내 위치 {x, y, w, h}; 추출 불가 시 None


def chunk_pages(
    pages: List[Tuple[int, str]],
    doc_name: str = "",
    source_path: str = "",
    chunk_size: int = config.CHUNK_SIZE,
    overlap: int = config.CHUNK_OVERLAP,
) -> List[Chunk]:
    """
    페이지(또는 섹션) 목록을 청크로 분할.

    Args:
        pages:       [(page_num, text), ...] — pdf_extractor / hwpx_extractor 출력
        doc_name:    문서 파일명 (표시용 메타데이터)
        source_path: 원본 파일 절대 경로 (뷰어용; 파일을 수정하지 않음)
        chunk_size:  청크 최대 글자 수
        overlap:     청크 간 중복 글자 수

    Returns:
        List[Chunk]
    """
    chunks: List[Chunk] = []
    global_idx = 0

    for page_num, text in pages:
        if not text.strip():
            continue

        # 페이지를 chunk_size 단위로 분할
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk_text = text[start:end].strip()

            if chunk_text:
                chunks.append(Chunk(
                    index=global_idx,
                    text=chunk_text,
                    source_page=page_num,
                    start_char=start,
                    end_char=end,
                    doc_name=doc_name,
                    source_path=source_path,
                ))
                global_idx += 1

            # 다음 청크 시작 위치 (overlap 만큼 뒤로 당겨서 시작)
            next_start = end - overlap
            if next_start <= start:
                next_start = start + 1  # 무한 루프 방지
            start = next_start

    return chunks


def chunks_to_texts(chunks: List[Chunk]) -> List[str]:
    """청크 리스트에서 텍스트만 추출 (임베딩 입력용)"""
    return [c.text for c in chunks]
