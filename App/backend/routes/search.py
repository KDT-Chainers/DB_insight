import json
import os
import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request

search_bp = Blueprint("search", __name__, url_prefix="/api")


# ── 검색 ──────────────────────────────────────────────────────────

@search_bp.get("/search")
def search():
    """
    GET /api/search?q=검색어&top_k=10&type=doc|image|audio|video

    type 미지정 → 인덱싱된 모든 타입에서 검색 후 유사도 합산.

    Response:
    {
      "query": "검색어",
      "results": [
        {
          "file_path":  str,
          "file_name":  str,
          "file_type":  str,   # doc | image | audio | video
          "similarity": float, # 0.0 ~ 1.0
          "snippet":    str
        },
        ...
      ]
    }
    """
    query     = request.args.get("q", "").strip()
    top_k     = request.args.get("top_k", default=10, type=int)
    file_type = request.args.get("type", default=None)

    if not query:
        return jsonify({"error": "q is required"}), 400
    if top_k <= 0:
        top_k = 10

    try:
        from db.vector_store import search as vs_search, search_all, search_video_m11, count

        results: list[dict] = []

        if file_type in ("image", "doc"):
            # TRI-CHEF 전용 검색
            domain = "image" if file_type == "image" else "doc_page"
            results = _search_trichef(query, [domain], top_k)
        elif file_type == "video":
            from embedders.base import encode_query_e5
            query_vec = encode_query_e5(query)
            results   = search_video_m11(query_vec, top_k=top_k)
        elif file_type == "audio":
            query_vec = _encode_for_type(query, "audio")
            results   = vs_search(query_vec, file_type="audio", top_k=top_k)
        else:
            # 전체 검색: 레거시(video/audio) + TRI-CHEF(image/doc_page)
            if count() > 0:
                embeddings_by_type = _encode_all(query)
                legacy = search_all(embeddings_by_type, top_k=top_k)
            else:
                legacy = []
            trichef = _search_trichef(query, ["image", "doc_page"], top_k)
            # 합산 후 similarity 내림차순 정렬
            combined = legacy + trichef
            combined.sort(key=lambda r: r.get("similarity", 0), reverse=True)
            results = combined[:top_k]

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"query": query, "results": results})


def _search_trichef(query: str, domains: list[str], top_k: int) -> list[dict]:
    """
    TRI-CHEF 엔진으로 이미지/문서 검색 후 통합 검색 결과 스키마로 변환.
    반환: [{file_path, file_name, file_type, similarity, snippet, preview_url}, ...]
    """
    from config import PATHS
    from routes.trichef import _get_engine

    try:
        engine = _get_engine()
    except Exception:
        return []

    # TRI-CHEF 이미지 레지스트리 (staged → 원본 경로 매핑)
    img_reg: dict = {}
    doc_reg: dict = {}
    try:
        img_cache = Path(PATHS["TRICHEF_IMG_CACHE"]) / "registry.json"
        if img_cache.exists():
            img_reg = json.loads(img_cache.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        doc_cache = Path(PATHS["TRICHEF_DOC_CACHE"]) / "registry.json"
        if doc_cache.exists():
            doc_reg = json.loads(doc_cache.read_text(encoding="utf-8"))
    except Exception:
        pass

    results: list[dict] = []
    doc_extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])

    for domain in domains:
        try:
            hits = engine.search(query, domain=domain, topk=top_k)
        except Exception:
            continue
        for hit in hits:
            rid = hit.id  # e.g. "staged/abc/foo.jpg" or "page_images/stem/p001.png"
            if domain == "image":
                file_type = "image"
                # 원본 경로 (registry 우선, 없으면 staged 경로)
                reg_entry = img_reg.get(rid, {})
                orig_path = reg_entry.get("abs") or str(
                    Path(PATHS["RAW_DB"]) / "Img" / rid
                )
                file_name = Path(orig_path).name
                # 캡션 스니펫
                snippet   = _read_img_caption(Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions", rid)
                # 미리보기 URL — raw_DB/Img/{rid} 경로로 서빙
                preview_url = f"/api/trichef/file?domain=image&path={rid}"
            else:
                # doc_page: id = "page_images/stem_key/page_001.png"
                file_type = "doc"
                parts = Path(rid).parts
                stem_key  = parts[1] if len(parts) >= 2 else rid
                # 원본 문서 경로: doc_reg에서 stem_key 매칭
                orig_path, file_name = _doc_page_to_source(stem_key, doc_reg)
                if not orig_path:
                    orig_path = str(doc_extract / rid)
                    file_name = Path(rid).name
                snippet     = ""
                # 미리보기 URL — 렌더링된 페이지 이미지
                preview_url = f"/api/trichef/file?domain=doc_page&path={rid}"

            results.append({
                "file_path":   orig_path,
                "file_name":   file_name,
                "file_type":   file_type,
                "similarity":  round(hit.confidence, 4),
                "snippet":     snippet,
                "preview_url": preview_url,
                "trichef_id":  rid,
                "trichef_domain": domain,
            })

    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results[:top_k]


def _read_img_caption(cap_root: Path, key: str) -> str:
    """캡션 파일(json 또는 txt)에서 캡션 텍스트 읽기."""
    try:
        from embedders.trichef.doc_page_render import stem_key_for
        stem = stem_key_for(key)
    except Exception:
        stem = key.replace("/", "_").replace("\\", "_")
    for suffix in (f"{stem}.caption.json", f"{stem}.txt"):
        p = cap_root / suffix
        if p.exists():
            try:
                if suffix.endswith(".json"):
                    d = json.loads(p.read_text(encoding="utf-8"))
                    return d.get("L1") or ""
                return p.read_text(encoding="utf-8")[:300]
            except Exception:
                pass
    return ""


def _doc_page_to_source(stem_key: str, doc_reg: dict) -> tuple[str, str]:
    """
    stem_key → (원본 파일 경로, 파일명).
    doc_reg: {rel_key: {sha, abs, staged, pages}}
    """
    try:
        from embedders.trichef.doc_page_render import stem_key_for
        for rel_key, info in doc_reg.items():
            if stem_key_for(rel_key) == stem_key:
                orig = info.get("abs") or info.get("staged", "")
                return orig, Path(rel_key).name
    except Exception:
        pass
    return "", ""


def _encode_for_type(query: str, file_type: str) -> list[float]:
    """파일 타입에 맞는 모델로 쿼리 인코딩."""
    if file_type == "audio":
        from embedders.base import encode_query_ko
        return encode_query_ko(query)
    elif file_type == "video":
        from embedders.base import encode_query_e5
        return encode_query_e5(query)
    else:
        from embedders.base import encode_query
        return encode_query(query)


def _encode_all(query: str) -> dict[str, list[float]]:
    """
    레거시 컬렉션(video/audio) 전용 타입별 쿼리 인코딩.
    image/doc 은 TRI-CHEF 엔진으로 별도 처리하므로 여기서 제외.
      audio → 768d (ko-sroberta)
      video → 1024d (e5-large, M11)
    각 컬렉션에 청크가 없으면 포함하지 않음.
    """
    from db.vector_store import count as col_count

    result: dict[str, list[float] | None] = {}

    # 768d 모델 (audio)
    if col_count("audio") > 0:
        from embedders.base import encode_query_ko
        result["audio"] = encode_query_ko(query)

    # 1024d 모델 (video, M11 e5-large)
    if col_count("video") > 0:
        from embedders.base import encode_query_e5
        result["video"] = encode_query_e5(query)

    return result


# ── 인덱싱된 파일 목록 ────────────────────────────────────────────

@search_bp.get("/indexed-files")
def indexed_files():
    """GET /api/indexed-files"""
    try:
        from db.vector_store import get_indexed_files, count
        files = get_indexed_files()
        return jsonify({"total_chunks": count(), "files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 파일 열기 ─────────────────────────────────────────────────────

@search_bp.post("/files/open")
def file_open():
    """POST /api/files/open  body: { "file_path": "C:/..." }"""
    data      = request.get_json(silent=True) or {}
    file_path = data.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    os.startfile(file_path)
    return jsonify({"success": True})


@search_bp.post("/files/open-folder")
def folder_open():
    """POST /api/files/open-folder  body: { "file_path": "C:/..." }"""
    data      = request.get_json(silent=True) or {}
    file_path = data.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    subprocess.Popen(["explorer", "/select,", file_path])
    return jsonify({"success": True})
