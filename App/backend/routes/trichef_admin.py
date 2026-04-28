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
from flask import Blueprint, jsonify, request, send_file, send_from_directory

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
    # [W6-AV] Movie/Music — TRI-CHEF 캐시 상대경로 또는 레거시 절대경로 모두 지원
    if domain in ("music", "movie"):
        abs_p = Path(doc_id)
        # 절대경로 — 레거시 embedded_DB 파일 (local app이므로 허용)
        if abs_p.is_absolute():
            return abs_p if abs_p.exists() else None
        sub = "Rec" if domain == "music" else "Movie"
        p = Path(PATHS["RAW_DB"]) / sub / doc_id
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
    from embedders.trichef.doc_page_render import _sanitize, stem_key_for
    for key, meta in reg.items():
        if stem_key_for(key) == stem or _sanitize(Path(key).stem) == stem:
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
    from embedders.trichef.doc_page_render import stem_key_for
    cap = load_caption(cap_dir, stem_key_for(doc_id))
    if cap:
        return cap
    # 레거시 폴백: 마이그레이션 전 파일명
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
    # [W5-2 / W7-doc-quality] reranker 통합 — BGE-reranker-v2-m3 로 top_n 재순위.
    # [2026-04-24] 기본 ON — doc_page 신뢰도-적합성 일치 개선.
    # 기본값: doc_page True, image False (image 캡션 기반 rerank 는 효과 낮음).
    default_rerank = (domain == "doc_page")
    use_rerank = bool(body.get("use_rerank", default_rerank))
    rerank_k   = int(body.get("rerank_k", min(top_n, 50)))

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

    # [W4-4] Wave3 에서 Qwen 한국어 캡션으로 전환됨 — 과거의 "image+KR → lex/asf 스킵"
    # 휴리스틱은 더 이상 유효하지 않다. 한국어 캡션이라 BGE-M3 sparse / ASF 가 정상 매칭된다.
    # (제거: has_kr 판정 및 강제 비활성화)

    lex = None
    if use_lexical and d.get("sparse") is not None:
        q_sp = bgem3_sparse.embed_query_sparse(query)
        lex = bgem3_sparse.lexical_scores(q_sp, d["sparse"])

    asf_s = None
    if use_asf and d.get("asf_sets") and d.get("vocab"):
        asf_s = asf_filter.asf_scores(query, d["asf_sets"], d["vocab"])

    # [개선 2] 가중 fusion — 신호 있는 채널만 정규화 후 가중합. 없는 채널의 가중치는 dense 로 재배분.
    def _minmax(x):
        lo, hi = float(np.min(x)), float(np.max(x))
        return (x - lo) / (hi - lo + 1e-12) if hi > lo else np.zeros_like(x)

    w_dense, w_lex, w_asf = 0.6, 0.25, 0.15
    lex_active = lex is not None and float(np.max(lex)) > 0
    asf_active = asf_s is not None and float(np.max(asf_s)) > 0
    if not lex_active:
        w_dense += w_lex
        w_lex = 0.0
    if not asf_active:
        w_dense += w_asf
        w_asf = 0.0
    fused = w_dense * _minmax(dense)
    if w_lex > 0:
        fused = fused + w_lex * _minmax(lex)
    if w_asf > 0:
        fused = fused + w_asf * _minmax(asf_s)

    # RRF 는 표시용으로 유지 (참고치)
    rankings = [np.argsort(-dense)]
    if lex_active:
        rankings.append(np.argsort(-lex))
    if asf_active:
        rankings.append(np.argsort(-asf_s))
    n = len(dense)
    rrf = np.zeros(n, dtype=np.float32)
    for order_ in rankings:
        for r_, idx in enumerate(order_):
            rrf[int(idx)] += 1.0 / (60 + r_ + 1)

    order = np.argsort(-fused)

    cal = calibration.get_thresholds(domain)
    mu, sig = cal.get("mu_null", 0.0), max(cal.get("sigma_null", 1.0), 1e-9)
    # [개선 3] image 도메인: abs_threshold 를 μ+3σ 로 상향 (기존 calibration 값이 낮게 잡힌 경우 보호)
    abs_thr = cal.get("abs_threshold", 0.0)
    if domain == "image":
        abs_thr = max(abs_thr, mu + 3.0 * sig)

    # [W5-2] 선택적 cross-encoder 재순위: fused 상위 rerank_k 에만 적용
    rerank_scores: dict[int, float] = {}
    if use_rerank:
        try:
            import sys
            from pathlib import Path as _P
            _ROOT = _P(__file__).resolve().parents[2].parent
            if str(_ROOT) not in sys.path:
                sys.path.insert(0, str(_ROOT))
            from shared.reranker import get_reranker
            rr = get_reranker()
            cand_idx = list(order[:min(rerank_k, len(order))])
            passages = []
            for i in cand_idx:
                did = d["ids"][int(i)]
                if domain == "doc_page":
                    txt = _doc_text(did)[:800]
                else:
                    txt = _image_caption(did)[:800]
                passages.append(txt or did)
            rr_s = rr.score(query, passages)
            for i, s in zip(cand_idx, rr_s):
                rerank_scores[int(i)] = float(s)
            # reranker 점수로 재정렬 (없는 항목은 fused 순서 유지)
            order = np.array(
                sorted(cand_idx, key=lambda i: -rerank_scores.get(int(i), -1e9))
                + [i for i in order[min(rerank_k, len(order)):]]
            )
        except Exception as e:
            logger.exception(f"[admin] rerank 실패: {e}")

    rows = []
    for rank, i in enumerate(order[:top_n], start=1):
        s = float(dense[i])
        z = (s - mu) / sig
        conf = 0.5 * (1 + math.erf(z / (2 ** 0.5)))
        # [W7-doc-quality] rerank 점수가 있으면 confidence 를 sigmoid(rerank) 로 교체.
        #   - dense-z 기반 conf 는 "군중 대비 높음" 이지 "의미 적합" 이 아님
        #   - cross-encoder logit → sigmoid → 0~1 확률로 UI 와 직관 일치
        rr = rerank_scores.get(int(i))
        if rr is not None:
            conf = 1.0 / (1.0 + math.exp(-float(rr)))
        doc_id = d["ids"][i]
        if domain == "doc_page":
            src, page = _source_doc_path(doc_id)
        else:
            src = _resolve_file_path("image", doc_id)
            page = 0
        rows.append({
            "rank": rank,
            "id": doc_id,
            "filename": Path(src).name if src else Path(doc_id).name,
            "source_path": str(src) if src else "",
            "page": page,
            "dense": s,
            "lexical": float(lex[i]) if lex is not None else None,
            "asf": float(asf_s[i]) if asf_s is not None else None,
            "rrf": float(rrf[i]),
            "fused": float(fused[i]),
            "rerank": rerank_scores.get(int(i)),
            "confidence": conf,
            "z_score": z,
        })

    return jsonify({
        "domain": domain,
        "query": query,
        "total": n,
        "returned": len(rows),
        "calibration": {"mu_null": mu, "sigma_null": sig,
                        "abs_threshold": abs_thr},
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
    """도메인별 파일 서빙 (image 썸네일 / audio·video 플레이어).

    AV 도메인은 conditional=True 로 HTTP Range 응답을 지원해
    브라우저 seek 가능하게 한다.
    """
    doc_id = request.args.get("id", "").strip()
    domain = request.args.get("domain", "doc_page")
    if not doc_id:
        return jsonify({"error": "id 필수"}), 400
    p = _resolve_file_path(domain, doc_id)
    if not p or not p.exists():
        return jsonify({"error": "file not found"}), 404
    # AV 는 Range 필수 (대용량 영상 seek)
    if domain in ("movie", "music"):
        import mimetypes as _mt
        mime, _ = _mt.guess_type(str(p))
        return send_file(str(p), mimetype=mime or "application/octet-stream",
                         conditional=True)
    return send_file(str(p))


# ── AV 전수 검사 ────────────────────────────────────────────────────────
@bp_admin.post("/inspect_av")
def inspect_av():
    """Movie/Music 전수 검사 — 파일 단위 집계 + 상위 세그먼트 반환.

    body: {query, domain(movie|music), top_n=30, top_segments=5}
    """
    body = request.get_json(force=True)
    query = body.get("query", "").strip()
    domain = body.get("domain", "music")
    top_n = int(body.get("top_n", 30))
    top_segs = int(body.get("top_segments", 5))

    if not query:
        return jsonify({"error": "query 필수"}), 400
    if domain not in ("movie", "music"):
        return jsonify({"error": "AV 전용 — movie/music 만 허용"}), 400

    e = _engine()
    if domain not in e._cache:
        return jsonify({"error": f"domain {domain} 캐시 없음"}), 400

    res = e.search_av(query, domain=domain, topk=top_n, top_segments=top_segs)
    cal = calibration.get_thresholds(domain)
    mu = cal.get("mu_null", 0.0)
    sig = max(cal.get("sigma_null", 1.0), 1e-9)
    abs_thr = cal.get("abs_threshold", 0.0)

    files = []
    for rank, r in enumerate(res, start=1):
        z = (r.score - mu) / sig
        # segments 에 rank 부여
        segs_with_rank = []
        for i, s in enumerate(r.segments, start=1):
            sd = dict(s)
            sd["rank"] = i
            segs_with_rank.append(sd)
        files.append({
            "rank": rank,
            "file_path": r.file_path,
            "file_name": r.file_name,
            "score": round(float(r.score), 4),
            "confidence": round(float(r.confidence), 4),
            "z_score": round(float(z), 3),
            "segments": segs_with_rank,
        })

    N_total = len(e._cache[domain]["segments"])
    return jsonify({
        "domain": domain,
        "query": query,
        "total": N_total,
        "returned": len(files),
        "calibration": {"mu_null": mu, "sigma_null": sig,
                        "abs_threshold": abs_thr},
        "files": files,
    })


@bp_admin.get("/ui")
def admin_ui():
    """관리자 UI (HTML 카드 그리드). /api/admin/ui 로 접근.

    파일은 App/admin_ui/admin.html (독립 폴더). 백엔드는 단순 서빙만 수행.
    별도 standalone 실행도 가능: App/admin_ui/serve.py.
    """
    ui_dir = Path(__file__).resolve().parents[2] / "admin_ui"
    return send_from_directory(str(ui_dir), "admin.html")


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
            # [W6-AV] 프런트엔드가 AV 카드/검색 경로를 분기할 수 있도록 kind 부여
            "kind": "av" if dom in ("movie", "music") else "text",
        }
    return jsonify(out)


@bp_admin.route("/search-by-image", methods=["POST"])
def search_by_image():
    """이미지 파일을 업로드하여 유사 이미지를 검색."""
    import tempfile
    if "image" not in request.files:
        return jsonify({"error": "이미지 파일이 없습니다."}), 400

    file = request.files["image"]
    domain = request.form.get("domain", "image")
    topk = int(request.form.get("topk", 20))

    # 임시 파일로 저장하여 엔진에 전달
    suffix = Path(file.filename).suffix if file.filename else ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        file.save(tmp.name)
        tmp_path = Path(tmp.name)

    try:
        results = _engine().search_by_image(tmp_path, domain=domain, topk=topk)
        out = []
        for r in results:
            out.append({
                "id": r.id,
                "score": round(r.score, 4),
                "confidence": round(r.confidence, 4),
                "metadata": r.metadata
            })
        return jsonify({"results": out})
    finally:
        tmp_path.unlink(missing_ok=True)   # 임시 파일 삭제
