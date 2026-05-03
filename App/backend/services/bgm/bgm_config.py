"""BGM 도메인 설정 — settings.json 스위치 + 모델 파라미터.

settings.json 경로: <DATA_ROOT>/settings.json (없으면 기본값 사용).

스위치 흐름:
  is_api_enabled() == False  → ACRCloud 호출 0건 (lazy import 자체도 안 함)
  is_api_enabled() == True   → bgm.acrcloud.* 키로 ACR 호출 가능
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from config import (
    DATA_ROOT,
    EMBEDDED_DB_BGM,
    EXTRACTED_DB_BGM,
    RAW_DB,
)

logger = logging.getLogger(__name__)

# ── 디렉터리 ────────────────────────────────────────────────────────────────
RAW_BGM_DIR        = RAW_DB / "Movie" / "정혜_BGM_1차"   # 102 mp4 원본
AUDIO_CACHE_DIR    = EXTRACTED_DB_BGM / "audio"          # mp4 → wav 캐시
INDEX_DIR          = EMBEDDED_DB_BGM                      # 인덱스 산출물

# ── 산출물 경로 ─────────────────────────────────────────────────────────────
META_PATH          = INDEX_DIR / "audio_meta.json"
CLAP_EMB_PATH      = INDEX_DIR / "clap_emb.npy"
CLAP_INDEX_PATH    = INDEX_DIR / "clap_index.faiss"
CHROMAPRINT_DB     = INDEX_DIR / "chromaprint_db.json"
LIBROSA_FEATS      = INDEX_DIR / "librosa_features.json"
CATALOG_VERSION    = INDEX_DIR / "catalog_version.json"

# ── 모델 파라미터 ───────────────────────────────────────────────────────────
CLAP_MODEL         = os.environ.get("BGM_CLAP_MODEL", "laion/clap-htsat-unfused")
CLAP_SR            = 48000   # CLAP 입력 샘플레이트
CLAP_DIM           = 512     # CLAP 임베딩 차원
AUDIO_MAX_SECONDS  = 60.0    # 1트랙당 인덱싱 길이 상한
DEVICE             = "cuda" if os.environ.get("FORCE_CPU") != "1" else "cpu"

# ── Confidence 임계값 ──────────────────────────────────────────────────────
SCORE_MARGIN_HIGH  = 0.15
SCORE_MARGIN_MED   = 0.05
FINGERPRINT_HIGH   = 0.97   # Chromaprint similarity 임계값
# (self-match=1.0 통과, 무관 트랙 false positive median 0.90 차단)

# ── 설정 파일 ──────────────────────────────────────────────────────────────
SETTINGS_PATH      = DATA_ROOT / "settings.json"

_DEFAULT_SETTINGS: dict[str, Any] = {
    "bgm": {
        "api_enabled": False,
        "api_provider": "acrcloud",
        "acrcloud": {
            "host": "",
            "access_key": "",
            "access_secret": "",
        },
        "fallback_to_local": True,
        "auto_enrich_catalog": True,
    }
}

_settings_cache: dict[str, Any] | None = None
_settings_lock = threading.Lock()


def _deep_merge(base: dict, override: dict) -> dict:
    """override의 키만 덮어쓰는 재귀 병합."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(force_reload: bool = False) -> dict[str, Any]:
    """settings.json 로드 (메모리 캐시)."""
    global _settings_cache
    if _settings_cache is not None and not force_reload:
        return _settings_cache
    with _settings_lock:
        if _settings_cache is not None and not force_reload:
            return _settings_cache
        if SETTINGS_PATH.is_file():
            try:
                user = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[bgm.config] settings.json 파싱 실패, 기본값 사용: {e}")
                user = {}
        else:
            user = {}
        _settings_cache = _deep_merge(_DEFAULT_SETTINGS, user)
        return _settings_cache


def save_settings(new_settings: dict[str, Any]) -> None:
    """settings.json 갱신. 입력은 전체 또는 부분(top-level) dict."""
    global _settings_cache
    with _settings_lock:
        current = load_settings(force_reload=True)
        merged = _deep_merge(current, new_settings)
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _settings_cache = merged


def get_bgm_setting(path: str, default: Any = None) -> Any:
    """예: get_bgm_setting('api_enabled', False) → bgm.api_enabled."""
    s = load_settings()
    cur: Any = s.get("bgm", {})
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur


def is_api_enabled() -> bool:
    """ACRCloud 외부 API 호출 허용 여부."""
    return bool(get_bgm_setting("api_enabled", False))


def set_api_enabled(enabled: bool) -> None:
    save_settings({"bgm": {"api_enabled": bool(enabled)}})
