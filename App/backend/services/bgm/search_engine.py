"""BGM 검색 엔진 — 텍스트 쿼리 + 오디오 식별 통합.

런타임:
  - 1회 모델/인덱스 로드, 이후 메모리 상주 (TriChefEngine 패턴)
  - search(text)    : CLAP text→audio FAISS + librosa tag boost + filename/acr boost
  - identify(audio) : Chromaprint exact → CLAP audio→audio → (옵션) ACR API
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Any

import numpy as np

from . import (
    acr_client,
    bgm_config,
    chromaprint as cp,
    clap_encoder,
    index_store,
    nlp_query,
    segments as bgm_segments,
)

logger = logging.getLogger(__name__)


def _confidence_from_margin(margin: float) -> str:
    if margin >= bgm_config.SCORE_MARGIN_HIGH:
        return "high"
    if margin >= bgm_config.SCORE_MARGIN_MED:
        return "medium"
    return "low"


# ── Null distribution calibration (다른 도메인과 동일한 통계 매핑) ──────────
# Doc/Img/Movie/Rec 와 동일하게 z-score CDF 기반:
#   confidence = Φ((cosine - μ_null) / σ_null)
# scripts/bgm_calibrate.py 가 생성한 calibration.json 로드.
_CAL_CACHE: dict = {}


def _load_calibration() -> dict:
    """BGM null distribution (μ, σ) 로드. 없으면 보수적 기본값."""
    global _CAL_CACHE
    if _CAL_CACHE:
        return _CAL_CACHE
    cal_path = bgm_config.INDEX_DIR / "calibration.json"
    if cal_path.is_file():
        try:
            d = json.loads(cal_path.read_text(encoding="utf-8"))
            _CAL_CACHE = {
                "mu_null":    float(d.get("mu_null", 0.40)),
                "sigma_null": float(d.get("sigma_null", 0.08)),
            }
        except Exception:
            _CAL_CACHE = {"mu_null": 0.40, "sigma_null": 0.08}
    else:
        # 기본값 — CLAP text-to-audio 실측 null 분포 (비관련 쿼리 평균 ~0.40)
        # mu=0.40: 비관련 쿼리 기준선, sigma=0.08: 분포 폭
        # → CLAP 0.45 ≈ 73%, 0.50 ≈ 89%, 0.55 ≈ 97%
        _CAL_CACHE = {"mu_null": 0.40, "sigma_null": 0.08}
    return _CAL_CACHE


def _normalize_score(s: float) -> float:
    """CLAP cosine → 통계적 confidence [0, 1] (Doc/Img/Movie/Rec 와 동일 매핑).

    Null distribution 기반 z-score CDF:
      z = (s − μ_null) / σ_null
      confidence = Φ(z) = 0.5 * (1 + erf(z / √2))

    의미:
      50% = 무관 쿼리·문서 평균
      85% = 1σ 위 (의미 있는 매칭)
      97.5% = 2σ 위 (강한 매칭)
      99.7% = 3σ 위 (매우 강한 매칭)
    """
    cal = _load_calibration()
    sigma = max(cal["sigma_null"], 1e-6)
    z = (float(s) - cal["mu_null"]) / sigma
    return max(0.0, min(1.0, 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))


def _fmt_time_range(start: float, end: float) -> str:
    """1:23 ~ 1:53 형식."""
    def _hms(s: float) -> str:
        s = max(0.0, float(s))
        m = int(s // 60)
        ss = int(s - m * 60)
        return f"{m}:{ss:02d}"
    return f"{_hms(start)} ~ {_hms(end)}"


class BGMEngine:
    """싱글턴 권장 (라이트하므로 새로 생성해도 무방)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._meta: index_store.MetaStore | None = None
        self._index = None           # CLAP audio 인덱스
        self._text_index = None      # CLAP text-description 인덱스
        self._text_ids: list[str] = []  # text 인덱스 순서대로 filename
        self._fp_db: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            self._meta = index_store.MetaStore(bgm_config.META_PATH)
            self._index = index_store.load_index(bgm_config.CLAP_INDEX_PATH)
            # 텍스트 설명 인덱스 (bgm_enrich_text.py 산출물)
            if bgm_config.TEXT_INDEX_PATH.is_file():
                self._text_index = index_store.load_index(bgm_config.TEXT_INDEX_PATH)
                if bgm_config.TEXT_IDS_PATH.is_file():
                    try:
                        d = json.loads(bgm_config.TEXT_IDS_PATH.read_text(encoding="utf-8"))
                        self._text_ids = d.get("ids", [])
                    except Exception:
                        self._text_ids = []
                logger.info(f"[bgm.engine] text index: {len(self._text_ids)} entries")
            self._fp_db = cp.load_db(bgm_config.CHROMAPRINT_DB)
            self._loaded = True
            logger.info(
                f"[bgm.engine] loaded: meta={len(self._meta)} "
                f"audio_idx={'OK' if self._index is not None else 'MISS'} "
                f"text_idx={'OK' if self._text_index is not None else 'MISS'} "
                f"fp_db={len(self._fp_db)}"
            )

    def reload(self) -> None:
        with self._lock:
            self._loaded = False
        self._ensure_loaded()

    def is_ready(self) -> bool:
        self._ensure_loaded()
        return (
            self._index is not None
            and self._meta is not None
            and len(self._meta) > 0
        )

    def status(self) -> dict[str, Any]:
        self._ensure_loaded()
        return {
            "ready":         self.is_ready(),
            "n_tracks":      len(self._meta) if self._meta else 0,
            "has_clap":      clap_encoder.is_loaded(),
            "has_index":     self._index is not None,
            "fp_db_size":    len(self._fp_db),
            "fp_available":  cp.available(),
            "api_enabled":   bgm_config.is_api_enabled(),
            "api_configured": acr_client.is_configured(),
        }

    # ── 텍스트 쿼리 ─────────────────────────────────────────────────────────

    def search(self, query: str, *, top_k: int = 20) -> dict[str, Any]:
        self._ensure_loaded()
        if not self.is_ready():
            return {
                "query": query, "results": [], "confidence": "none",
                "error": "BGM 인덱스가 비어 있습니다. /api/bgm/rebuild_index 또는 "
                         "scripts/bgm_ingest.py 로 먼저 102 mp4 인덱싱이 필요합니다.",
            }

        parsed = nlp_query.parse(query)

        # BGM CLAP query translation:
        # CLAP is an English-dominant model. For Korean queries, we replace the
        # original Korean text with ONLY the English translations so that the
        # CLAP text embedding lives in the same English semantic space as the
        # audio-text training pairs. Keeping Korean tokens degrades embedding quality.
        raw_text = parsed.text_for_clap or query
        try:
            from services.query_expand import _KO_EN
            import re as _re
            _has_korean = bool(_re.search(r'[가-힣]', raw_text))
            if _has_korean:
                # BGM-domain mood priority map — produces CLAP-friendly English phrases
                # that stay in the same semantic region as typical English BGM queries.
                # e.g. "어두운 긴장감" → "dark tense dramatic" (same region as EN query)
                _BGM_MOOD_PRIORITY: dict[str, list[str]] = {
                    "어두운":   ["dark", "tense", "dramatic"],
                    "긴장감":   ["tense", "dramatic", "intense"],
                    "긴장":     ["tense", "tension", "dramatic"],
                    "잔잔한":   ["calm", "peaceful", "gentle"],
                    "신나는":   ["upbeat", "energetic", "lively"],
                    "빠른":     ["fast", "upbeat", "energetic"],
                    "느린":     ["slow", "calm", "relaxing"],
                    "슬픈":     ["sad", "melancholic", "sorrowful"],
                    "밝은":     ["bright", "cheerful", "upbeat"],
                    "웅장한":   ["epic", "grand", "orchestral"],
                    "신비로운": ["mysterious", "ethereal", "ambient"],
                    "편안한":   ["relaxing", "soothing", "comfortable"],
                }
                # Korean query: translate to English ONLY (discard Korean tokens)
                tokens = raw_text.split()
                english_parts: list[str] = []
                seen: set[str] = set()
                for tok in tokens:
                    # BGM mood priority > general dictionary
                    translations = _BGM_MOOD_PRIORITY.get(tok) or _KO_EN.get(tok, [])
                    if translations:
                        for en in translations[:3]:  # up to 3 translations per token
                            if en.lower() not in seen:
                                english_parts.append(en)
                                seen.add(en.lower())
                    # else: no translation, skip Korean token
                # Fallback: if no translations found, use original
                clap_query = " ".join(english_parts) if english_parts else raw_text
            else:
                # English query: use as-is (CLAP handles English natively)
                clap_query = raw_text
        except Exception:
            clap_query = raw_text

        try:
            q_vec = clap_encoder.encode_text(clap_query)[0]
        except Exception as e:
            logger.exception("CLAP 텍스트 인코딩 실패")
            return {"query": query, "results": [], "error": str(e)[:300]}

        items = self._meta.all()
        # filename → meta index
        fn_to_idx = {m.get("filename", ""): i for i, m in enumerate(items)}

        # ── 오디오 인덱스 검색 (text→audio CLAP) ──────────────────────────────
        pool = max(top_k * 4, 40)
        audio_scores: dict[str, float] = {}
        if self._index is not None:
            s_arr, i_arr = index_store.search(self._index, q_vec, pool)
            for s, i in zip(s_arr.tolist(), i_arr.tolist()):
                if i < 0 or i >= len(items):
                    continue
                fn = items[i].get("filename", "")
                audio_scores[fn] = float(s)

        # ── 텍스트 설명 인덱스 검색 (text→text CLAP) ──────────────────────────
        text_scores: dict[str, float] = {}
        if self._text_index is not None and self._text_ids:
            ts_arr, ti_arr = index_store.search(self._text_index, q_vec, pool)
            for s, i in zip(ts_arr.tolist(), ti_arr.tolist()):
                if i < 0 or i >= len(self._text_ids):
                    continue
                fn = self._text_ids[i]
                text_scores[fn] = float(s)

        # ── 두 채널 퓨전: 0.55 * audio + 0.45 * text ─────────────────────────
        # text 채널이 없으면 audio 100%
        AUDIO_W = 0.55 if text_scores else 1.0
        TEXT_W  = 0.45 if text_scores else 0.0

        all_fns = set(audio_scores) | set(text_scores)
        ranked: list[tuple[int, float, dict[str, float]]] = []

        # Pre-compute description keyword list for CLAP semantic gap compensation.
        # CLAP text encoder sometimes maps mood-antonyms (e.g. "dark tense" vs
        # "energetic upbeat") too close in embedding space. We add a small explicit
        # keyword match bonus based on query words found in the description text.
        import re as _re_dkw
        _DESC_STOP = {"music", "background", "with", "and", "for", "the",
                      "very", "tempo", "clip", "that", "this", "from"}
        _desc_kw: list[str] = list(dict.fromkeys(
            w for w in _re_dkw.findall(r'[a-z]{4,}', clap_query.lower())
            if w not in _DESC_STOP
        )) if clap_query else []

        for fn in all_fns:
            idx = fn_to_idx.get(fn)
            if idx is None:
                continue
            m = items[idx]
            a_s = audio_scores.get(fn, 0.0)
            t_s = text_scores.get(fn, 0.0)
            fused_base = AUDIO_W * a_s + TEXT_W * t_s

            # Description keyword boost: rewards files whose description explicitly
            # contains the query mood/style words. Compensates for CLAP blind spots.
            # e.g. "dark tense dramatic" → dark files (+0.075) vs warm files (+0.0)
            desc_kw_boost = 0.0
            if _desc_kw:
                desc_lower = (m.get("description") or "").lower()
                matched = sum(1 for w in _desc_kw if w in desc_lower)
                desc_kw_boost = min(matched * 0.025, 0.10)

            boost = self._apply_boosts(parsed, m)
            ranked.append((idx, fused_base + boost["total"] + desc_kw_boost, boost))

        ranked.sort(key=lambda t: -t[1])
        ranked = ranked[:top_k]

        # 마진 기반 confidence
        margin = (ranked[0][1] - ranked[1][1]) if len(ranked) >= 2 else 0.5
        confidence = _confidence_from_margin(margin)

        # 세그먼트 인덱스가 있으면 각 파일별 best segment timestamp 도 채움
        seg_results: list[dict] = []
        try:
            seg_results = bgm_segments.search_segments(q_vec, top_k=top_k * 3, per_file_limit=3) or []
        except Exception as e:
            logger.debug(f"[bgm.engine] segment search 실패: {e}")
            seg_results = []
        # filename → list of segments
        seg_by_file: dict[str, list[dict]] = {}
        for sr in seg_results:
            seg_by_file.setdefault(sr["filename"], []).append(sr)

        results = []
        for rank, (i, fused, boost) in enumerate(ranked, 1):
            m = items[i]
            fn = m.get("filename", "")
            file_segments = seg_by_file.get(fn, [])
            # 정규화된 segment 정보 (start, end, score, confidence, label)
            segs = [
                {
                    "start":      s["start"],
                    "end":        s["end"],
                    "score":      round(s["score"], 4),
                    "confidence": round(_normalize_score(s["score"]), 4),
                    "label":      _fmt_time_range(s["start"], s["end"]),
                }
                for s in file_segments
            ]
            top_seg = segs[0] if segs else None
            results.append({
                "rank":         rank,
                "filename":     fn,
                "guess_artist": m.get("guess_artist", ""),
                "guess_title":  m.get("guess_title", ""),
                "acr_artist":   m.get("acr_artist", ""),
                "acr_title":    m.get("acr_title", ""),
                "duration":     m.get("duration", 0.0),
                "tags":         m.get("tags", []),
                "description":  m.get("description", ""),
                "source":       m.get("source", "catalog"),
                "params":       m.get("params", {}),
                "score":        round(fused, 4),
                "audio_score":  round(audio_scores.get(fn, 0.0), 4),
                "text_score":   round(text_scores.get(fn, 0.0), 4),
                "confidence":   round(_normalize_score(fused), 4),
                "boost":        {k: round(v, 4) for k, v in boost.items()},
                "segments":     segs,
                "top_segment":  top_seg,
            })

        return {
            "query":      query,
            "parsed":     {
                "artist_hint":   parsed.artist_hint,
                "title_hint":    parsed.title_hint,
                "mood_boosts":   parsed.mood_boosts,
                "broad_artist":  parsed.broad_artist_search,
            },
            "results":    results,
            "confidence": confidence,
            "score_margin": round(margin, 4),
        }

    def _apply_boosts(self, parsed: nlp_query.ParsedQuery, m: dict[str, Any]) -> dict[str, float]:
        artist_b = title_b = mood_b = 0.0

        # artist 매칭
        if parsed.artist_hint:
            ah = parsed.artist_hint.lower()
            blob = " ".join([
                str(m.get("filename", "")),
                str(m.get("guess_artist", "")),
                str(m.get("acr_artist", "")),
            ]).lower()
            if ah in blob:
                artist_b = 0.30 if parsed.broad_artist_search else 0.20

        # title 매칭
        if parsed.title_hint:
            th = parsed.title_hint.lower()
            blob = " ".join([
                str(m.get("filename", "")),
                str(m.get("guess_title", "")),
                str(m.get("acr_title", "")),
            ]).lower()
            if th in blob:
                title_b = 0.25

        # mood 매칭 (librosa tag)
        tags = [t.lower() for t in (m.get("tags") or [])]
        if parsed.mood_boosts and tags:
            from .nlp_query import MOOD_SYNONYMS
            for mood in parsed.mood_boosts:
                keys = [k.lower() for k in MOOD_SYNONYMS.get(mood, [])]
                if any(k in tags or any(k in t for t in tags) for k in keys):
                    mood_b += 0.05

        total = artist_b + title_b + mood_b
        return {"artist": artist_b, "title": title_b, "mood": mood_b, "total": total}

    # ── 오디오 식별 ─────────────────────────────────────────────────────────

    def identify(
        self,
        audio_path: str | Path,
        *,
        top_k: int = 5,
        use_api_fallback: bool = True,
    ) -> dict[str, Any]:
        """업로드된 mp4/audio → 곡 식별.

        흐름: Chromaprint exact → CLAP audio→audio → (옵션) ACR API
        """
        self._ensure_loaded()
        path = Path(audio_path)
        if not path.is_file():
            return {"results": [], "error": "파일 없음"}

        # ── 1. Chromaprint exact ───────────────────────────────────────────
        if cp.available() and self._fp_db:
            fp_pair = cp.fingerprint_file(path)
            if fp_pair is not None:
                fp_str, dur = fp_pair
                hit = cp.find_best_match(
                    fp_str, self._fp_db,
                    threshold=bgm_config.FINGERPRINT_HIGH,
                )
                if hit is not None:
                    fn, sim = hit
                    items = self._meta.all() if self._meta else []
                    matched = next((m for m in items if m.get("filename") == fn), None)
                    if matched is not None:
                        return {
                            "method": "chromaprint",
                            "confidence": "high",
                            "results": [{
                                "rank": 1,
                                "filename":     matched.get("filename", ""),
                                "guess_artist": matched.get("guess_artist", ""),
                                "guess_title":  matched.get("guess_title", ""),
                                "acr_artist":   matched.get("acr_artist", ""),
                                "acr_title":    matched.get("acr_title", ""),
                                "duration":     matched.get("duration", 0.0),
                                "tags":         matched.get("tags", []),
                                "score":        round(float(sim), 4),
                                "confidence":   round(float(sim), 4),
                            }],
                        }

        # ── 2. CLAP audio→audio ────────────────────────────────────────────
        try:
            q_vec = clap_encoder.encode_audio_file(path)
        except Exception as e:
            logger.exception("CLAP 오디오 인코딩 실패")
            q_vec = None

        clap_results: list[dict[str, Any]] = []
        if q_vec is not None and self._index is not None and self._meta is not None:
            scores, idxs = index_store.search(self._index, q_vec, top_k)
            items = self._meta.all()
            for rank, (s, i) in enumerate(zip(scores.tolist(), idxs.tolist()), 1):
                if i < 0 or i >= len(items):
                    continue
                m = items[i]
                clap_results.append({
                    "rank": rank,
                    "filename":     m.get("filename", ""),
                    "guess_artist": m.get("guess_artist", ""),
                    "guess_title":  m.get("guess_title", ""),
                    "acr_artist":   m.get("acr_artist", ""),
                    "acr_title":    m.get("acr_title", ""),
                    "duration":     m.get("duration", 0.0),
                    "tags":         m.get("tags", []),
                "source":       m.get("source", "catalog"),
                    "score":        round(float(s), 4),
                    "confidence":   round(_normalize_score(float(s)), 4),
                })

        clap_top = clap_results[0] if clap_results else None
        if clap_top and clap_top["score"] >= 0.5:
            return {
                "method":     "clap",
                "confidence": "medium",
                "results":    clap_results,
            }

        # ── 3. ACR API (옵션, 스위치 OFF면 호출 자체 X) ─────────────────────
        if use_api_fallback and bgm_config.is_api_enabled():
            acr = acr_client.recognize(path)
            if acr is not None:
                return {
                    "method":     "acrcloud",
                    "confidence": "high" if acr.get("score", 0) >= 80 else "medium",
                    "results": [{
                        "rank":         1,
                        "filename":     "",  # 외부 — 로컬 카탈로그 외
                        "guess_artist": acr.get("artist", ""),
                        "guess_title":  acr.get("title", ""),
                        "acr_artist":   acr.get("artist", ""),
                        "acr_title":    acr.get("title", ""),
                        "score":        float(acr.get("score", 0)) / 100.0,
                        "confidence":   float(acr.get("score", 0)) / 100.0,
                        "external":     True,
                    }],
                }

        # ── 4. 최종 fallback: CLAP top-k 그대로 (low confidence) ───────────
        return {
            "method":     "clap_low",
            "confidence": "low",
            "results":    clap_results,
        }


# 싱글턴
_engine: BGMEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> BGMEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = BGMEngine()
    return _engine


def reload_engine() -> None:
    global _engine
    # 캘리브레이션 캐시도 함께 갱신
    import services.bgm.search_engine as _self
    _self._CAL_CACHE.clear()
    with _engine_lock:
        if _engine is not None:
            _engine.reload()
        else:
            _engine = BGMEngine()
