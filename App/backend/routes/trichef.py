"""routes/trichef.py — TRI-CHEF REST API Blueprint."""
from __future__ import annotations

import json as _json
import logging
import mimetypes
import re as _re
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

# ── doc_page ID → 원본 문서 정보 파싱 ────────────────────────────────────────
_doc_reg_cache: dict | None = None
_doc_reg_lock  = threading.Lock()


def _get_doc_stem_map() -> dict[str, str]:
    """stem_key → 원본 문서 절대경로 역방향 매핑 (서버 기동 시 1회 로드)."""
    global _doc_reg_cache
    if _doc_reg_cache is not None:
        return _doc_reg_cache
    with _doc_reg_lock:
        if _doc_reg_cache is not None:
            return _doc_reg_cache
        mapping: dict[str, str] = {}
        try:
            from embedders.trichef.doc_page_render import stem_key_for
            reg_path = Path(PATHS["TRICHEF_DOC_CACHE"]) / "registry.json"
            if reg_path.exists():
                reg = _json.loads(reg_path.read_text(encoding="utf-8"))
                for rel_key, meta in reg.items():
                    mapping[stem_key_for(rel_key)] = meta.get("abs", rel_key)
        except Exception as e:
            logger.warning(f"[doc_stem_map] 로드 실패: {e}")
        _doc_reg_cache = mapping
        logger.info(f"[doc_stem_map] {len(mapping)}개 문서 매핑 완료")
        return _doc_reg_cache


def _parse_doc_page_id(page_id: str) -> dict:
    """page_images/<stem_key>/p####.jpg → file_name / page_num / source_path.

    Returns:
        file_name  : 원본 문서 stem 이름 (hash 제거)
        page_num   : 1-based 페이지 번호
        source_path: 원본 문서 절대경로 (registry 조회, 없으면 "")
    """
    try:
        parts = Path(page_id).parts          # ('page_images', '<stem_key>', 'p####.jpg')
        if len(parts) >= 3 and parts[0] == "page_images":
            stem_key = parts[1]
            page_stem = Path(parts[2]).stem   # "p####"
            # stem_key = "<sanitized_name>__<8hex>" → 문서명 추출
            doc_name  = _re.sub(r"__[0-9a-f]{8}$", "", stem_key)
            page_match = _re.match(r"p(\d+)", page_stem)
            page_num  = int(page_match.group(1)) + 1 if page_match else 1
            source_path = _get_doc_stem_map().get(stem_key, "")
            return {"file_name": doc_name, "page_num": page_num,
                    "source_path": source_path}
    except Exception:
        pass
    return {"file_name": Path(page_id).name, "page_num": 1, "source_path": ""}

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


def reload_engine() -> None:
    """임베딩 완료 후 검색 엔진 캐시 재로드 (npy 파일 변경 반영)."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            try:
                _engine.reload()
            except Exception as e:
                logger.warning(f"[reload_engine] reload 실패, 재생성: {e}")
                _engine = TriChefEngine()
        else:
            _engine = TriChefEngine()


@bp.post("/search")
def search():
    body = request.get_json(force=True)
    query = body.get("query", "").strip()
    if not query:
        return jsonify({"error": "query 필수"}), 400

    # 한↔영 양방향 쿼리 확장 (다국어 일관성)
    try:
        from services.query_expand import expand_bilingual
        engine_query = expand_bilingual(query)
    except Exception:
        engine_query = query
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
                av_res = engine.search_av(engine_query, domain=d, topk=topk)
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
                        "dense":          r.metadata.get("dense_agg", r.score),
                        "lexical":        r.metadata.get("sparse_agg", 0.0),
                        "asf":            r.metadata.get("asf_agg", 0.0),
                        "segments":       r.segments,   # 각 세그먼트에 preview 필드 포함
                        "low_confidence": r.metadata.get("low_confidence", False),
                        "preview_url":    None,
                    })
            else:
                res = engine.search(engine_query, domain=d, topk=topk,
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
                    # doc_page: 원본 문서명·페이지·경로 파싱
                    if d == "doc_page":
                        doc_info    = _parse_doc_page_id(r.id)
                        file_name   = doc_info["file_name"]
                        page_num    = doc_info["page_num"]
                        source_path = doc_info["source_path"]
                    else:
                        file_name   = Path(r.id).name
                        page_num    = None
                        source_path = str(Path(PATHS["RAW_DB"]) / "Img" / r.id) if d == "image" else ""

                    all_items.append({
                        "rank":           rank,
                        "domain":         d,
                        "id":             r.id,
                        "file_name":      file_name,
                        "page_num":       page_num,       # doc_page only, 1-based
                        "source_path":    source_path,    # 원본 문서 절대경로
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

    # ── 도메인별 중복 제거 ─────────────────────────────────────────────────────
    # image: staged/<sha8>/file.jpg ↔ file.jpg 중복 → leaf 파일명 기준, confidence 높은 것 유지
    # doc_page: 같은 PDF/문서의 여러 페이지 → 문서명(file_name) 기준, confidence 높은 페이지 유지
    _seen_img: dict[str, dict] = {}   # leaf_name → item
    _seen_doc: dict[str, dict] = {}   # file_name → item (best page per doc)
    _other:    list[dict]      = []

    for item in all_items:
        if item["domain"] == "image":
            leaf = Path(item["id"]).name
            prev = _seen_img.get(leaf)
            if prev is None or item["confidence"] > prev["confidence"]:
                _seen_img[leaf] = item
        elif item["domain"] == "doc_page":
            doc_key = item.get("file_name") or Path(item["id"]).name
            prev = _seen_doc.get(doc_key)
            if prev is None or item["confidence"] > prev["confidence"]:
                _seen_doc[doc_key] = item
        else:
            _other.append(item)

    all_items = list(_seen_img.values()) + list(_seen_doc.values()) + _other

    # 5도메인 통합 score 조정 — Edge case 격리 + generous curve
    # 페널티 판정은 확장된 쿼리(engine_query)로 수행:
    #   '꽃' → '꽃 flower flowers blossom' → meaningful ≫ 2 → 0.55 cap 해제
    try:
        from services.score_adjust import adjust_confidence, _generous_curve
        _penalty_q = engine_query  # expand_bilingual 결과 재사용
        for it in all_items:
            if "confidence" in it and it["confidence"] is not None:
                it["confidence"] = round(adjust_confidence(it["confidence"], _penalty_q), 4)
            # dense (raw cosine): edge case 무관, generous curve 만 적용
            if "dense" in it and it["dense"] is not None:
                it["dense"] = round(_generous_curve(it["dense"]), 4)
    except Exception:
        pass

    all_items.sort(key=lambda x: -x["confidence"])
    top = all_items[:topk]
    for i, it in enumerate(top, 1):
        it["global_rank"] = i

    # ── location 부착 (이미지 title/tagline/synopsis, 문서 page/snippet) ──────
    try:
        from services.location_resolver import _img_location, _doc_location
        for it in top:
            d = it.get("domain", "")
            trichef_id = it.get("id", "")
            if d == "image":
                loc = _img_location(trichef_id, query)
                if loc:
                    it["location"] = loc
            elif d == "doc_page":
                loc = _doc_location(trichef_id, query)
                if loc:
                    it["location"] = loc
    except Exception:
        pass

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


@bp.post("/search_by_image")
def search_by_image():
    """이미지 파일 업로드 → TRI-CHEF 이미지 검색.

    multipart/form-data:
      image  : 이미지 파일 (필수)
      domain : "image" | "doc_page"  (기본 "image")
      topk   : 정수 (기본 20)
    """
    import tempfile
    import os

    if "image" not in request.files:
        return jsonify({"error": "image 파일 필수"}), 400

    file   = request.files["image"]
    domain = request.form.get("domain", "image")
    topk   = int(request.form.get("topk", 20))

    if domain not in ("image", "doc_page"):
        return jsonify({"error": "domain 은 image 또는 doc_page 만 허용"}), 400

    # 임시 파일로 저장 (확장자 보존)
    suffix = Path(file.filename).suffix if file.filename else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        file.save(tmp.name)
        tmp_path = Path(tmp.name)

    try:
        engine = _get_engine()
        results = engine.search_by_image(tmp_path, domain=domain, topk=topk)
    except Exception as e:
        logger.exception("search_by_image 실패")
        return jsonify({"error": str(e)[:400]}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    items = []
    for rank, r in enumerate(results, 1):
        if domain == "doc_page":
            doc_info    = _parse_doc_page_id(r.id)
            file_name   = doc_info["file_name"]
            page_num    = doc_info["page_num"]
            source_path = doc_info["source_path"]
        else:
            file_name   = Path(r.id).name
            page_num    = None
            source_path = str(Path(PATHS["RAW_DB"]) / "Img" / r.id)
        items.append({
            "rank":           rank,
            "domain":         domain,
            "id":             r.id,
            "file_name":      file_name,
            "page_num":       page_num,
            "source_path":    source_path,
            "score":          round(r.score, 4),
            "confidence":     round(r.confidence, 4),
            "dense":          round(r.metadata.get("dense", r.score), 4),
            "low_confidence": r.metadata.get("low_confidence", False),
            "caption":        r.metadata.get("caption", ""),
            "preview_url":    f"/api/trichef/file?domain={domain}&path={r.id}",
            "segments":       [],
        })

    return jsonify({"domain": domain, "top": items, "count": len(items)})


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
