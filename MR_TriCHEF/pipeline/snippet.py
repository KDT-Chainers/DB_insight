"""snippet.py — 검색 결과 preview 추출.

질의 토큰과 overlap이 최대인 문장 구간을 원문에서 선택.
PROJECT_PIPELINE_SPEC.md §10 알고리즘을 MR_TriCHEF 파이프라인용으로 이식.

사용:
    from .snippet import extract_best_snippet
    preview = extract_best_snippet(stt_text, query)
"""
from __future__ import annotations

import re


def extract_best_snippet(text: str, query: str, window_size: int = 220) -> str:
    """질의 토큰과 overlap이 최대인 문장 구간 추출.

    Args:
        text:        원문 텍스트 (STT 결과, 문서 본문, caption 등)
        query:       검색 질의
        window_size: 반환 최대 글자 수 (기본 220자)

    Returns:
        질의와 가장 관련 있는 원문 구간.
        질의 복붙이 아닌 원문 기반 구간만 반환.
        overlap이 없으면 원문 앞부분 반환.
    """
    text = text.strip()
    if not text:
        return ""

    # 문장 분리: 마침표/느낌표/물음표 뒤 공백, 또는 줄바꿈
    sentences = re.split(r"(?<=[.!?。])\s+|\n+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return text[:window_size]

    q_tokens = set(query.lower().split())
    best_sent = sentences[0]
    best_count = -1

    for sent in sentences:
        count = sum(1 for tok in sent.lower().split() if tok in q_tokens)
        if count > best_count:
            best_count = count
            best_sent = sent

    # 질의 토큰 overlap이 전혀 없으면 앞부분 반환
    if best_count == 0:
        return text[:window_size]
    return best_sent[:window_size]
