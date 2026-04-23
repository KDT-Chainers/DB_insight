"""
vectordb/secure_gateway.py
──────────────────────────────────────────────────────────────────────────────
[DEPRECATED] 보안 게이트웨이 — 사용되지 않음

v2 단일 인덱스 구조로 전환 후 이 모듈은 더 이상 사용되지 않는다.

이전 역할:
  - secure_index(원본 청크)에 대한 HMAC 토큰 기반 접근 제어
  - public_index(마스킹) / meta_index / secure_index 3단계 인덱스 구조

v2 변경 사유:
  - 마스킹 임베딩은 검색 품질을 크게 저하시킨다
  - 원문을 단일 인덱스에 저장하고 UI에서만 마스킹 표시하는 방식으로 변경
  - meta_index와 secure_index가 불필요해짐
  - Grounding Gate의 "meta_hits" 우회 로직도 제거됨

이 파일은 히스토리 보존을 위해 유지하지만 import되어서는 안 된다.
"""

raise ImportError(
    "secure_gateway는 v2에서 제거되었습니다. "
    "단일 VectorStore(vectordb/store.py)를 사용하세요."
)
