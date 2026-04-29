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
    GET /api/search?q=검색어&top_k=10&type=doc|image|video|audio

    type 미지정 → 인덱싱된 모든 타입에서 검색.

    Response: { "query": str, "results": [...] }
    결과 항목 공통 스키마:
      file_path   str
      file_name   str
      file_type   str   # doc | image | video | audio
      confidence  float # 0.0 ~ 1.0  (calibrated)
      similarity  float # confidence 와 동일 (하위 호환)
      snippet     str
      preview_url str | null
      segments    list  # video/audio 전용 — 세그먼트 타임라인
    """
    query     = request.args.get("q", "").strip()
    top_k     = request.args.get("top_k", default=10, type=int)
    file_type = request.args.get("type", default=None)

    if not query:
        return jsonify({"error": "q is required"}), 400
    if top_k <= 0:
        top_k = 10

    try:
        results: list[dict] = []

        if file_type == "image":
            results = _search_trichef(query, ["image"], top_k)
        elif file_type == "doc":
            results = _search_trichef(query, ["doc_page"], top_k)
        elif file_type == "video":
            # TRI-CHEF AV 우선 → 캐시 없으면 구형 ChromaDB fallback
            results = _search_trichef_av(query, ["movie"], top_k)
            if not results:
                results = _search_legacy_video(query, top_k)
        elif file_type == "audio":
            # TRI-CHEF AV 우선 → 캐시 없으면 구형 ChromaDB fallback
            results = _search_trichef_av(query, ["music"], top_k)
            if not results:
                results = _search_legacy_audio(query, top_k)
        else:
            # 전체 검색: 이미지·문서·영상·음원 모두 TRI-CHEF
            img_doc = _search_trichef(query, ["image", "doc_page"], top_k)
            video   = _search_trichef_av(query, ["movie"], top_k)
            if not video:
                video = _search_legacy_video(query, top_k)
            audio   = _search_trichef_av(query, ["music"], top_k)
            if not audio:
                audio = _search_legacy_audio(query, top_k)
            combined = img_doc + video + audio
            combined.sort(key=lambda r: r.get("confidence", 0), reverse=True)
            results = combined[:top_k]

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"query": query, "results": results})


# ── TRI-CHEF 이미지·문서 검색 ──────────────────────────────────────

def _search_trichef(query: str, domains: list[str], top_k: int) -> list[dict]:
    """
    TRI-CHEF 엔진으로 이미지/문서 검색.
    반환: [{file_path, file_name, file_type, confidence, similarity, snippet, preview_url, segments=[]}, ...]
    """
    from config import PATHS
    from routes.trichef import _get_engine

    try:
        engine = _get_engine()
    except Exception:
        return []

    # TRI-CHEF 레지스트리 (staged → 원본 경로 매핑)
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
            rid = hit.id
            if domain == "image":
                file_type = "image"
                reg_entry = img_reg.get(rid, {})
                orig_path = reg_entry.get("abs") or str(
                    Path(PATHS["RAW_DB"]) / "Img" / rid
                )
                file_name   = Path(orig_path).name
                snippet     = _read_img_caption(Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions", rid)
                preview_url = f"/api/trichef/file?domain=image&path={rid}"
            else:
                file_type = "doc"
                parts    = Path(rid).parts
                stem_key = parts[1] if len(parts) >= 2 else rid
                orig_path, file_name = _doc_page_to_source(stem_key, doc_reg)
                if not orig_path:
                    orig_path = str(doc_extract / rid)
                    file_name = Path(rid).name
                snippet     = ""
                preview_url = f"/api/trichef/file?domain=doc_page&path={rid}"

            conf = round(hit.confidence, 4)
            results.append({
                "file_path":      orig_path,
                "file_name":      file_name,
                "file_type":      file_type,
                "confidence":     conf,
                "similarity":     conf,       # 하위 호환
                "snippet":        snippet,
                "preview_url":    preview_url,
                "segments":       [],
                "trichef_id":     rid,
                "trichef_domain": domain,
            })

    results.sort(key=lambda r: r["confidence"], reverse=True)

    # ── 같은 원본 파일의 여러 페이지 중 최고 점수 1개만 남김 ──────────
    # doc_page 도메인은 페이지 단위로 임베딩되므로 동일 파일이 중복 반환됨.
    seen_files: dict[str, dict] = {}
    deduped: list[dict] = []
    for r in results:
        key = r["file_path"] or r["trichef_id"]
        if key not in seen_files:
            seen_files[key] = r
            deduped.append(r)
        # 이미 있으면 점수가 더 높은 것으로 교체 (정렬됐으므로 첫 등장이 최고점)

    return deduped[:top_k]


# ── TRI-CHEF AV (영상·음원) 검색 ────────────────────────────────────

def _search_trichef_av(query: str, domains: list[str], top_k: int) -> list[dict]:
    """
    TRI-CHEF AV 엔진으로 movie/music 검색 — search_av() 호출.
    반환: [{file_path, file_name, file_type, confidence, similarity, snippet, preview_url, segments}, ...]

    segments 각 항목:
      start   float   시작 초
      end     float   종료 초
      score   float   세그먼트 점수
      text    str     STT 텍스트
      caption str     캡션 (영상)
      type    str     "stt" | "caption"
      preview str     snippet 미리보기
    """
    from routes.trichef import _get_engine

    try:
        engine = _get_engine()
    except Exception:
        return []

    results: list[dict] = []

    for domain in domains:
        file_type = "video" if domain == "movie" else "audio"
        try:
            av_res = engine.search_av(query, domain=domain, topk=top_k, top_segments=5)
        except Exception:
            continue

        for r in av_res:
            # 대표 스니펫: 최고 점수 세그먼트 텍스트
            top_seg = r.segments[0] if r.segments else {}
            snippet = (
                top_seg.get("preview", "")
                or top_seg.get("text", "")
                or top_seg.get("caption", "")
            )[:300]

            # AV 파일 서빙: /api/admin/file?domain=movie|music&id={file_path}
            # file_path 가 절대경로이므로 관리자 스트림 엔드포인트 재사용
            av_domain = domain  # "movie" | "music"
            preview_url = None

            conf = round(r.confidence, 4)
            results.append({
                "file_path":      r.file_path,
                "file_name":      r.file_name,
                "file_type":      file_type,
                "confidence":     conf,
                "similarity":     conf,    # 하위 호환
                "snippet":        snippet,
                "preview_url":    preview_url,
                "segments":       r.segments,
                "trichef_domain": av_domain,
            })

    results.sort(key=lambda x: -x["confidence"])
    return results[:top_k]


# ── 구형 ChromaDB 비디오/오디오 검색 ────────────────────────────────────

def _search_legacy_video(query: str, top_k: int) -> list[dict]:
    """구형 파이프라인(e5-large + BLIP/STT) 기반 영상 검색."""
    from embedders.base import encode_query_e5
    from db.vector_store import search_video_m11

    try:
        q_vec = encode_query_e5(query)
        hits  = search_video_m11(q_vec, top_k=top_k)
    except Exception:
        return []

    return [
        {
            "file_path":   h["file_path"],
            "file_name":   h["file_name"],
            "file_type":   "video",
            "confidence":  round(h["similarity"], 4),
            "similarity":  round(h["similarity"], 4),
            "snippet":     h.get("snippet", ""),
            "preview_url": None,
            "segments":    [],
        }
        for h in hits
    ]


def _search_legacy_audio(query: str, top_k: int) -> list[dict]:
    """구형 파이프라인(ko-sroberta + 태그 텍스트) 기반 음성 검색."""
    from embedders.base import encode_query_ko
    from db.vector_store import search

    try:
        q_vec = encode_query_ko(query)
        hits  = search(q_vec, file_type="audio", top_k=top_k)
    except Exception:
        return []

    return [
        {
            "file_path":   h["file_path"],
            "file_name":   h["file_name"],
            "file_type":   "audio",
            "confidence":  round(h["similarity"], 4),
            "similarity":  round(h["similarity"], 4),
            "snippet":     h.get("snippet", ""),
            "preview_url": None,
            "segments":    [],
        }
        for h in hits
    ]


# ── 헬퍼 ──────────────────────────────────────────────────────────

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
    """stem_key → (원본 파일 경로, 파일명)."""
    try:
        from embedders.trichef.doc_page_render import stem_key_for
        for rel_key, info in doc_reg.items():
            if stem_key_for(rel_key) == stem_key:
                orig = info.get("abs") or info.get("staged", "")
                return orig, Path(rel_key).name
    except Exception:
        pass
    return "", ""


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
