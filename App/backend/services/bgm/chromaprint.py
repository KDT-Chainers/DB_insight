"""Chromaprint 오디오 지문 (Exact Match) — fpcalc 바이너리 호출.

지문 매칭으로 102 카탈로그 안에 있는 곡인지 즉시 판별.
리믹스/커버는 약하지만 동일 녹음본은 99%+ 정확도.

런타임:
  1. `pyacoustid` (`acoustid.fingerprint_file`) 우선
  2. PATH의 `fpcalc` 바이너리 fallback
  3. 둘 다 없으면 `available()` False — 검색 시 graceful skip

DB 포맷 (chromaprint_db.json):
  {
    "<filename>": {
      "fingerprint": "AQADtMmS...",
      "duration": 187.4
    },
    ...
  }
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _try_acoustid():
    try:
        import acoustid  # type: ignore
        return acoustid
    except ImportError:
        return None


def _fpcalc_path() -> str | None:
    """fpcalc 실행파일 위치. 우선순위:
       1. PATH 등록된 fpcalc
       2. App/backend/bin/fpcalc.exe (저장소 동봉)
       3. 환경변수 FPCALC
    """
    p = shutil.which("fpcalc")
    if p:
        return p

    # 저장소 동봉 (App/backend/bin/fpcalc.exe)
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "bin" / "fpcalc.exe"
        if cand.is_file():
            return str(cand)
        cand = parent / "bin" / "fpcalc"
        if cand.is_file():
            return str(cand)

    import os
    env = os.environ.get("FPCALC", "").strip()
    if env and Path(env).is_file():
        return env
    return None


def available() -> bool:
    """지문 도구 사용 가능 여부."""
    return _try_acoustid() is not None or _fpcalc_path() is not None


def fingerprint_file(path: str | Path) -> tuple[str, float] | None:
    """오디오 파일 → (fingerprint_str, duration_sec). 실패 시 None."""
    path = Path(path)
    if not path.is_file():
        return None

    ac = _try_acoustid()
    if ac is not None:
        try:
            duration, fp = ac.fingerprint_file(str(path))
            if isinstance(fp, bytes):
                fp = fp.decode("ascii", errors="replace")
            return fp, float(duration)
        except Exception as e:
            logger.debug(f"[bgm.chromaprint] acoustid 실패, fpcalc 시도: {e}")

    fpcalc = _fpcalc_path()
    if fpcalc is None:
        return None
    try:
        out = subprocess.run(
            [fpcalc, "-json", str(path)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        data = json.loads(out.stdout.decode("utf-8", errors="replace"))
        fp = data.get("fingerprint", "")
        dur = float(data.get("duration", 0.0))
        if not fp:
            return None
        return fp, dur
    except Exception as e:
        logger.warning(f"[bgm.chromaprint] fpcalc 실패 ({path.name}): {e}")
        return None


# ── 매칭 ────────────────────────────────────────────────────────────────────

def _decode_fp(fp_str: str) -> list[int]:
    """compressed base64 fingerprint → int list. acoustid가 있으면 그쪽 사용."""
    ac = _try_acoustid()
    if ac is not None:
        try:
            from chromaprint import decode_fingerprint  # type: ignore
            ints, _ = decode_fingerprint(fp_str.encode("ascii"))
            return list(ints)
        except Exception:
            pass
    # 단순 fallback: 문자별 ord 시퀀스 (정확도 낮음, exact-eq 비교만 가능)
    return [ord(c) for c in fp_str]


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def similarity(fp_a: str, fp_b: str) -> float:
    """두 지문의 정합도 [0, 1]. 1=동일, 0=무관."""
    if not fp_a or not fp_b:
        return 0.0
    if fp_a == fp_b:
        return 1.0
    a = _decode_fp(fp_a)
    b = _decode_fp(fp_b)
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    # hamming 거리 평균
    total_bits = 0
    diff_bits = 0
    for i in range(n):
        diff_bits += _hamming(a[i], b[i])
        total_bits += 32
    return 1.0 - (diff_bits / total_bits)


# ── DB CRUD ─────────────────────────────────────────────────────────────────

def load_db(path: str | Path) -> dict[str, dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_db(path: str | Path, db: dict[str, dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def find_best_match(
    query_fp: str,
    db: dict[str, dict[str, Any]],
    *,
    threshold: float = 0.85,
) -> tuple[str, float] | None:
    """query 지문에 가장 가까운 DB 항목 → (filename, similarity).
    similarity >= threshold 인 경우만 반환, 아니면 None."""
    if not query_fp or not db:
        return None
    best_name = None
    best_sim = 0.0
    for fn, rec in db.items():
        sim = similarity(query_fp, rec.get("fingerprint", ""))
        if sim > best_sim:
            best_sim = sim
            best_name = fn
    if best_name is not None and best_sim >= threshold:
        return best_name, best_sim
    return None
