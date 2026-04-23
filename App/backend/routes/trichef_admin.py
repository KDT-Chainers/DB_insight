"""routes/trichef_admin.py — 관리자 전용 read-only 전수 검사 API.

프론트엔드(Gradio) 와 분리된 별도 프로세스에서 호출.
임계치/top-K 필터 없이 모든 항목에 대한 per-row 점수를 반환.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import fitz
import numpy as np
from flask import Blueprint, jsonify, request, send_file

from config import PATHS, TRICHEF_CFG
from embedders.trichef import bgem3_sparse, siglip2_re
from embedders.trichef import bgem3_caption_im as e5_caption_im
from embedders.trichef.caption_io import load_caption, page_idx_from_stem
from services.trichef import asf_filter, calibration, qwen_expand, tri_gs
from services.trichef.auto_vocab import _tokenize

logger = logging.getLogger(__name__)
bp_admin = Blueprint("trichef_admin", __name__, url_prefix="/api/admin")


# ── 엔진 재사용 (routes/trichef.py 의 _get_engine 싱글턴과 공유) ─────────
def _engine():
    from routes.trichef import _get_engine
    return _get_engine()


# ── 경로 해석 ────────────────────────────────────────────────────────────
def _resolve_file_path(domain: str, doc_id: str) -> Path | None:
    if domain == "image":
        p = Path(PATHS["RAW_DB"]) / "Img" / doc_id
        return p if p.exists() else None
    if domain == "doc_page":
        p = Path(PATHS["TRICHEF_DOC_EXTRACT"]) / doc_id
        return p if p.exists() else None
    return None


def _source_doc_path(doc_id: str) -> tuple[Path | None, int]:
    """doc_page id → (원본 문서 경로, 페이지 번호). PDF/HWP/Office 통합."""
    parts = Path(doc_id).parts
    if len(parts) < 3 or parts[0] != "page_images":
        return None, 0
    stem = parts[1]
    page_stem = Path(parts[2]).stem
    page_idx = page_idx_from_stem(page_stem)

    cache = Path(PATHS["TRICHEF_DOC_CACHE"])
    reg = json.loads((cache / "registry.json").read_text(encoding="utf-8"))
    from embedders.trichef.doc_page_render import _sanitize
    for key, meta in reg.items():
        if _sanitize(Path(key).stem) == stem:
            return Path(meta["abs"]), page_idx
    return None, page_idx


def _doc_text(doc_id: str) -> str:
    """doc_page id → 해당 페이지의 PDF 원문 + 캡션 결합."""
    parts = Path(doc_id).parts
    if len(parts) < 3 or parts[0] != "page_images":
        return ""
    stem = parts[1]
    page_stem = Path(parts[2]).stem
    page_idx = page_idx_from_stem(page_stem)

    extract = Path(PATHS["TRICHEF_DOC_EXTRACT"])
    cap = load_caption(extract / "captions" / stem, page_stem)

    from services.trichef.lexical_rebuild import resolve_doc_pdf_map
    stem_to_pdf = resolve_doc_pdf_map()
    pdf = stem_to_pdf.get(stem)
    body = ""
    if pdf and pdf.exists() and pdf.stat().st_size > 0:
        try:
            with fitz.open(pdf) as d:
                if 0 <= page_idx < len(d):
                    body = d[page_idx].get_text("text") or ""
        except Exception as e:
            logger.warning(f"[admin] PDF text 추출 실패 {pdf.name}: {e}")
    return (cap + "\n" + body).strip()


def _image_caption(doc_id: str) -> str:
    cap_dir = Path(PATHS["TRICHEF_IMG_EXTRACT"]) / "captions"
    return load_caption(cap_dir, Path(doc_id).stem)


# ── 매칭 토큰 추출 (하이라이트용) ──────────────────────────────────────
def _matched_tokens(query: str, text: str, vocab: dict) -> list[str]:
    q_raw = set(_tokenize(query))
    t_raw = set(_tokenize(text))
    matches: set[str] = set()
    # exact
    for t in q_raw:
        if t in t_raw:
            matches.add(t)
    # 한글 substring (vocab 기준 확장)
    for qt in q_raw:
        if any("\uac00" <= c <= "\ud7a3" for c in qt) and len(qt) >= 2:
            for tt in t_raw:
                if qt in tt:
                    matches.add(tt)
    return sorted(matches, key=len, reverse=True)


# ── 엔드포인트: 전수 검색 ───────────────────────────────────────────
@bp_admin.post("/inspect")
def inspect():
    """쿼리 1건에 대한 전수 per-row 스코어.

    body: {query, domain(image|doc_page), top_n=200, use_lexical=True, use_asf=True}
    """
    body = request.get_json(force=True)
    query = body.get("query", "").strip()
    domain = body.get("domain", "doc_page")
    top_n = int(body.get("top_n", 200))
    use_lexical = bool(body.get("use_lexical", True))
    use_asf = bool(body.get("use_asf", True))

    if not query:
        return jsonify({"error": "query 필수"}), 400

    e = _engine()
    if domain not in e._cache:
        return jsonify({"error": f"domain {domain} 캐시 없음"}), 400

    d = e._cache[domain]
    # 쿼리 임베딩
    variants = qwen_expand.expand(query)
    q_Re = qwen_expand.avg_normalize(siglip2_re.embed_texts(variants))
    q_Im = qwen_expand.avg_normalize(e5_caption_im.embed_query(variants))
    q_Z = q_Im

    dense = tri_gs.hermitian_score(
        q_Re[None, :], q_Im[None, :], q_Z[None, :],
        d["Re"], d["Im"], d["Z"],
    )[0]

    lex = None
    if use_lexical and d.get("sparse") is not None:
        q_sp = bgem3_sparse.embed_query_sparse(query)
        lex = bgem3_sparse.lexical_scores(q_sp, d["sparse"])

    asf_s = None
    if use_asf and d.get("asf_sets") and d.get("vocab"):
        asf_s = asf_filter.asf_scores(query, d["asf_sets"], d["vocab"])

    # RRF
    rankings = [np.argsort(-dense)]
    if lex is not None:
        rankings.append(np.argsort(-lex))
    if asf_s is not None and asf_s.any():
        rankings.append(np.argsort(-asf_s))
    n = len(dense)
    rrf = np.zeros(n, dtype=np.float32)
    for order in rankings:
        for rank, idx in enumerate(order):
            rrf[int(idx)] += 1.0 / (60 + rank + 1)
    order = np.argsort(-rrf)

    cal = calibration.get_thresholds(domain)
    mu, sig = cal.get("mu_null", 0.0), max(cal.get("sigma_null", 1.0), 1e-9)

    rows = []
    for rank, i in enumerate(order[:top_n], start=1):
        s = float(dense[i])
        z = (s - mu) / sig
        conf = 0.5 * (1 + math.erf(z / (2 ** 0.5)))
        doc_id = d["ids"][i]
        rows.append({
            "rank": rank,
            "id": doc_id,
            "dense": s,
            "lexical": float(lex[i]) if lex is not None else None,
            "asf": float(asf_s[i]) if asf_s is not None else None,
            "rrf": float(rrf[i]),
            "confidence": conf,
            "z_score": z,
        })

    return jsonify({
        "domain": domain,
        "query": query,
        "total": n,
        "returned": len(rows),
        "calibration": {"mu_null": mu, "sigma_null": sig,
                        "abs_threshold": cal.get("abs_threshold", 0.0)},
        "rows": rows,
    })


@bp_admin.get("/doc-text")
def doc_text():
    """doc_page id → 원문 텍스트 + 매칭 토큰 (쿼리가 있으면)."""
    doc_id = request.args.get("id", "").strip()
    query = request.args.get("query", "").strip()
    domain = request.args.get("domain", "doc_page")
    if not doc_id:
        return jsonify({"error": "id 필수"}), 400

    if domain == "image":
        text = _image_caption(doc_id)
    else:
        text = _doc_text(doc_id)

    matches = []
    if query:
        e = _engine()
        vocab = e._cache.get(domain, {}).get("vocab", {})
        matches = _matched_tokens(query, text, vocab)

    src, page = _source_doc_path(doc_id) if domain == "doc_page" else (
        _resolve_file_path("image", doc_id), 0
    )
    return jsonify({
        "id": doc_id,
        "text": text,
        "matches": matches,
        "source_path": str(src) if src else None,
        "page": page,
    })


@bp_admin.get("/file")
def file_serve():
    """도메인별 파일 서빙 (이미지 썸네일용)."""
    doc_id = request.args.get("id", "").strip()
    domain = request.args.get("domain", "doc_page")
    if not doc_id:
        return jsonify({"error": "id 필수"}), 400
    p = _resolve_file_path(domain, doc_id)
    if not p or not p.exists():
        return jsonify({"error": "file not found"}), 404
    return send_file(str(p))


@bp_admin.get("/domains")
def domains():
    """로드된 도메인 + 각 카운트."""
    e = _engine()
    out = {}
    for dom, cache in e._cache.items():
        out[dom] = {
            "count": int(cache["Re"].shape[0]),
            "has_sparse": cache.get("sparse") is not None,
            "has_asf":    bool(cache.get("asf_sets")),
            "vocab_size": len(cache.get("vocab", {})),
        }
    return jsonify(out)
