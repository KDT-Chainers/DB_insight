"""검색 결과 재순위(BGE-reranker-v2-m3) 어댑터.

`shared/reranker.py` 의 cross-encoder 모델을 GPU(RTX 4070 Laptop, bf16) 에 1회
로드한 뒤 /api/search 결과를 query-passage 적합도 순으로 재정렬한다.

설계 원칙:
- 환경변수 `TRICHEF_USE_RERANKER` 가 truthy 일 때만 활성화 (기본 OFF, 안전).
- 신규 파일 1개 — 기존 검색 로직 변경 없이 결과 dict 만 재정렬.
- 실패 시 무음 (원본 results 반환) — 검색 자체는 절대 실패시키지 않음.
- 모델 싱글턴 — `get_reranker()` 가 프로세스 전역 캐시.

GPU 우선 — `shared/reranker.py:47` 가 `torch.cuda.is_available()` 자동 감지.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    """env var truthy 검사. '1', 'true', 'yes', 'on' 모두 허용."""
    v = os.environ.get("TRICHEF_USE_RERANKER", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _ensure_shared_on_path() -> None:
    """프로젝트 루트(= App 의 부모) 를 sys.path 에 추가하여
    `from shared.reranker import ...` 임포트를 가능하게 한다.
    """
    # services/rerank_adapter.py → backend → App → project_root
    project_root = Path(__file__).resolve().parents[3]
    p = str(project_root)
    if p not in sys.path:
        sys.path.insert(0, p)


def _passage_for(result: dict) -> str:
    """결과 dict 1개에서 reranker 입력 텍스트(passage) 생성.

    우선순위:
    1) snippet (이미지·문서 캡션 / AV 스니펫)
    2) segments[0].text 또는 .caption (AV 도메인 보조)
    3) file_name (최후 fallback)

    상한 800자 — 모델 max_length 512 토큰 ≈ 한국어 800자 수준에 매핑.
    """
    snippet = (result.get("snippet") or "").strip()
    if snippet:
        return snippet[:800]
    segs = result.get("segments") or []
    if segs:
        first = segs[0] if isinstance(segs[0], dict) else {}
        txt = first.get("text") or first.get("caption") or first.get("preview") or ""
        if txt:
            return str(txt)[:800]
    return str(result.get("file_name") or result.get("file_path") or "")[:800]


def maybe_rerank(query: str, results: list[dict],
                 top_k_pool: int | None = None) -> list[dict]:
    """env-flag 활성 시 results 를 cross-encoder 점수로 재정렬.

    Args:
        query: 사용자 쿼리.
        results: /api/search 가 빌드한 결과 dict 리스트
                 (file_path, file_name, snippet, confidence, ... 포함).
        top_k_pool: 재순위 대상 상위 N개 (None=전체). 기본 50 으로 비용 캡.

    Returns:
        재정렬된 새 리스트(원본 dict 에 'rerank_score' 키만 추가).
        비활성/실패/빈 입력이면 원본 그대로 반환.
    """
    if not _is_enabled():
        return results
    if not results:
        return results

    pool = top_k_pool if top_k_pool is not None else 50
    head = results[:pool]
    tail = results[pool:]

    try:
        _ensure_shared_on_path()
        from shared.reranker import get_reranker
        rr = get_reranker()
        passages = [_passage_for(r) for r in head]
        scores = rr.score(query, passages)
        for r, s in zip(head, scores):
            s = float(s)
            r["rerank_score"] = s
            # [v3 — soft-cap]
            #   기존(v2)의 min(prev, sigmoid(s)) 하드 캡은 cross-encoder logit 이
            #   -5 ~ -10 인 흔한 케이스(짧은 AV passage, 한국어 미세조정 부족)에서
            #   sigmoid≈0.001~0.0001 로 떨어져 dense=0.99 의 양질 결과까지 conf 0%
            #   로 만들어 5% 자동 숨김에 모두 걸리는 부작용을 일으켰다.
            #   이제 rerank_score 는 "정렬 신호" 로만 쓰고 confidence 는 dense z-score
            #   기반 값을 보존한다. 다만 강한 부정(s < -3) 인 경우 50% 디스카운트만
            #   적용해 사용자에게 약한 신호를 주는 정도로 그친다.
            prev = float(r.get("confidence") or 0.0)
            if s < -3.0:
                # 강한 부정: 절반으로만 깎음 (0 으로 절멸시키지 않음)
                r["confidence"] = round(prev * 0.5, 4)
            # else: confidence 그대로 유지
        head = sorted(head, key=lambda r: r.get("rerank_score", -1e9), reverse=True)
        return head + tail
    except Exception as e:
        logger.exception(f"[rerank_adapter] 재순위 실패, 원본 반환: {e}")
        return results
