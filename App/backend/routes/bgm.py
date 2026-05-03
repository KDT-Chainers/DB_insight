"""routes/bgm.py — BGM (5번째 도메인) Flask Blueprint.

엔드포인트:
  POST /api/bgm/search           텍스트 쿼리
  POST /api/bgm/identify         오디오/비디오 업로드 → 곡 식별
  GET  /api/bgm/file?id=...      미디어 파일 스트리밍
  GET  /api/bgm/api_status       ACR API 스위치 상태
  POST /api/bgm/api_toggle       ACR API ON/OFF (+ 키 갱신)
  POST /api/bgm/catalog_sync     ACR 메타 보강 (api_enabled=True 필요)
  POST /api/bgm/rebuild_index    102 mp4 인덱스 재구축 (관리자용)
  GET  /api/bgm/health           엔진 상태
"""
from __future__ import annotations

import logging
import mimetypes
import os
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from services.bgm import bgm_config
from services.bgm import acr_client
from services.bgm import ingest_pipeline
from services.bgm.search_engine import get_engine, reload_engine

logger = logging.getLogger(__name__)
bp = Blueprint("bgm", __name__, url_prefix="/api/bgm")


# ── 텍스트 검색 ─────────────────────────────────────────────────────────────

@bp.post("/search")
def search():
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query 필수"}), 400
    top_k = int(body.get("top_k", body.get("topk", 20)))

    # 한↔영 양방향 쿼리 확장 (다국어 일관성)
    try:
        from services.query_expand import expand_bilingual
        expanded_query = expand_bilingual(query)
    except Exception:
        expanded_query = query

    engine = get_engine()
    try:
        result = engine.search(expanded_query, top_k=top_k)
        # 응답 query 필드는 원본 표시
        result["query"] = query
        result["expanded_query"] = expanded_query if expanded_query != query else None
    except Exception as e:
        logger.exception("[bgm.search] 실패")
        return jsonify({"query": query, "results": [], "error": str(e)[:300]}), 500

    # 5도메인 통합 score 조정 — Edge case 격리 + generous curve
    try:
        from services.score_adjust import adjust_confidences, _generous_curve
        adjust_confidences(result.get("results", []), query)
        for r in result.get("results", []):
            adjust_confidences(r.get("segments") or [], query)
            # dense (raw cosine): generous curve 만 적용 (UI 유사도 표시용)
            if "dense" in r and r["dense"] is not None:
                r["dense"] = round(_generous_curve(r["dense"]), 4)
            if "score" in r and r["score"] is not None:
                r["score"] = round(_generous_curve(r["score"]), 4)
    except Exception:
        pass

    # /api/admin/inspect 호환 형식으로 추가 매핑 (frontend 통합용)
    rows = []
    for r in result.get("results", []):
        rows.append({
            "id":            r.get("filename", ""),
            "filename":      r.get("filename", ""),
            "source_path":   "",  # 보안: 절대경로 노출 X — preview는 /api/bgm/file 사용
            "score":         r.get("score", 0.0),
            "confidence":    r.get("confidence", 0.0),
            "dense":         r.get("score", 0.0),
            "guess_artist":  r.get("guess_artist", ""),
            "guess_title":   r.get("guess_title", ""),
            "acr_artist":    r.get("acr_artist", ""),
            "acr_title":     r.get("acr_title", ""),
            "duration":      r.get("duration", 0.0),
            "tags":          r.get("tags", []),
            "boost":         r.get("boost", {}),
        })
    return jsonify({
        "query":        result.get("query"),
        "parsed":       result.get("parsed"),
        "rows":         rows,
        "results":      result.get("results", []),  # 원본 형식도 함께
        "confidence":   result.get("confidence"),
        "score_margin": result.get("score_margin"),
        "engine":       "bgm",
    })


# ── 오디오/비디오 업로드 → 곡 식별 ──────────────────────────────────────────

@bp.post("/identify")
def identify():
    """multipart/form-data:
      file              : mp4/mp3/wav (필수)
      top_k             : 정수 (기본 5)
      use_api_fallback  : "1"|"0" (기본 1 — bgm.api_enabled 가 True 일 때만 의미)
    """
    if "file" not in request.files:
        return jsonify({"error": "file 필드 필수"}), 400
    f = request.files["file"]
    top_k = int(request.form.get("top_k", 5))
    use_api = request.form.get("use_api_fallback", "1").strip() not in ("0", "false", "no")

    suffix = Path(f.filename or "").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        f.save(tmp.name)
        tmp_path = Path(tmp.name)

    try:
        engine = get_engine()
        result = engine.identify(tmp_path, top_k=top_k, use_api_fallback=use_api)
    except Exception as e:
        logger.exception("[bgm.identify] 실패")
        return jsonify({"error": str(e)[:300]}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return jsonify(result)


# ── 미디어 파일 스트리밍 ────────────────────────────────────────────────────

@bp.get("/file")
def serve_file():
    """id 또는 path 로 미리보기 스트리밍.
    안전: bgm 인덱스에 등록된 filename 만 허용.
    """
    file_id = request.args.get("id", "").strip()
    if not file_id:
        return jsonify({"error": "id 필수"}), 400
    if "/" in file_id or "\\" in file_id or ".." in file_id:
        return jsonify({"error": "잘못된 id"}), 400

    engine = get_engine()
    engine._ensure_loaded()  # noqa: SLF001 — 단순 상태 점검용
    items = engine._meta.all() if engine._meta else []
    target = next((it for it in items if it.get("filename") == file_id), None)
    if target is None:
        return jsonify({"error": "등록되지 않은 파일"}), 404

    src = Path(target.get("path") or "")
    if not src.is_file():
        # raw_DB 기본 디렉터리에서 재탐색
        cand = bgm_config.RAW_BGM_DIR / file_id
        if cand.is_file():
            src = cand
    if not src.is_file():
        return jsonify({"error": "파일이 디스크에 없음"}), 404

    mime, _ = mimetypes.guess_type(str(src))
    return send_file(str(src), mimetype=mime or "application/octet-stream", conditional=True)


# ── API 스위치 ──────────────────────────────────────────────────────────────

@bp.get("/api_status")
def api_status():
    return jsonify({
        "api_enabled":      bgm_config.is_api_enabled(),
        "api_provider":     bgm_config.get_bgm_setting("api_provider", "acrcloud"),
        "api_configured":   acr_client.is_configured(),
        "fallback_to_local": bool(bgm_config.get_bgm_setting("fallback_to_local", True)),
        "auto_enrich":      bool(bgm_config.get_bgm_setting("auto_enrich_catalog", True)),
        "host":             bgm_config.get_bgm_setting("acrcloud.host", ""),
        # 키는 마스킹
        "access_key_set":    bool(bgm_config.get_bgm_setting("acrcloud.access_key", "")),
        "access_secret_set": bool(bgm_config.get_bgm_setting("acrcloud.access_secret", "")),
    })


@bp.post("/api_toggle")
def api_toggle():
    """body 예:
      {"api_enabled": true,
       "host": "...", "access_key": "...", "access_secret": "...",
       "fallback_to_local": true, "auto_enrich_catalog": true}
    """
    body = request.get_json(silent=True) or {}
    patch: dict = {}
    if "api_enabled" in body:
        patch["api_enabled"] = bool(body["api_enabled"])
    if "fallback_to_local" in body:
        patch["fallback_to_local"] = bool(body["fallback_to_local"])
    if "auto_enrich_catalog" in body:
        patch["auto_enrich_catalog"] = bool(body["auto_enrich_catalog"])

    acr_patch: dict = {}
    for key in ("host", "access_key", "access_secret"):
        if key in body and isinstance(body[key], str):
            acr_patch[key] = body[key].strip()
    if acr_patch:
        patch["acrcloud"] = acr_patch

    if patch:
        bgm_config.save_settings({"bgm": patch})

    return api_status()


# ── ACR 카탈로그 동기화 ─────────────────────────────────────────────────────

@bp.post("/catalog_sync")
def catalog_sync():
    """ACR 메타 보강 (api_enabled & 자격증명 필수)."""
    if not bgm_config.is_api_enabled():
        return jsonify({"error": "bgm.api_enabled=False"}), 400
    if not acr_client.is_configured():
        return jsonify({"error": "ACR 자격증명 미설정"}), 400

    body = request.get_json(silent=True) or {}
    only_missing = bool(body.get("only_missing", True))
    try:
        n = ingest_pipeline.sync_acr_metadata(only_missing=only_missing)
    except Exception as e:
        logger.exception("[bgm.catalog_sync] 실패")
        return jsonify({"error": str(e)[:300]}), 500

    reload_engine()
    return jsonify({"synced": n, "only_missing": only_missing})


# ── 인덱스 재구축 ───────────────────────────────────────────────────────────

@bp.post("/rebuild_index")
def rebuild_index():
    body = request.get_json(silent=True) or {}
    rebuild = bool(body.get("rebuild", False))
    sync_acr = bool(body.get("sync_acr", False))
    src_dir = body.get("src_dir") or None

    try:
        result = ingest_pipeline.build_index(
            src_dir=src_dir, rebuild=rebuild, sync_acr=sync_acr,
        )
    except Exception as e:
        logger.exception("[bgm.rebuild_index] 실패")
        return jsonify({"error": str(e)[:400]}), 500

    reload_engine()
    return jsonify(result)


# ── 헬스 ────────────────────────────────────────────────────────────────────

@bp.get("/health")
def health():
    engine = get_engine()
    s = engine.status()
    s["raw_dir"] = str(bgm_config.RAW_BGM_DIR)
    s["raw_exists"] = bgm_config.RAW_BGM_DIR.is_dir()
    if s["raw_exists"]:
        try:
            n = sum(
                1 for p in bgm_config.RAW_BGM_DIR.iterdir()
                if p.is_file() and p.suffix.lower() in ingest_pipeline.SUPPORTED_EXTS
            )
        except Exception:
            n = 0
        s["raw_count"] = n
    return jsonify(s)
