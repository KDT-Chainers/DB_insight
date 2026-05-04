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

    # 한↔영 양방향 쿼리 확장 — sparse/ASF 채널이 다국어 토큰 모두 커버
    # (BGE-M3 dense 는 다국어 OK 지만 sparse 는 정확 토큰 매칭만)
    try:
        from services.query_expand import expand_bilingual
        expanded_query = expand_bilingual(query)
    except Exception:
        expanded_query = query

    try:
        results: list[dict] = []

        if file_type == "image":
            results = _search_trichef(expanded_query, ["image"], top_k)
        elif file_type == "doc":
            results = _search_trichef(expanded_query, ["doc_page"], top_k)
        elif file_type == "video":
            # TRI-CHEF AV 우선 → 캐시 없으면 구형 ChromaDB fallback
            results = _search_trichef_av(expanded_query, ["movie"], top_k)
            if not results:
                results = _search_legacy_video(expanded_query, top_k)
        elif file_type == "audio":
            # TRI-CHEF AV 우선 → 캐시 없으면 구형 ChromaDB fallback
            results = _search_trichef_av(expanded_query, ["music"], top_k)
            if not results:
                results = _search_legacy_audio(expanded_query, top_k)
        elif file_type == "bgm":
            results = _search_bgm(expanded_query, top_k)
        else:
            # 전체 검색: 이미지·문서·영상·음원·BGM 5도메인 TRI-CHEF + CLAP.
            # [v3] 도메인별 최소 보장 비율 — AV conf 가 dense 0.99 로 매우 높고
            # doc/image conf 가 0.4~0.7 로 낮아, 단순 confidence sort 시 doc/image
            # 가 거의 모두 잘려나가는 문제 해결.
            #   각 도메인 top_k/4 보장 (round-robin), 남는 자리는 score sort.
            img_only  = _search_trichef(expanded_query, ["image"], top_k)
            doc_only  = _search_trichef(expanded_query, ["doc_page"], top_k)
            video     = _search_trichef_av(expanded_query, ["movie"], top_k)
            if not video:
                video = _search_legacy_video(expanded_query, top_k)
            audio     = _search_trichef_av(expanded_query, ["music"], top_k)
            if not audio:
                audio = _search_legacy_audio(expanded_query, top_k)
            bgm       = _search_bgm(expanded_query, top_k)

            # 도메인별 정렬 (각 도메인 내부 confidence 순)
            for lst in (img_only, doc_only, video, audio, bgm):
                lst.sort(key=lambda r: r.get("confidence", 0), reverse=True)

            # 최소 보장: 각 도메인 quota = max(1, top_k // 5) — 5도메인 기준
            quota = max(1, top_k // 5)
            guaranteed: list[dict] = []
            for lst in (doc_only, img_only, video, audio, bgm):
                guaranteed.extend(lst[:quota])

            # 추가 자리: 5도메인 quota 초과한 부분에 대해 score sort
            _DOMAIN_W = {"image": 1.0, "doc": 1.0, "video": 0.75, "audio": 0.75, "bgm": 0.75}
            extras = []
            for lst in (img_only, doc_only, video, audio, bgm):
                extras.extend(lst[quota:])
            extras.sort(
                key=lambda r: r.get("confidence", 0) *
                              _DOMAIN_W.get(r.get("file_type", ""), 1.0),
                reverse=True,
            )

            # 합치기 — guaranteed 먼저, 그 다음 extras (가중 score 순)
            # [v4] dedup 단계에서 file_name 중복으로 결과 줄어들 수 있어 여유분 (×2)
            # 받아서 후속 dedup 후 top_k 까지 채움.
            combined = guaranteed + extras
            results = combined[:top_k * 2]

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Optional cross-encoder rerank (env-gated, GPU bf16). 비활성/실패 시 원본 유지.
    from services.rerank_adapter import maybe_rerank, _is_enabled as _rr_enabled
    results = maybe_rerank(query, results)

    # [v5] 재순위 후 관련성 하한 필터 — reranker 활성 시만 작동.
    # 도메인 보장 쿼터(guaranteed slot)에 의해 포함된 비관련 결과가 상위 노출되는
    # 문제 해결 (예: '경주 시굴 조사' 검색에 '실크로드 영상' 등장).
    # rerank_score < -5.0 → sigmoid((-5+3)/3) ≈ 0.25 (관련성 25% 미만) → 제거.
    # reranker 비활성 또는 rerank_score 없는 항목은 영향 없음 (default=0.0 ≥ -5.0).
    if _rr_enabled():
        _RERANK_FLOOR = -5.0
        results = [r for r in results if r.get("rerank_score", 0.0) >= _RERANK_FLOOR]

    # 5도메인 통합 score 조정
    # TRI-CHEF(image/doc/video/audio): 엔진이 이미 per-query z-score CDF [0,1] 출력
    #   → generous_curve 이중 적용 금지. 쿼리 품질 페널티만 적용.
    # BGM: 엔진 z-score CDF + 0.75 상한 (비음악 쿼리 오버랭크 방지)
    # dense (raw cosine): generous_curve 적용 (UI 유사도 표시용)
    try:
        from services.score_adjust import apply_query_penalty, _generous_curve
        for r in results:
            if r.get("file_type") == "bgm":
                for f in ("confidence", "similarity"):
                    if f in r and r[f] is not None:
                        r[f] = round(min(0.75, float(r[f])), 4)
                continue
            # TRI-CHEF 도메인: CDF 값에 쿼리 페널티만
            for f in ("confidence", "similarity"):
                if f in r and r[f] is not None:
                    r[f] = round(apply_query_penalty(float(r[f]), query), 4)
            # dense: raw cosine → generous_curve
            if "dense" in r and r["dense"] is not None:
                r["dense"] = round(_generous_curve(r["dense"]), 4)
    except Exception:
        pass

    # 위치 정보(location) 부착 — 페이지+라인(doc) / 타임코드+텍스트(video/audio).
    # image 는 None → location 키 자체 생략.
    # query 전달 → doc 결과는 매칭 줄 + snippet 도 함께 부착.
    from services.location_resolver import extract_location
    for r in results:
        loc = extract_location(r, query=query)
        if loc is not None:
            r["location"] = loc

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
            # [#1] admin.html(/api/admin/inspect)과 동일 채널 디폴트로 통일.
            # use_lexical/use_asf=True → BGE-M3 sparse + ASF Attention-Similarity-Filter
            # 두 채널을 dense 와 함께 fusion. LOO R@1 +20pp 가능 (벤치 결과).
            hits = engine.search(query, domain=domain, topk=top_k,
                                 use_lexical=True, use_asf=True, pool=200)
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
                # URL encode rid — 한글/공백/특수문자(+,[,] 등) 처리. + 는 공백으로 디코드되어 깨짐.
                from urllib.parse import quote as _q
                preview_url = f"/api/trichef/file?domain=image&path={_q(rid, safe='/')}"
            else:
                file_type = "doc"
                parts    = Path(rid).parts
                stem_key = parts[1] if len(parts) >= 2 else rid
                orig_path, file_name = _doc_page_to_source(stem_key, doc_reg)
                if not orig_path:
                    orig_path = str(doc_extract / rid)
                    file_name = Path(rid).name
                snippet     = ""
                from urllib.parse import quote as _q
                preview_url = f"/api/trichef/file?domain=doc_page&path={_q(rid, safe='/')}"

            conf     = round(hit.confidence, 4)
            hit_meta = hit.metadata
            dense_v  = round(float(hit_meta.get("dense", 0.0)), 4)
            lex_v    = round(float(hit_meta["lexical"]), 4) if "lexical" in hit_meta else None
            asf_v    = round(float(hit_meta["asf"]), 4) if "asf" in hit_meta else None
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
                # 점수 상세 (UI 메트릭 표시용)
                "dense":          dense_v,
                "lexical":        lex_v,
                "asf":            asf_v,
                "z_score":        None,        # image/doc: engine 내부 계산, 미노출
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

            conf    = round(r.confidence, 4)
            av_meta = r.metadata
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
                # 점수 상세 (UI 메트릭 표시용)
                "dense":          round(float(av_meta.get("dense_agg", 0.0)), 4),
                "z_score":        round(float(av_meta.get("z_dense",   0.0)), 4),
                "asf":            round(float(av_meta.get("asf_agg",   0.0)), 4),
                "lexical":        None,
            })

    results.sort(key=lambda x: -x["confidence"])

    # [중복 제거 v2] 같은 파일이 abs/rel 두 형식으로 dual-registered 된 케이스
    # (Movie/Rec 의 396/232 SHA-중복) 검색 결과 중복 출현 방지.
    # 단순화: file_name (basename) 만으로 dedup. 같은 basename 의 다른 파일이
    # 있을 가능성은 낮고, 있어도 검색 결과에서 첫 매칭 우선이 합리적.
    seen: set = set()
    deduped: list[dict] = []
    for r in results:
        # basename 추출 (file_name 우선, 없으면 file_path 의 마지막 segment)
        fn = r.get("file_name")
        if not fn:
            fp = (r.get("file_path") or "").replace("\\", "/")
            fn = fp.rsplit("/", 1)[-1] if fp else ""
        key = fn.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    return deduped[:top_k]


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

def _search_bgm(query: str, top_k: int) -> list[dict]:
    """BGM CLAP 텍스트 검색 → 통합 스키마로 변환. GPU(RTX 4070) 우선 사용."""
    try:
        from services.bgm.search_engine import get_engine
        from services.bgm import bgm_config as _bgm_cfg
        engine = get_engine()
        if not engine.is_ready():
            return []
        res = engine.search(query, top_k=top_k)
        out = []
        for r in (res.get("results") or []):
            fn = r.get("filename", "")
            fpath = str(_bgm_cfg.RAW_BGM_DIR / fn) if fn else ""
            tags  = r.get("tags") or []
            title = r.get("acr_title") or r.get("guess_title") or ""
            artist = r.get("acr_artist") or r.get("guess_artist") or ""
            snippet = " · ".join(filter(None, [artist, title] + tags[:3]))
            out.append({
                "file_path":    fpath,
                "file_name":    fn,
                "file_type":    "bgm",
                "confidence":   round(float(r.get("confidence", 0)), 4),
                "similarity":   round(float(r.get("confidence", 0)), 4),
                "dense":        round(float(r.get("score", 0)), 4),
                "snippet":      snippet,
                "preview_url":  f"/api/bgm/file?filename={fn}" if fn else None,
                "segments":     r.get("segments", []),
                "guess_artist": r.get("guess_artist", ""),
                "guess_title":  r.get("guess_title", ""),
                "acr_artist":   r.get("acr_artist", ""),
                "acr_title":    r.get("acr_title", ""),
                "duration":     r.get("duration", 0.0),
                "tags":         tags,
            })
        return out
    except Exception:
        return []


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
    """stem_key → (원본 파일 경로, 파일명).

    매칭 우선순위:
      1. 신포맷: stem_key_for(rel_key) == stem_key  (sanitized + __hash)
      2. 구포맷 sanitized: _sanitize(Path(rel_key).stem) == stem_key
      3. 구포맷 raw: Path(rel_key).stem == stem_key
      4. abs 경로 stem 매칭 (이동된 파일 대응)
    """
    if not stem_key:
        return "", ""
    try:
        from embedders.trichef.doc_page_render import stem_key_for, _sanitize
    except Exception:
        return "", ""

    # 1. 신포맷 (hash 포함)
    for rel_key, info in doc_reg.items():
        if not isinstance(info, dict):
            continue
        if stem_key_for(rel_key) == stem_key:
            orig = info.get("abs") or info.get("staged", "")
            return orig, Path(rel_key).name

    # 2. 구포맷 — hash 제거된 raw stem_key 일 가능성
    # (예: "2015 건강보험_국세DB연계_취업통계연보")
    base_key = stem_key.rsplit("__", 1)[0] if "__" in stem_key else stem_key
    for rel_key, info in doc_reg.items():
        if not isinstance(info, dict):
            continue
        rel_stem = Path(rel_key).stem
        if _sanitize(rel_stem) == base_key or rel_stem == base_key:
            orig = info.get("abs") or info.get("staged", "")
            return orig, Path(rel_key).name

    # 3. abs 경로 stem 매칭 (registry rel_key 와 abs 가 다른 경우)
    for rel_key, info in doc_reg.items():
        if not isinstance(info, dict):
            continue
        ap = info.get("abs")
        if ap and Path(ap).stem == base_key:
            return ap, Path(ap).name
        for alias in info.get("abs_aliases") or []:
            if Path(alias).stem == base_key:
                return alias, Path(alias).name

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
    """POST /api/files/open-folder  body: { "file_path": "C:/..." }

    탐색기에서 해당 파일을 선택한 상태로 부모 폴더를 엽니다.
    Windows: `explorer /select,<file>` — 콤마와 경로는 **하나의 인자** 로 전달해야 함.
      * subprocess.Popen(["explorer", "/select,", path]) ← BAD: 콤마/경로가 분리되어
        탐색기가 콤마만 받고 path 를 무시 → 기본 폴더(문서 등)로 엽니다.
      * subprocess.Popen(f'explorer /select,"{path}"', shell=True) ← OK
    경로가 디렉터리이면 부모 + select 가 의미 없으므로 그냥 디렉터리를 엽니다.
    """
    data      = request.get_json(silent=True) or {}
    file_path = data.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    # Windows 백슬래시 정규화 (forward slash 도 explorer 가 받지만 일관성)
    norm_path = os.path.normpath(file_path)

    try:
        if os.path.isdir(norm_path):
            # 디렉터리면 그대로 열기
            os.startfile(norm_path)
        else:
            # 파일 → 부모 폴더 열고 파일 선택. shell=True 로 단일 명령 문자열 전달
            # (큰따옴표로 경로 감싸서 공백/한글 지원).
            subprocess.Popen(f'explorer /select,"{norm_path}"', shell=True)
    except Exception as e:
        # 최종 fallback — 부모 폴더만 열기
        try:
            os.startfile(os.path.dirname(norm_path))
        except Exception:
            return jsonify({"error": str(e)}), 500
    return jsonify({"success": True})
