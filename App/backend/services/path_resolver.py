"""Registry entry → 현재 PC abs 경로 동적 결합.

다른 PC 호환성:
  registry.json 안의 'abs' / 'abs_aliases' 필드는 인덱싱한 PC 의 절대경로라
  다른 PC 에서 git pull 후 그대로 사용하면 깨진다. 모든 검색/파일 조작
  결과는 현재 PC 의 RAW_DB 경로 + rel_key (registry key) 로 매번 결합한다.

  RAW_DB 는 config.py 가 환경변수 DB_INSIGHT_DATA 또는 repo 기준
  parents[N]/Data 로 동적 결정하므로 PC 별로 자동 적응.

사용 예:
    from services.path_resolver import resolve_raw_path
    abs_path = resolve_raw_path(rel_key, "image")
    abs_path = resolve_raw_path(rel_key, "doc", reg_entry=info)
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional


# domain 라벨 → raw_DB 하위 디렉토리
# (search.py / registry_lookup.py 와 매핑 통일)
_DOMAIN_DIR = {
    "image": "Img",
    "doc":   "Doc",
    "video": "Movie",
    "audio": "Rec",
    "bgm":   "Movie",   # BGM 은 Movie 폴더 내 일부 음원
}


def resolve_raw_path(rel_key: str, domain: str,
                     reg_entry: Optional[dict] = None) -> str:
    """rel_key + 현재 PC RAW_DB → 절대경로 동적 결합.

    Args:
        rel_key:   registry key (상대경로, 예: 'YS_1차/file.jpg')
        domain:    'image' | 'doc' | 'video' | 'audio' | 'bgm'
        reg_entry: registry entry dict — rel_key 가 없을 때 'staged'
                   필드를 fallback 으로 사용 (입력 stash 케이스).

    Returns:
        현재 PC 의 절대경로 문자열. 매핑 실패 시 빈 문자열.
    """
    if rel_key:
        domain_dir = _DOMAIN_DIR.get(domain, "")
        if domain_dir:
            try:
                from config import RAW_DB
                return str(RAW_DB / domain_dir / rel_key)
            except Exception:
                return ""
    if isinstance(reg_entry, dict):
        return reg_entry.get("staged", "") or ""
    return ""


def find_rel_key_by_stem(stem: str, registry: dict) -> Optional[tuple[str, dict]]:
    """stem (파일명에서 확장자 제거) 기준으로 registry 에서 매칭 entry 찾기.

    - 신포맷 hash 포함 / 구포맷 단순 stem 모두 시도
    - 'abs' / 'abs_aliases' 필드가 PC 별이라 stem 만 비교

    Returns:
        (rel_key, entry) 또는 None
    """
    if not stem or not isinstance(registry, dict):
        return None
    for rel_key, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        rel_stem = Path(rel_key).stem
        if rel_stem == stem:
            return rel_key, entry
    return None
