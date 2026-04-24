"""routes/trichef.py — TRI-CHEF REST API Blueprint."""
from __future__ import annotations

import logging
import mimetypes
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from config import PATHS, TRICHEF_CFG
from services.trichef.unified_engine import TriChefEngine
from embedders.trichef.incremental_runner import (
    run_image_incremental,
    run_doc_incremental,
    run_movie_incremental,
    run_music_incremental,
)

logger = logging.getLogger(__name__)
bp = Blueprint("trichef", __name__, url_prefix="/api/trichef")

_engine: TriChefEngine | None = None
_engine_lock = threading.Lock()

_raw_count_cache: dict = {"ts": 0.0, "img": 0, "doc": 0}
_raw_count_ttl = 5.0  # 초


def _raw_counts() -> tuple[int, int]:
    import time
    now = time.time()
    if now - _raw_count_cache["ts"] < _raw_count_ttl:
        return _raw_count_cache["img"], _raw_count_cache["doc"]
    img_dir = Path(PATHS["RAW_DB"]) / "Img"
    doc_dir = Path(PATHS["RAW_DB"]) / "Doc"
    img_n = sum(1 for p in img_dir.rglob("*.*") if p.is_file()) if img_dir.exists() else 0
    doc_n = sum(1 for p in doc_dir.rglob("*.*") if p.is_file()) if doc_dir.exists() else 0
    _raw_count_cache.update(ts=now, img=img_n, doc=doc_n)
    return img_n, doc_n


def _get_engine() -> TriChefEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = TriChefEngine()
    return _engine


@bp.post("/search")
def search():
    body = request.get_json(force=True)
    query = body.get("query", "").strip()
    if not query:
        return jsonify({"error": "query 필수"}), 400
    topk = int(body.get("topk", 20))
    domains = body.get("domains", ["image", "doc_page"])
    use_lexical = bool(body.get("use_lexical", True))
    use_asf = bool(body.get("use_asf", True))
    pool = int(body.get("pool", 200))

    engine = _get_engine()
    all_items: list[dict] = []
    stats: dict = {"per_domain": {}}

    from services.trichef import calibration

    _AV_DOMAINS = {"movie", "music"}

    for d in domains:
        try:
            if d in _AV_DOMAINS:
                av_res = engine.search_av(query, domain=d, topk=topk)
                cal = calibration.get_thresholds(d)
                stats["per_domain"][d] = {
                    "count": len(av_res),
                    "mu_null":       round(cal["mu_null"], 4),
                    "sigma_null":    round(cal["sigma_null"], 4),
                    "abs_threshold": round(cal["abs_threshold"], 4),
                }
                for rank, r in enumerate(av_res, 1):
                    all_items.append({
                        "rank":           rank,
                        "domain":         d,
                        "id":             r.file_path,
                        "file_name":      r.file_name,
                        "score":          r.score,
                        "confidence":     r.confidence,
                        "dense":          r.score,
                        "lexical":        0.0,
                        "asf":            0.0,
                        "segments":       r.segments,   # 각 세그먼트에 preview 필드 포함
                        "low_confidence": r.metadata.get("low_confidence", False),
                        "preview_url":    None,
                    })
            else:
                res = engine.search(query, domain=d, topk=topk,
                                    use_lexical=use_lexical, use_asf=use_asf,
                                    pool=pool)
                cal = calibration.get_thresholds(d)
                stats["per_domain"][d] = {
                    "count": len(res),
                    "mu_null":        round(cal["mu_null"], 4),
                    "sigma_null":     round(cal["sigma_null"], 4),
                    "abs_threshold":  round(cal["abs_threshold"], 4),
                }
                for rank, r in enumerate(res, 1):
                    all_items.append({
                        "rank":           rank,
                        "domain":         d,
                        "id":             r.id,
                        "score":          round(r.score, 4),
                        "confidence":     round(r.confidence, 4),
                        "dense":          round(r.metadata.get("dense", r.score), 4),
                        "lexical":        round(r.metadata.get("lexical", 0.0), 4),
                        "asf":            round(r.metadata.get("asf", 0.0), 4),
                        "low_confidence": r.metadata.get("low_confidence", False),
                        "segments":       [],
                        "preview_url":    f"/api/trichef/file?domain={d}&path={r.id}",
                    })
        except Exception as e:
            logger.exception(f"domain={d} 검색 실패")
            stats["per_domain"][d] = {"error": str(e)[:200], "count": 0}

    all_items.sort(key=lambda x: -x["confidence"])
    top = all_items[:topk]
    for i, it in enumerate(top, 1):
        it["global_rank"] = i

    return jsonify({"query": query, "top": top, "stats": stats})


_SAFE_ROOTS = [
    Path(PATHS["RAW_DB"]),
    Path(PATHS["EXTRACTED_DB"]),
    Path(PATHS["EMBEDDED_DB"]),
]


@bp.get("/file")
def serve_file():
    rel = request.args.get("path", "")
    domain = request.args.get("domain", "image")
    if not rel:
        return jsonify({"error": "path 필수"}), 400
    if ".." in rel or rel.startswith("/") or rel.startswith("\\"):
        return jsonify({"error": "허용되지 않은 경로"}), 400

    if domain == "image":
        candidate = Path(PATHS["RAW_DB"]) / "Img" / rel
    else:
        candidate = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / rel
    candidate = candidate.resolve()

    if not any(
        candidate == r.resolve() or candidate.is_relative_to(r.resolve())
        for r in _SAFE_ROOTS
    ):
        return jsonify({"error": "허용되지 않은 경로"}), 403
    if not candidate.exists():
        return jsonify({"error": "파일 없음"}), 404

    mime, _ = mimetypes.guess_type(str(candidate))
    return send_file(str(candidate), mimetype=mime or "application/octet-stream")


@bp.post("/reindex")
def reindex():
    body  = request.get_json(silent=True) or {}
    scope = body.get("scope", "all")
    # scope: "image" | "document" | "movie" | "music" | "all"
    results = {}
    if scope in ("image", "all"):
        try:
            results["image"] = run_image_incremental().__dict__
        except Exception as e:
            logger.exception("image reindex 실패")
            results["image"] = {"error": str(e)[:400]}
    if scope in ("document", "all"):
        try:
            results["document"] = run_doc_incremental().__dict__
        except Exception as e:
            logger.exception("document reindex 실패")
            results["document"] = {"error": str(e)[:400]}
    if scope in ("movie", "all"):
        try:
            results["movie"] = run_movie_incremental().__dict__
        except Exception as e:
            logger.exception("movie reindex 실패")
            results["movie"] = {"error": str(e)[:400]}
    if scope in ("music", "all"):
        try:
            results["music"] = run_music_incremental().__dict__
        except Exception as e:
            logger.exception("music reindex 실패")
            results["music"] = {"error": str(e)[:400]}
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.reload()
    return jsonify(results)


@bp.get("/status")
def status():
    """캐시 현황 빠른 조회 (모델 로드 없음)."""
    idir  = Path(PATHS["TRICHEF_IMG_CACHE"])
    ddir  = Path(PATHS["TRICHEF_DOC_CACHE"])
    mdir  = Path(PATHS["TRICHEF_MOVIE_CACHE"])
    mudir = Path(PATHS["TRICHEF_MUSIC_CACHE"])
    img_n, doc_n = _raw_counts()

    def _npy_rows(npy_path: Path) -> int:
        try:
            import numpy as np
            return int(np.load(npy_path, mmap_mode="r").shape[0])
        except Exception:
            return 0

    return jsonify({
        "image_cached":    (idir  / "cache_img_Re_siglip2.npy").exists(),
        "doc_page_cached": (ddir  / "cache_doc_page_Re.npy").exists(),
        "movie_cached":    (mdir  / "cache_movie_Re.npy").exists(),
        "music_cached":    (mudir / "cache_music_Re.npy").exists(),
        "img_raw_count":   img_n,
        "doc_raw_count":   doc_n,
        "movie_segments":  _npy_rows(mdir  / "cache_movie_Re.npy"),
        "music_segments":  _npy_rows(mudir / "cache_music_Re.npy"),
    })


@bp.get("/image-tags")
def image_tags():
    p = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "tags" / "image_tags.json"
    if not p.exists():
        return jsonify({"count": 0, "images": []})
    import json as _json
    data = _json.loads(p.read_text(encoding="utf-8"))
    return jsonify({"count": len(data), "images": data})
