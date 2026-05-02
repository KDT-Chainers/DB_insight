"""4개 도메인(Doc/Img/Movie/Rec) registry.json 의 빠른 조회 서비스.

인덱싱 UI 가 폴더 트리를 펼칠 때 각 파일이 이미 임베딩되어 있는지 확인하기
위한 경량 lookup. mtime 기반 lazy reload 로 registry.json 변경을 자동 반영한다.
"""
from __future__ import annotations
from pathlib import Path
import json
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# 파일 경로 기준: .../App/backend/services/registry_lookup.py
# → 3 단계 위 == DB_insight 루트 → Data/embedded_DB
_EMBEDDED_DB_ROOT = Path(__file__).resolve().parents[3] / "Data" / "embedded_DB"

# registry.json 디렉토리 이름 → /api/files/stats by_type 키와 통일
_DOMAIN_LABEL = {
    "Doc":   "doc",
    "Img":   "image",
    "Movie": "video",
    "Rec":   "audio",
}

_reg_cache: Dict[str, dict] = {}
_reg_mtime: Dict[str, float] = {}
_abs_index_cache: Dict[str, str] = {}
_abs_index_built_at: float = -1.0
# [#10] size 보조 인덱스 — abs 매칭 실패 시 fallback.
# (size_bytes, basename_lower) → (domain_label, abs_path)
_size_index_cache: Dict[tuple, tuple] = {}
# [#13] rel-key 인덱스 — Movie/Rec registry 처럼 abs 필드 없이 relative key 만
# 저장되는 도메인을 위한 매칭. (norm_rel_path → domain_label).
_relkey_index_cache: Dict[str, str] = {}

# raw_DB 루트 — registry key(상대경로) ↔ 입력 절대경로 매핑용.
_RAW_DB_ROOT = Path(__file__).resolve().parents[3] / "Data" / "raw_DB"


def _registry_path(domain: str) -> Path:
    return _EMBEDDED_DB_ROOT / domain / "registry.json"


def _load_one(domain: str) -> dict:
    """mtime 변화 시에만 다시 읽음."""
    path = _registry_path(domain)
    if not path.exists():
        _reg_cache[domain] = {}
        _reg_mtime[domain] = 0.0
        return _reg_cache[domain]

    mtime = path.stat().st_mtime
    if _reg_mtime.get(domain, -1.0) != mtime:
        try:
            _reg_cache[domain] = json.loads(path.read_text(encoding="utf-8"))
            _reg_mtime[domain] = mtime
        except Exception as e:
            logger.warning(f"[registry_lookup] {domain}/registry.json 로드 실패: {e}")
            _reg_cache[domain] = {}
            _reg_mtime[domain] = mtime
    return _reg_cache[domain]


def _norm(p: str) -> str:
    """Windows 호환 경로 정규화 — 비교용 키."""
    if not p:
        return ""
    try:
        return str(Path(p).resolve()).lower().replace("\\", "/")
    except Exception:
        return p.lower().replace("\\", "/")


def _max_mtime() -> float:
    m = 0.0
    for d in _DOMAIN_LABEL:
        path = _registry_path(d)
        if path.exists():
            m = max(m, path.stat().st_mtime)
    return m


def _rebuild_abs_index() -> None:
    """4중 인덱스 구축: abs / size+basename / rel-key / alias.

    [#10] 보조 인덱스 (size, basename) — abs 정규화 차이 보완.
    [#13] rel-key 인덱스 — Movie/Rec 처럼 abs 필드 없이 relative key 만 있는 경우.
    [#15] alias 인덱스 — SHA-dedup 으로 등록 skip 된 phantom 파일 매핑.
          incremental_runner 가 SHA-skip 시 entry["abs_aliases"] 에 새 abs 추가.
    """
    global _abs_index_cache, _abs_index_built_at, _size_index_cache, _relkey_index_cache
    new_abs: Dict[str, str] = {}
    new_size: Dict[tuple, tuple] = {}
    new_rel: Dict[str, str] = {}
    for dom, label in _DOMAIN_LABEL.items():
        reg = _load_one(dom)
        for key, entry in reg.items():
            if not isinstance(entry, dict):
                continue
            # 1차: abs 인덱스
            abs_path = entry.get("abs")
            if abs_path:
                norm_key = _norm(abs_path)
                if norm_key:
                    new_abs[norm_key] = label
                # 2차: size+basename 보조 (디스크 존재 시)
                try:
                    p = Path(abs_path)
                    if p.is_file():
                        sz = p.stat().st_size
                        new_size[(sz, p.name.lower())] = (label, abs_path)
                except Exception:
                    pass
            # [#15] alias 인덱스 — abs_aliases (list of str)
            aliases = entry.get("abs_aliases") or []
            if isinstance(aliases, list):
                for a_path in aliases:
                    if not a_path:
                        continue
                    a_norm = _norm(a_path)
                    if a_norm:
                        new_abs[a_norm] = label
                    try:
                        ap = Path(a_path)
                        if ap.is_file():
                            sz = ap.stat().st_size
                            new_size[(sz, ap.name.lower())] = (label, a_path)
                    except Exception:
                        pass
            # 3차: rel-key 인덱스 — registry key 가 raw_DB/<domain>/ 하위 상대경로일 때.
            # Movie/Rec 는 abs 미저장이므로 이 경로로만 매칭됨.
            try:
                rel_norm = _norm(str(_RAW_DB_ROOT / dom / key))
                if rel_norm:
                    new_rel[rel_norm] = label
            except Exception:
                pass
    _abs_index_cache = new_abs
    _size_index_cache = new_size
    _relkey_index_cache = new_rel
    _abs_index_built_at = _max_mtime()


def _ensure_fresh_index() -> None:
    if _max_mtime() != _abs_index_built_at:
        _rebuild_abs_index()


def lookup(paths: list[str]) -> Dict[str, dict]:
    """입력 절대경로 리스트 → {원본경로: {indexed, domain}}.

    매칭 우선순위:
      1. abs 정규화 일치 (가장 확실, Doc/Img)
      2. rel-key 일치 (Movie/Rec — abs 미저장 도메인 핵심)
      3. (size, basename) 일치 (path 정규화 차이 보완)
    """
    if not paths:
        return {}
    _ensure_fresh_index()
    result: Dict[str, dict] = {}
    for p in paths:
        norm = _norm(p)
        # 1차: abs 정규화
        domain = _abs_index_cache.get(norm)
        # 2차: rel-key (Movie/Rec) — registry key 가 raw_DB/<domain>/ 하위 상대경로
        if domain is None:
            domain = _relkey_index_cache.get(norm)
        # 3차: (size, basename) 보조
        if domain is None:
            try:
                pp = Path(p)
                if pp.is_file():
                    key = (pp.stat().st_size, pp.name.lower())
                    hit = _size_index_cache.get(key)
                    if hit is not None:
                        domain = hit[0]
            except Exception:
                pass
        result[p] = {"indexed": domain is not None, "domain": domain}
    return result


def orphans_under(folder_path: str) -> list[dict]:
    """폴더 하위에 등록되었으나 실제 파일이 사라진 항목 목록.

    "임베딩 후 사용자가 raw_DB 파일을 임의 삭제한" 케이스 감지용.
    folder_path 의 prefix 와 일치하는 모든 registry 엔트리를 검사하여
    `Path(abs).exists() == False` 인 것들을 orphan 으로 반환.

    Returns:
        [{ "path": str(원본 abs), "domain": "doc"|"image"|"video"|"audio" }, ...]
    """
    if not folder_path:
        return []
    _ensure_fresh_index()
    base = _norm(folder_path)
    if not base:
        return []
    out: list[dict] = []
    # _abs_index_cache 는 _norm 키 → domain. 원본 abs 는 도메인별 registry 의 entry["abs"].
    # prefix 매칭은 norm 기준, 존재 검사는 원본 abs 로 수행.
    for dom, label in _DOMAIN_LABEL.items():
        reg = _load_one(dom)
        for entry in reg.values():
            abs_path = entry.get("abs") if isinstance(entry, dict) else None
            if not abs_path:
                continue
            n = _norm(abs_path)
            if not n.startswith(base):
                continue
            # base 이후에 분리자 또는 끝 — 잘못된 prefix 매칭 방지
            tail = n[len(base):]
            if tail and tail[0] not in ("/", "\\"):
                continue
            try:
                if not Path(abs_path).exists():
                    out.append({"path": abs_path, "domain": label})
            except Exception:
                continue
    return out
