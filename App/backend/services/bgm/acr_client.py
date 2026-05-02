"""ACRCloud Identification API 클라이언트 — 스위치 OFF면 호출 0건.

기본 정책:
  bgm.api_enabled == False → recognize() 즉시 None 반환 (네트워크 호출 X)
  bgm.api_enabled == True  → ACR REST endpoint 호출

키는 bgm.acrcloud.{host, access_key, access_secret} 에서 읽음.
의존: requests (lazy import)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from pathlib import Path
from typing import Any

from . import bgm_config

logger = logging.getLogger(__name__)


def _credentials() -> tuple[str, str, str] | None:
    host   = bgm_config.get_bgm_setting("acrcloud.host", "") or ""
    key    = bgm_config.get_bgm_setting("acrcloud.access_key", "") or ""
    secret = bgm_config.get_bgm_setting("acrcloud.access_secret", "") or ""
    if not (host and key and secret):
        return None
    return host, key, secret


def is_configured() -> bool:
    """API 키가 모두 채워져 있는지 (스위치 OFF여도 True 가능)."""
    return _credentials() is not None


def _signature(string_to_sign: str, secret: str) -> str:
    h = hmac.new(secret.encode("ascii"), string_to_sign.encode("ascii"), hashlib.sha1)
    return base64.b64encode(h.digest()).decode("ascii")


def recognize(audio_path: str | Path) -> dict[str, Any] | None:
    """오디오 파일 → ACR 인식 결과 dict.

    스위치 OFF / 키 미설정 시 None 반환 (외부 호출 안 함).
    인식 실패 / 네트워크 오류 시 None.

    반환 예: {"title": "Dynamite", "artist": "BTS", "score": 99, "raw": {...}}
    """
    if not bgm_config.is_api_enabled():
        logger.debug("[bgm.acr] api_enabled=False — 호출 스킵")
        return None

    creds = _credentials()
    if creds is None:
        logger.debug("[bgm.acr] 자격증명 미설정 — 호출 스킵")
        return None
    host, access_key, access_secret = creds

    path = Path(audio_path)
    if not path.is_file():
        logger.warning(f"[bgm.acr] 파일 없음: {path}")
        return None

    try:
        import requests  # type: ignore
    except ImportError:
        logger.warning("[bgm.acr] requests 미설치 — `pip install requests`")
        return None

    url = f"https://{host}/v1/identify"
    http_method = "POST"
    http_uri = "/v1/identify"
    data_type = "audio"
    signature_version = "1"
    timestamp = str(int(time.time()))

    # ACR 표준 권장: 입력 오디오 처음 ~10초만 전송
    audio_bytes = path.read_bytes()[: 1024 * 1024]  # 1MB cap

    string_to_sign = "\n".join([
        http_method, http_uri, access_key,
        data_type, signature_version, timestamp,
    ])
    sig = _signature(string_to_sign, access_secret)

    files = {"sample": ("sample", audio_bytes)}
    payload = {
        "access_key":        access_key,
        "sample_bytes":      str(len(audio_bytes)),
        "timestamp":         timestamp,
        "signature":         sig,
        "data_type":         data_type,
        "signature_version": signature_version,
    }

    try:
        resp = requests.post(url, files=files, data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[bgm.acr] 호출 실패: {e}")
        return None

    if data.get("status", {}).get("code") != 0:
        # 1001 = no result, 그 외 다양한 에러
        return None

    music = (data.get("metadata") or {}).get("music") or []
    if not music:
        return None
    top = music[0]
    artists = top.get("artists") or []
    artist_name = ", ".join((a.get("name") or "") for a in artists if a.get("name"))
    return {
        "title":  (top.get("title") or "").strip(),
        "artist": artist_name.strip(),
        "score":  int(top.get("score") or 0),
        "raw":    top,
    }
