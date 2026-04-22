"""routes/trichef.py — TRI-CHEF REST API Blueprint."""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from config import PATHS, TRICHEF_CFG
from services.trichef.unified_engine import TriChefEngine
from embedders.trichef.incremental_runner import (
    run_image_incremental,
    run_doc_incremental,
)

logger = logging.getLogger(__name__)
bp = Blueprint("trichef", __name__, url_prefix="/api/trichef")

_engine: TriChefEngine | None = None


def _get_engine() -> TriChefEngine:
    global _engine
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

    engine = _get_engine()
    all_items: list[dict] = []
    stats: dict = {"per_domain": {}}

    from services.trichef import calibration
    for d in domains:
        try:
            res = engine.search(query, domain=d, topk=topk)
        except Exception as e:
            logger.exception(f"domain={d} 검색 실패")
            stats["per_domain"][d] = {"error": str(e)[:200], "count": 0}
            continue
        cal = calibration.get_thresholds(d)
        stats["per_domain"][d] = {
            "count": len(res),
            "mu_null":        round(cal["mu_null"], 4),
            "sigma_null":     round(cal["sigma_null"], 4),
            "abs_threshold":  round(cal["abs_threshold"], 4),
        }
        for rank, r in enumerate(res, 1):
            all_items.append({
                "rank": rank, "domain": d,
                "id": r.id, "score": round(r.score, 4),
                "confidence": round(r.confidence, 4),
                "preview_url": f"/api/trichef/file?domain={d}&path={r.id}",
            })

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
    body = request.get_json(silent=True) or {}
    scope = body.get("scope", "all")   # "image" | "document" | "all"
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
    global _engine
    _engine = None   # 재로드 강제
    return jsonify(results)


@bp.get("/status")
def status():
    """캐시 현황 빠른 조회 (모델 로드 없음)."""
    from pathlib import Path
    idir = Path(PATHS["TRICHEF_IMG_CACHE"])
    ddir = Path(PATHS["TRICHEF_DOC_CACHE"])
    return jsonify({
        "image_cached":    (idir / "cache_img_Re_siglip2.npy").exists(),
        "doc_page_cached": (ddir / "cache_doc_page_Re.npy").exists(),
        "img_raw_count":   len(list((Path(PATHS["RAW_DB"]) / "Img").rglob("*.*")))
                           if (Path(PATHS["RAW_DB"]) / "Img").exists() else 0,
        "doc_raw_count":   sum(
            len(list((Path(PATHS["RAW_DB"]) / d).rglob("*.*")))
            for d in ("Docs", "Doc")
            if (Path(PATHS["RAW_DB"]) / d).exists()
        ),
    })


@bp.get("/image-tags")
def image_tags():
    p = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "tags" / "image_tags.json"
    if not p.exists():
        return jsonify({"count": 0, "images": []})
    import json as _json
    data = _json.loads(p.read_text(encoding="utf-8"))
    return jsonify({"count": len(data), "images": data})
