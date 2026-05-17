"""[P3] 재사용 가능한 한국어/혼합 텍스트 슬라이딩 청커.

기능:
  - 1000자 청크 + 200자 오버랩 (기본값, 조정 가능)
  - 단어/문장 경계 우선 분할 (마침표·줄바꿈 가까운 위치로 청크 끝 조정)
  - 짧은 텍스트는 단일 청크로 반환 (최소 청크 크기 미만 X)

사용처:
  - 긴 페이지(>1500자) 의 BGE-M3 토큰 잘림 손실 회복용
    → 청크별 임베딩 → 평균 풀링 → 페이지 단위 벡터로 환원
  - 향후 문서 검색 청크 단위 인덱스 전환 시 동일 청커 사용 (호환성)
"""
from __future__ import annotations

import re
from typing import Iterator


# 청크 끝 조정 시 우선시할 경계 문자 (마침표/물음표/느낌표/줄바꿈/한국어 종결)
_SENTENCE_END_CHARS = ".!?。！？\n"
_WORD_BOUNDARY_RE = re.compile(r"\s")


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
    *,
    min_chunk: int = 100,
    boundary_lookback: int = 100,
) -> list[str]:
    """텍스트를 슬라이딩 청크로 분할.

    Args:
        text: 원본 텍스트
        chunk_size: 목표 청크 크기 (문자 수)
        overlap: 인접 청크 간 오버랩 (문자 수)
        min_chunk: 마지막 청크의 최소 크기 (이보다 작으면 직전 청크에 합침)
        boundary_lookback: 청크 끝 조정 시 뒤로 탐색할 최대 글자 수
                          (단어/문장 경계 찾기용)

    Returns:
        청크 문자열 리스트 (텍스트가 chunk_size 이하면 [text] 1개)
    """
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError(
            f"잘못된 파라미터: chunk_size={chunk_size}, overlap={overlap}"
        )

    chunks: list[str] = []
    pos = 0
    n = len(text)
    step = chunk_size - overlap

    while pos < n:
        end = min(pos + chunk_size, n)
        # 마지막 청크가 아닐 때만 경계 조정
        if end < n:
            adj_end = _adjust_to_boundary(text, end, boundary_lookback)
            if adj_end > pos + chunk_size // 2:  # 너무 앞으로 가지 않도록 안전장치
                end = adj_end
        chunk = text[pos:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        pos = end - overlap if end - overlap > pos else pos + step

    # 마지막 청크가 너무 짧으면 직전과 합침
    if len(chunks) >= 2 and len(chunks[-1]) < min_chunk:
        merged = chunks[-2] + " " + chunks[-1]
        chunks = chunks[:-2] + [merged]

    return chunks


def _adjust_to_boundary(text: str, target: int, lookback: int) -> int:
    """target 위치에서 뒤로 lookback 만큼 탐색하여 가까운 문장/단어 경계 반환.

    우선순위: 문장 종결 (.!? 등) > 공백 > target 그대로.
    """
    lo = max(0, target - lookback)
    # 1) 문장 종결 문자 탐색 (뒤에서 앞으로)
    for i in range(target - 1, lo - 1, -1):
        if text[i] in _SENTENCE_END_CHARS:
            return i + 1  # 종결 문자 포함, 다음부터 새 청크
    # 2) 공백 (단어 경계) 탐색
    for i in range(target - 1, lo - 1, -1):
        if _WORD_BOUNDARY_RE.match(text[i]):
            return i + 1
    # 3) 경계 없음 — 원래 target 사용 (다른 한국어 문자 안에서 자름)
    return target


def chunk_iter(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
) -> Iterator[tuple[int, str]]:
    """청크를 (index, chunk_text) 튜플로 yield."""
    for i, c in enumerate(chunk_text(text, chunk_size, overlap)):
        yield i, c


def chunk_stats(text: str, chunk_size: int = 1000, overlap: int = 200) -> dict:
    """디버깅용 — 청크 통계."""
    chunks = chunk_text(text, chunk_size, overlap)
    if not chunks:
        return {"n_chunks": 0, "total_chars": 0, "avg_len": 0, "min_len": 0, "max_len": 0}
    lens = [len(c) for c in chunks]
    return {
        "n_chunks": len(chunks),
        "total_chars": sum(lens),
        "avg_len": sum(lens) / len(lens),
        "min_len": min(lens),
        "max_len": max(lens),
        "input_chars": len(text),
    }
