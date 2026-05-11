import json
import os
import platform
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
    # [v9] top_k <= 0 → 무제한 (매칭된 모든 결과 반환).
    #   신뢰도/정확도/유사도 계산이 정확해지면서 무관한 결과는 자체적으로
    #   낮은 점수로 후순위에 위치 → top_k 자르기보다 모든 매칭 노출이 더 직관적.
    #   향후 top_k=n 선택 UI 추가 시 0 = "전체 보기" 의미로 사용.
    if top_k <= 0:
        top_k = 10**6   # 실질 무제한 (메모리 안전한 큰 값)

    # [Phase 3 v3] 자연어 노이즈 제거 — 어미/조사/동사 제거 후 명사구 보존.
    # "재정건전화법안에 대한 입법과제와 쟁점이 정리된 자료를 찾아줘"
    # → "재정건전화법안 입법과제 쟁점 자료 정리" (doc 매칭 향상).
    _NOISE_PATTERNS = [
        "에 대한", "에 관한", "에 관련된", "을 위한", "를 위한",
        "을 찾아줘", "를 찾아줘", "을 찾아", "를 찾아",
        "이 있나", "가 있나", "이 있을까", "가 있을까", "이 있어", "가 있어",
        "보고싶어", "보여줘", "알려줘", "찾아봐", "필요해",
        "이 정리된", "가 정리된", "이 포함된", "가 포함된",
        " 좀 ", " 좀", " 같은 ", " 같은",
    ]
    _q_clean = query
    for pat in _NOISE_PATTERNS:
        _q_clean = _q_clean.replace(pat, " ")
    _q_clean = " ".join(_q_clean.split())
    if not _q_clean:
        _q_clean = query

    # 한↔영 양방향 쿼리 확장 — sparse/ASF 채널이 다국어 토큰 모두 커버
    # (BGE-M3 dense 는 다국어 OK 지만 sparse 는 정확 토큰 매칭만)
    try:
        from services.query_expand import expand_bilingual
        expanded_query = expand_bilingual(_q_clean)
    except Exception:
        expanded_query = _q_clean

    try:
        results: list[dict] = []

        # [v16] 사용자 요구: 단일 도메인 탭은 100건 cap (전체 검색은 도메인 20 + 합계 100)
        _SINGLE_DOMAIN_CAP = 100
        _single_topk = min(top_k, _SINGLE_DOMAIN_CAP)

        if file_type == "image":
            # [v18.3] adaptive abs_thr 로 엔진 단에서 후보 확보 → topk는 기본값 유지.
            # [v18.9] lexical ON → 0건 이면 dense-only 재시도 (캡션 부족 쿼리 대응).
            results = _search_trichef(expanded_query, ["image"], _single_topk)
            if not results:
                results = _search_trichef(expanded_query, ["image"], _single_topk,
                                          _dense_only=True)
            # [v22] 이미지 탭 단독에도 MPLC 적용 — 전체 탭과 confidence 수준 동일화.
            # 이미지 탭은 MPLC 없이 raw CDF만 사용 → 전체 탭보다 6%p 낮아 저신뢰도 필터에 걸림.
            # 전체 탭: apply_mplc_to_results → query_intent_boost 순서와 동일하게 적용.
            try:
                from services.mplc_scoring import apply_mplc_to_results, MPLC_WEIGHTS
                if MPLC_WEIGHTS and results:
                    apply_mplc_to_results({"image": results}, expanded_query)
            except Exception:
                pass
        elif file_type == "doc":
            results = _search_trichef(expanded_query, ["doc_page"], _single_topk)
        elif file_type == "video":
            # TRI-CHEF AV 우선 → 캐시 없으면 구형 ChromaDB fallback
            results = _search_trichef_av(expanded_query, ["movie"], _single_topk)
            if not results:
                results = _search_legacy_video(expanded_query, _single_topk)
        elif file_type == "audio":
            # TRI-CHEF AV 우선 → 캐시 없으면 구형 ChromaDB fallback
            results = _search_trichef_av(expanded_query, ["music"], _single_topk)
            if not results:
                results = _search_legacy_audio(expanded_query, _single_topk)
        elif file_type == "bgm":
            results = _search_bgm(expanded_query, _single_topk)

        # [v21] 도메인 탭 공통 query_intent_boost — 전체 탭과 동일한 신뢰도 수준 유지.
        # 문제: 도메인 탭은 query_intent_boost 없이 raw CDF confidence 사용 →
        #   "고양이"(이미지탭) ~18%, 전체탭 ~21% — 저신뢰도 필터(20%)에 걸려 숨겨짐.
        # 해결: 단독 도메인 탭 검색 후 해당 도메인의 boost 를 즉시 적용.
        #   boost=1.0(무관 쿼리)이면 변화 없음. boost>1.0 이면 전체탭과 동일하게 상승.
        if file_type and file_type != "bgm":
            try:
                from services.mplc_scoring import query_intent_boost as _qib
                _dom_key = file_type  # "image" | "doc" | "video" | "audio"
                _boost = _qib(query, _dom_key)
                if _boost > 1.0:
                    for _r in results:
                        _c = float(_r.get("confidence", 0) or 0)
                        _r["_rank_score"] = _c * _boost
                        _r["confidence"]  = round(min(1.0, _c * _boost), 4)
                        if "similarity" in _r:
                            _r["similarity"] = _r["confidence"]
            except Exception:
                pass
        else:
            # ════════════════════════════════════════════════════════════════
            # [v10 전체 검색] 5도메인 병렬 실행 + CMP 통합 ranking + cap.
            # ════════════════════════════════════════════════════════════════
            # 변경 요지:
            #  1. 5 도메인 검색을 ThreadPoolExecutor 로 병렬 실행 → 응답 시간 단축
            #     (GPU 추론은 GIL 보호 + lock 으로 자연 직렬화, I/O+sparse 는 병렬).
            #  2. 각 도메인 결과에 CMP 적용 (Calibrated Match Probability) →
            #     도메인 무관 [0,1] 비교 가능 + CMP < 0.40 자동 제외 ('없음').
            #  3. 통합 ranking 은 CMP 단일 기준 (도메인 가중치 X) → 5도메인 결과
            #     가 합리적으로 섞임. 한 도메인이 독식 안 함.
            #  4. cap: 도메인당 max 100, 전체 max 500 (일반화 가능).
            from concurrent.futures import ThreadPoolExecutor
            from services.cmp_scoring import apply_cmp_to_results, CMP_THRESHOLD_NONE

            # [v16] 사용자 요구: 각 도메인 20, 전체 100 (응답 속도 우선).
            #   이전 v15.2 (도메인 100, 전체 500) 은 cross-encoder rerank 부하로
            #   GPU OOM / 타임아웃 발생. 응답 안정성 우선으로 cap 5배 축소.
            DOMAIN_OPTIMAL_TOPK = {
                "doc":   20,
                "image": 20,
                "video": 20,
                "audio": 20,
                "bgm":   20,
            }
            # 합계 max 100
            DOMAIN_CAP_BY_DOMAIN = dict(DOMAIN_OPTIMAL_TOPK)
            TOTAL_CAP  = min(top_k, 100)
            DOMAIN_CAP = max(DOMAIN_CAP_BY_DOMAIN.values())

            # ── 1. 5도메인 병렬 검색 (GPU+CPU 활용, 도메인별 최적 cap) ──
            def _img():   return _search_trichef(expanded_query, ["image"],    DOMAIN_CAP_BY_DOMAIN["image"])
            def _doc():   return _search_trichef(expanded_query, ["doc_page"], DOMAIN_CAP_BY_DOMAIN["doc"])
            def _video():
                v = _search_trichef_av(expanded_query, ["movie"], DOMAIN_CAP_BY_DOMAIN["video"])
                return v or _search_legacy_video(expanded_query, DOMAIN_CAP_BY_DOMAIN["video"])
            def _audio():
                a = _search_trichef_av(expanded_query, ["music"], DOMAIN_CAP_BY_DOMAIN["audio"])
                return a or _search_legacy_audio(expanded_query, DOMAIN_CAP_BY_DOMAIN["audio"])
            def _bgm():   return _search_bgm(expanded_query, DOMAIN_CAP_BY_DOMAIN["bgm"])

            with ThreadPoolExecutor(max_workers=5, thread_name_prefix="search") as ex:
                fut_img = ex.submit(_img)
                fut_doc = ex.submit(_doc)
                fut_vid = ex.submit(_video)
                fut_aud = ex.submit(_audio)
                fut_bgm = ex.submit(_bgm)
                img_only = fut_img.result() or []
                doc_only = fut_doc.result() or []
                video    = fut_vid.result() or []
                audio    = fut_aud.result() or []
                bgm      = fut_bgm.result() or []
                # [DEBUG] 검색 직후 각 도메인 건수 로깅
                try:
                    import datetime as _dtt2
                    _dbg2 = r"C:\yssong\KDT-FT-team3-Chainers\DB_insight\av_debug.log"
                    with open(_dbg2, "a", encoding="utf-8") as _lf2:
                        _vid_lines = ""
                        for _vi, _vr in enumerate(video[:10]):
                            _vid_lines += (
                                f"  video[{_vi}]: conf={_vr.get('confidence')} "
                                f"dense={_vr.get('dense')} prebst={_vr.get('prebst_cosine')} "
                                f"name={_vr.get('file_name','?')[:50]}\n"
                            )
                        if not video:
                            _vid_lines = "  video: EMPTY\n"
                        _lf2.write(
                            f"[{_dtt2.datetime.now()}] PARALLEL 결과: q={query[:40]!r} "
                            f"img={len(img_only)} doc={len(doc_only)} "
                            f"vid={len(video)} aud={len(audio)} bgm={len(bgm)}\n"
                            + _vid_lines
                        )
                except Exception:
                    pass

            # [v18.9] image dense-only fallback (직렬 실행, 스레드 충돌 없음).
            # lexical ON 이 per-query adaptive abs_thr 를 과도하게 올려 이미지
            # 캡션 텍스트 부족 쿼리("햄버거" 등)에서 0건 반환 시 dense-only 재시도.
            if not img_only:
                try:
                    img_only = _search_trichef(
                        expanded_query, ["image"], DOMAIN_CAP_BY_DOMAIN["image"],
                        _dense_only=True,
                    )
                except Exception:
                    pass

            # ── 2. [v13.1 MPLC default + BSWS 환경변수 toggle] ─────────────
            # MPLC v13.1: Multi-feature logistic regression + image hand-tune.
            #   80케이스 검증 합격률 86% (baseline 79% +7%, FAIL 0).
            # BSWS: Bragg-Scherrer Weighted Score — Occam's razor 단순 공식.
            #   Hyperparameters 3개로 audio cluster 자동 페널티 시도. 검증
            #   결과 79% (baseline 동률, MPLC 미달) — 자산 보존만.
            # 환경변수 OMC_USE_BSWS=1 이면 BSWS 시도 (실험 용).
            import os as _os
            results_by_domain_pre = {
                "doc":   doc_only, "image": img_only,
                "video": video,    "audio": audio,
                "bgm":   bgm,
            }
            # [v18.10] query_intent_boost 는 BSWS/MPLC 양쪽 경로 모두 필요 (HIGH-1 fix)
            from services.mplc_scoring import query_intent_boost
            if _os.environ.get("OMC_USE_BSWS", "").strip() == "1":
                from services.bsws_scoring import apply_bsws_to_results
                apply_bsws_to_results(results_by_domain_pre, query)
                # [HIGH-2 fix] BSWS 경로도 _rank_score 초기화 + intent boost 적용
                for lst in results_by_domain_pre.values():
                    for r in lst:
                        r["_rank_score"] = float(r.get("confidence", 0) or 0)
                for dom, lst in results_by_domain_pre.items():
                    _boost = query_intent_boost(query, dom)
                    if _boost > 1.0:
                        for r in lst:
                            c = float(r.get("confidence", 0) or 0)
                            r["_rank_score"] = c * _boost
                            r["confidence"] = round(min(1.0, c * _boost), 4)
            else:
                from services.mplc_scoring import (
                    apply_mplc_to_results, MPLC_WEIGHTS,
                )
                if MPLC_WEIGHTS:
                    # [v17] Cross-lingual fix: pass bilingual-expanded query so
                    # keyword_count fires for English queries that match Korean content.
                    # e.g. "artificial intelligence" → expanded_query includes "인공지능"
                    # → f5 (keyword_count) = 1.0 instead of 0.0 → MPLC scores doc correctly.
                    # query_intent_boost still uses original query (domain language detection).
                    apply_mplc_to_results(results_by_domain_pre, expanded_query)
                # [Phase 3 v2] Query intent boost — 자연어 도메인 키워드 매칭 시
                # 해당 도메인 confidence × full domain_relevance (1.0~2.0).
                # cut 없이 ranking 만 영향. v16 (boost+cut) 회귀의 교훈으로
                # cut 제거 + boost 만 full 적용.
                #
                # [v17.2] _rank_score 분리: min(1.0, c*boost) 클리핑으로
                #   서로 다른 도메인 boost가 동일 1.0에 몰려 ranking 구분 불가 문제 수정.
                #   _rank_score = c*boost (언캡, 정렬 전용)
                #   confidence  = min(1.0, c*boost) (캡, UI 표시용)
                for lst in results_by_domain_pre.values():
                    for r in lst:
                        r["_rank_score"] = float(r.get("confidence", 0) or 0)
                for dom, lst in results_by_domain_pre.items():
                    boost = query_intent_boost(query, dom)   # 1.0~2.0 (original query)
                    if boost <= 1.0:
                        continue
                    for r in lst:
                        c = float(r.get("confidence", 0) or 0)
                        r["_rank_score"] = c * boost           # uncapped — for sort
                        r["confidence"] = round(min(1.0, c * boost), 4)

            for lst in (img_only, doc_only, video, audio, bgm):
                lst.sort(key=lambda r: r.get("_rank_score", r.get("confidence", 0)), reverse=True)

            base_quota = max(1, TOTAL_CAP // 10)
            def _max_conf(lst):
                return float(lst[0].get("_rank_score", lst[0].get("confidence", 0.0))) if lst else 0.0
            def _adj_quota(mc):
                if mc >= 0.80: return base_quota * 2
                if mc >= 0.50: return base_quota
                if mc >= 0.30: return max(1, base_quota // 2)
                return 1
            # [v18] 의도 매칭 없는 도메인은 guaranteed 슬롯 최대 2개로 제한.
            # "글로벌 XR 활용 동향" 같은 doc 쿼리에서 music/bgm 99% 유사도로
            # guaranteed 20슬롯을 독식하는 cross-domain 오염 방지.
            _intent_map = {
                "doc":   query_intent_boost(query, "doc"),
                "image": query_intent_boost(query, "image"),
                "video": query_intent_boost(query, "video"),
                "audio": query_intent_boost(query, "audio"),
                "bgm":   query_intent_boost(query, "bgm"),
            }

            # [v18.9] BGM/Audio 비음악 쿼리 보정 — z-score CDF 인플레이션 방지.
            # 문제: BGM/Audio 의 confidence 는 domain 내 z-score CDF (상대적 순위) 라서
            #   비음악 쿼리에서도 절대적으로 높은 값(0.70+)이 나와 cross-domain 비교 시
            #   관련 doc/video 를 밀어냄.
            #   예: "경주 동궁" → BGM CLAP cosine 0.31 → CDF 0.71 → doc(0.33) 보다 높아
            #       BGM 가 guaranteed #1 점유.
            # 수정: 음악 의도 없는 쿼리에서 BGM/Audio _rank_score = min(cdf, raw_dense).
            #   raw_dense 는 절대 cosine 이므로 cross-domain 비교에 공정.
            #   (음악 의도 있는 쿼리는 boost > 1.0 이므로 이 보정 미적용)
            # [CRITICAL-2 fix] raw_dense 는 후처리(score_adjust)에서 설정되므로
            # 이 시점엔 아직 없음 → dense 필드(각 검색함수가 설정)를 fallback으로 사용.
            for _bgm_r in bgm:
                if _intent_map.get("bgm", 1.0) <= 1.0:
                    # [E13 fix v2] prebst_cosine(부스트 전 cosine) 우선 — 오디오 CDF 인플레이션 방지.
                    # raw_dense = dense_agg(부스트 후) 이므로 AV 인플레이션 보정에 부적합.
                    _raw = float(_bgm_r.get("prebst_cosine") or _bgm_r.get("raw_dense") or _bgm_r.get("dense") or 0)
                    _bgm_r["_rank_score"] = min(float(_bgm_r.get("_rank_score", 0)), _raw)
                    # [v18.11] confidence 도 함께 보정 — 프론트 confidence 정렬 시에도 BGM 과대 노출 방지
                    for _f in ("confidence", "similarity"):
                        if _f in _bgm_r and _bgm_r[_f] is not None:
                            _bgm_r[_f] = round(min(float(_bgm_r[_f]), _raw), 4)
            for _aud_r in audio:
                if _intent_map.get("audio", 1.0) <= 1.0:
                    # [E13 fix v2] prebst_cosine(부스트 전 cosine) 우선 — 오디오 CDF 인플레이션 방지.
                    _raw = float(_aud_r.get("prebst_cosine") or _aud_r.get("raw_dense") or _aud_r.get("dense") or 0)
                    _aud_r["_rank_score"] = min(float(_aud_r.get("_rank_score", 0)), _raw)
                    # [v18.11] confidence 도 함께 보정
                    for _f in ("confidence", "similarity"):
                        if _f in _aud_r and _aud_r[_f] is not None:
                            _aud_r[_f] = round(min(float(_aud_r[_f]), _raw), 4)

            # [v18.10] 비음악 쿼리에서 audio/bgm 전체 결과 하드 캡 2건.
            # 문제: audio 파일에 "햄버거" 발화가 실제로 있으면 텍스트 임베딩 코사인이
            #   99% 까지 올라감 → raw_dense 도 동일하게 높아 min(x, raw) 보정 효과 없음.
            #   TRI-CHEF AV 스레드 실패 시 legacy 파이프라인으로 폴백 → 0건↔18건 비결정성.
            # 수정: 음악/음성 의도 없는 쿼리에서 audio/bgm 리스트를 상위 2건으로 하드 캡.
            #   guaranteed(2) + extras(0) → 전체 결과에서 최대 2건만 표시.
            #   결과 집합이 안정화되고 이미지/영상이 상위를 차지하게 됨.
            if _intent_map.get("audio", 1.0) <= 1.0:
                audio = audio[:2]
            if _intent_map.get("bgm", 1.0) <= 1.0:
                bgm = bgm[:2]

            # [v18.12] Video 비영상 쿼리 raw_dense 보정 — z-score CDF 인플레이션 방지.
            # 문제: "햄버거" 같은 비영상 쿼리에서 우주 다큐 등 무관 영상의 CDF confidence
            #   가 76-80% 까지 올라가 burger 이미지(35%) 보다 높게 랭크됨.
            # 수정: 영상 의도 없는 쿼리에서 video _rank_score/confidence = min(cdf, raw_dense).
            #   raw_dense 는 절대 cosine → cross-domain 비교 공정.
            # [E13 fix v3] 회귀 수정: raw_dense 가 0.22~0.30 구간인 경우
            #   min(cdf, raw) 로 캡하면 confidence < 0.30(conf floor) 이 되어
            #   _passes_floor 에서 실제 관련 영상까지 제거됨.
            #   (예: "코스모스 보이저호" → NGC E09 raw=0.2764 → conf=0.2764 < 0.30 → 전체 0건)
            #   수정: raw ≥ 0.22 이면 conf cap = max(raw, 0.30) 으로 floor 보장.
            #         raw < 0.22 이면 기존대로 raw 로 캡 (노이즈 제거, _passes_floor 가 처리).
            #   _rank_score 는 raw 로 캡 유지 (cross-domain 순위 보정).
            for _vid_r in video:
                if _intent_map.get("video", 1.0) <= 1.0:
                    _raw = float(_vid_r.get("raw_dense") or _vid_r.get("dense") or 0)
                    if _raw <= 0:
                        continue   # dense 필드 없으면 보정 스킵 (0으로 zeroing 방지)
                    _vid_r["_rank_score"] = min(float(_vid_r.get("_rank_score", 0)), _raw)
                    # [E13 fix v3] conf floor 보장: raw ≥ 0.22 → cap = max(raw, 0.30)
                    _conf_cap = max(_raw, 0.30) if _raw >= 0.22 else _raw
                    for _f in ("confidence", "similarity"):
                        if _f in _vid_r and _vid_r[_f] is not None:
                            _vid_r[_f] = round(min(float(_vid_r[_f]), _conf_cap), 4)

            def _intent_quota(domain_key: str, lst: list) -> int:
                base = _adj_quota(_max_conf(lst))
                if _intent_map[domain_key] > 1.0:
                    return base          # 의도 매칭 → 전체 quota
                return min(2, base)      # 의도 불일치 → 최대 2슬롯
            quotas = {
                "doc":   _intent_quota("doc",   doc_only),
                "image": _intent_quota("image", img_only),
                "video": _intent_quota("video", video),
                "audio": _intent_quota("audio", audio),
                "bgm":   _intent_quota("bgm",   bgm),
            }
            guaranteed: list[dict] = []
            for key, lst in (("doc", doc_only), ("image", img_only),
                             ("video", video), ("audio", audio), ("bgm", bgm)):
                guaranteed.extend(lst[:quotas[key]])

            # [v14] doc 가중치 0.80 하향 — 새 한국어 요약 Im 캐시로 doc MPLC가
            # 과도하게 높아져 extra 슬롯을 독식하는 현상 방지.
            _DOMAIN_W = {"image": 1.0, "doc": 0.80, "video": 0.75,
                          "audio": 0.75, "bgm": 0.75}
            extras: list[dict] = []
            for key, lst in (("doc", doc_only), ("image", img_only),
                             ("video", video), ("audio", audio), ("bgm", bgm)):
                extras.extend(lst[quotas[key]:])
            extras.sort(
                key=lambda r: r.get("_rank_score", r.get("confidence", 0)) *
                              _DOMAIN_W.get(r.get("file_type", ""), 1.0),
                reverse=True,
            )

            # [v18.7] A안: guaranteed slot 보장 복원.
            # 이전 버그: combined.sort() 가 guaranteed/extras 를 한꺼번에 재정렬 →
            #   image cap=0.35 가 video 0.95 에 밀려 image quota(2슬롯)가 무력화 →
            #   "햄버거" 전체 검색 시 image 0 건 회귀.
            # 수정: guaranteed 는 자기들끼리만 _rank_score 정렬 (v14 doc-1위 버그 방지),
            #       extras 는 이미 정렬됨. 둘을 그대로 이어붙여 quota 보장 유지.
            guaranteed.sort(
                key=lambda r: r.get("_rank_score", r.get("confidence", 0)),
                reverse=True,
            )
            combined = guaranteed + extras
            results = combined[:TOTAL_CAP]

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Optional cross-encoder rerank (env-gated, GPU bf16). 비활성/실패 시 원본 유지.
    from services.rerank_adapter import maybe_rerank, _is_enabled as _rr_enabled
    # [v13] 도메인 단독 탭은 rerank pool 을 top_k 로 확대.
    #   문제: 도메인 단독(예: 이미지) 탭에서 default pool=50 이라 부풀려진 신뢰도로
    #   head 50 개가 채워지면 진짜 매칭(IMG_1357 박스 안 고양이 등)이 tail(51~100)
    #   에 갇혀 cross-encoder 영향을 못 받음 → 사자상/강아지/인형이 ranking 상위.
    #
    #   전체 탭은 5도메인 mix + quota 분배로 head 다양성 확보되므로 default(50) 유지.
    #   비용 영향: 도메인 탭 cross-encoder GPU 추론 ~2배 (+0.5~1초/쿼리).
    # [BGM 회귀 수정 2026-05-08] BGM 결과는 cross-encoder rerank 제외.
    #   배경: BGM 메타데이터 ("artist · title · tags") 가 짧아 cross-encoder 가
    #   처리 실패 또는 NaN 반환 → 정렬 후 결과 0건으로 회귀.
    #   해결: BGM 제외. BGM 매칭은 CLAP audio-text cosine 자체가 신뢰 가능.
    _rerank_pool = top_k if file_type in ("image", "doc", "video", "audio") else None
    results = maybe_rerank(query, results, top_k_pool=_rerank_pool)

    # [v6] 재순위 후 관련성 하한 필터 — reranker 활성 시만 작동.
    # 도메인 보장 쿼터(guaranteed slot)에 의해 포함된 비관련 결과가 상위 노출되는
    # 문제 해결 (예: '경주 시굴 조사' 검색에 '실크로드 영상' 등장).
    # rerank_score < -5.0 → sigmoid((-5+3)/3) ≈ 0.25 (관련성 25% 미만) → 제거.
    # reranker 비활성 또는 rerank_score 없는 항목은 영향 없음 (default=0.0 ≥ -5.0).
    #
    # [v6 패치] AV 도메인(movie/music) 면제 —
    #   AV passage 는 STT 한 segment 의 짧은 텍스트(한국어 자막 일부)라
    #   cross-encoder logit 이 본질적으로 낮음(-5~-10 흔함).
    #   파일명 매칭(+1.5 부스트)으로 이미 final score 가 충분히 높은
    #   NGC 코스모스 E02~E12 같은 결과까지 floor 에 걸려 사라지는 부작용 발생.
    #   AV 도메인은 file_path 기반 의미 매칭이 더 강하므로 floor 면제.
    if _rr_enabled():
        _RERANK_FLOOR = -5.0
        _STRONG_DENSE_CONF = 0.70  # dense+sparse 강매칭 임계값
        def _keep_after_rerank(r):
            # [v8] AV(movie/music) + BGM: passage 가 STT 일부라 reranker 점수가
            #   본질적으로 낮음 → 면제.
            if r.get("file_type") in ("video", "audio", "bgm"):
                return True
            # [v9→v19] image: 정상 신뢰도(confidence > 0.35) 이미지는 면제 유지.
            #   단, fallback 이미지(confidence ≤ 0.35, 임계값 미통과)는
            #   rerank_score < -3.0 이면 제거 — 비관련 음식 사진 등 필터링 (전체 탭).
            #   [v20] 이미지 탭 단독 검색(file_type=="image")은 query_intent_boost 없이
            #   confidence 가 낮고, 사용자가 명시적으로 이미지를 선택했으므로
            #   AV 처럼 rerank floor 완전 면제 → 이미지 탭 0건 회귀 방지.
            if r.get("file_type") == "image":
                # [v20] 이미지 탭 단독 검색: 완전 면제 (AV 동일).
                #   이미지 캡션은 짧아 cross-encoder 가 모든 이미지에 -5.0 이하를 줌.
                #   floor 적용 시 실제 관련 이미지까지 대거 제거됨 (100건→6건 회귀).
                #   이미지 탭에서 결과 수 보존 > 비관련 이미지 필터링 우선.
                if file_type == "image":
                    return True
                # 전체 탭: fallback 이미지(conf ≤ 0.35)에 엄격한 -3.0 floor 적용
                _IMAGE_FALLBACK_CAP = 0.351
                _IMAGE_FALLBACK_FLOOR = -3.0
                if float(r.get("confidence") or 0.0) <= _IMAGE_FALLBACK_CAP:
                    return r.get("rerank_score", 0.0) >= _IMAGE_FALLBACK_FLOOR
                return True   # 정상 신뢰도 이미지 면제
            # doc: dense conf 가 강매칭(>=0.70) 이면 rerank floor 완화 (어린이 doc 정상화).
            #   doc 은 page 단위 텍스트가 충분히 길어서 cross-encoder 신호 신뢰 가능.
            # [v18.10 fix] 단, rerank 가 극단적으로 낮으면(-10.0 이하 = 정확도 ~6% 미만)
            #   high confidence 여도 false positive 로 판정하여 제거.
            #   예: "햄버거" 검색 → "자기소개서.pdf" confidence=0.95 지만 rerank≈-11 → 제거.
            _ABSOLUTE_RERANK_FLOOR = -10.0
            if float(r.get("confidence") or 0.0) >= _STRONG_DENSE_CONF:
                return r.get("rerank_score", 0.0) >= _ABSOLUTE_RERANK_FLOOR
            return r.get("rerank_score", 0.0) >= _RERANK_FLOOR
        results = [r for r in results if _keep_after_rerank(r)]

        # [v18.10] rerank_score 를 최종 정렬에 반영 — 필터(제거)뿐 아니라 순위에도 사용.
        # 문제: _rank_score(MPLC)는 reranker 실행 전에 결정 → reranker가 무관하다 판정해도
        #   순위는 변하지 않음. 프론트 "종합순위" 는 백엔드 순서를 따르므로 이 순서가 중요.
        # 수정: reranker 활성 시 doc + image 결과에 대해 _rank_score 를 conf+rerank 혼합으로 갱신.
        #   video/audio/bgm 은 STT passage 가 짧아 reranker 신호가 본질적으로 낮음 → 변경 없음.
        #   혼합 비율: conf 40% + rerank_sigmoid 60% → reranker 판단이 순위에 강하게 반영.
        # 예시:
        #   무관한 doc(conf=0.95, rerank=-11) → sig(-11)=0.065 → new_score=0.419
        #   관련 doc  (conf=0.85, rerank=+3)  → sig(+3) =0.88  → new_score=0.868
        # [v18.14] image 도 rerank 블렌드 추가:
        #   고양이 캐릭터 인형(rerank=28%) vs 박스 속 고양이(rerank=78%) →
        #   dense(유사도)만 보면 인형이 1위이지만 rerank 반영 후 실제 고양이가 1위.
        import math as _math
        def _rr_sigmoid(x: float) -> float:
            return 1.0 / (1.0 + _math.exp(-((x + 3.0) / 3.0)))
        _rerank_updated = False
        for r in results:
            rr = r.get("rerank_score")
            if rr is not None and r.get("file_type") in ("doc", "image"):
                mplc = float(r.get("_rank_score", r.get("confidence", 0)) or 0)
                r["_rank_score"] = 0.4 * mplc + 0.6 * _rr_sigmoid(float(rr))
                _rerank_updated = True
        if _rerank_updated:
            results.sort(
                key=lambda r: r.get("_rank_score", r.get("confidence", 0)),
                reverse=True,
            )

    # 5도메인 통합 score 조정
    # TRI-CHEF(image/doc/video/audio): 엔진이 이미 per-query z-score CDF [0,1] 출력
    #   → generous_curve 이중 적용 금지. 쿼리 품질 페널티만 적용.
    # BGM: 엔진 z-score CDF + 0.75 상한 (비음악 쿼리 오버랭크 방지)
    # dense (raw cosine): generous_curve 적용 (UI 유사도 표시용)
    #
    # 페널티 판정은 확장된 쿼리로 수행:
    #   '꽃'(1글자) → '꽃 flower flowers blossom' → meaningful ≫ 2 → 0.55 cap 해제
    try:
        from services.score_adjust import apply_query_penalty, _generous_curve, hermitian_display_curve as _hermitian_curve
        from services.query_expand import expand_bilingual as _expand
        _penalty_q = _expand(query)   # 확장 쿼리로 n_meaningful 재계산
        for r in results:
            if r.get("file_type") == "bgm":
                for f in ("confidence", "similarity"):
                    if f in r and r[f] is not None:
                        r[f] = round(min(0.75, float(r[f])), 4)
                continue
            # TRI-CHEF 도메인: CDF 값에 쿼리 페널티만
            for f in ("confidence", "similarity"):
                if f in r and r[f] is not None:
                    r[f] = round(apply_query_penalty(float(r[f]), _penalty_q), 4)
            # dense: 표시용 커브 적용 (원본 raw Hermitian 보존)
            if "dense" in r and r["dense"] is not None:
                # [E13 fix v2] AV 결과는 raw_dense 를 설정하지 않음(prebst_cosine 별도 보관).
                # score_adjust 에서 raw_dense = dense(=dense_agg, 부스트 후) 로 설정.
                # → _passes_floor 0.22 floor / 영상 의도보정 캡에 dense_agg 값 사용.
                # prebst_cosine 은 _passes_floor >1.05 체크 / 오디오 인플레이션 캡에만 사용.
                if "raw_dense" not in r or r["raw_dense"] is None:
                    r["raw_dense"] = r["dense"]      # [v18.3] 원본 cosine 보존
                if r.get("file_type") == "image":
                    # [v18.11] image: Hermitian 전용 커브 적용
                    # null_mu≈0.286 → 20%, 강한매칭 0.40 → 85%
                    r["dense"] = round(_hermitian_curve(r["dense"]), 4)
                else:
                    r["dense"] = round(_generous_curve(r["dense"]), 4)
    except Exception as _sa_err:
        try:
            import traceback as _tb, datetime as _dt
            _sa_log = r"C:\Users\sjowu\AppData\Roaming\DB_insight\sa_debug.log"
            with open(_sa_log, "a", encoding="utf-8") as _lf:
                _lf.write(
                    f"[{_dt.datetime.now()}] score_adjust FAIL: {_sa_err}\n"
                    f"{_tb.format_exc()}\n---\n"
                )
        except Exception:
            pass

    # [v18.13] Video content-mismatch fail-safe cap.
    # 목적: v18.12 dense_agg-기반 cap 이 식품-식품 고유사도(곰탕↔햄버거 BGE-M3 ≈0.99)
    #       등으로 우회될 때, cross-encoder rerank 극단적 부정 신호로 확실히 차단.
    # threshold -4.6: 실측 곰탕 영상(-4.81) 제거, 코스모스 E02~E12(-4.0 내외) 보존.
    # _passes_floor: video conf < 0.30 → 자동 제거.
    # 주의: rerank_score 미존재(reranker 비활성) 시 0.0 → 이 필터 미적용.
    for _vfc_r in results:
        if _vfc_r.get("file_type") != "video":
            continue
        if float(_vfc_r.get("rerank_score") or 0.0) < -4.6:
            for _vf in ("confidence", "similarity"):
                if _vf in _vfc_r and _vfc_r[_vf] is not None:
                    _vfc_r[_vf] = round(min(float(_vfc_r[_vf]), 0.25), 4)

    # 위치 정보(location) 부착 — 페이지+라인(doc) / 타임코드+텍스트(video/audio).
    # image 는 None → location 키 자체 생략.
    # query 전달 → doc 결과는 매칭 줄 + snippet 도 함께 부착.
    from services.location_resolver import extract_location
    for r in results:
        loc = extract_location(r, query=query)
        if loc is not None:
            r["location"] = loc
            # doc: snippet 이 비어있으면 location.snippet 으로 backfill
            if not r.get("snippet") and loc.get("snippet"):
                r["snippet"] = loc["snippet"]
            # doc: page_num backfill
            if r.get("page_num") is None and loc.get("page"):
                r["page_num"] = loc["page"]

    # [v11] 다중 신호 floor — confidence + similarity + raw dense cosine.
    #   문제: 신뢰도(MPLC)는 keyword_count weight로 부풀려져 무관한 결과도 95%+
    #         가 되지만 유사도(raw cosine) 는 keyword 매칭에 영향받지 않음.
    #   해결: confidence + similarity + (AV/BGM 한정) raw dense cosine 모두 검사.
    #
    #   예: "코스모스 보이저호" → 무관한 doc 신뢰도 97% / 유사도 69% / raw 0.55
    # [v18.3] _passes_floor 단순화.
    # ─────────────────────────────────────────────────────────────────────────
    # 이전 3중 floor (_DOMAIN_MIN_CONF + _DOMAIN_MIN_SIM + _DOMAIN_MIN_DENSE) 의 문제:
    #   1. _DOMAIN_MIN_SIM 은 generous_curve 후 warped 값에 적용 → 실제 cosine 기준 불명확
    #   2. 쿼리 타입별로 cosine 범위가 달라 특정 단어 검색 시 계속 수동 튜닝 필요
    #   3. _DOMAIN_MIN_DENSE 도 cosine_top1 없으면 warped dense 로 fallback → 버그
    #
    # 개선:
    #   • image: unified_engine 에서 per-query adaptive abs_thr 적용 (v18.3).
    #            결과가 이미 쿼리 분포 기준 상위권 → 추가 SIM floor 불필요.
    #            노이즈 후처리: visual_check (아래).
    #   • doc  : calibration abs_thr (static) + reranker 가 품질 게이트 담당.
    #   • video: search_av per-query calibration + cosine_top1 floor.
    #   • audio: search_av per-query calibration + audio_check (아래).
    #   • bgm  : CLAP 기반 별도 경로.
    #
    # 남기는 것: (1) conf 최소 게이트 — 완전 무관 결과 제거
    #            (2) raw cosine 무결성 — 임베딩 불량/0 값 차단
    #            (3) video cosine_top1 floor — AV 노이즈 컷
    _DOMAIN_MIN_CONF = {
        "image": 0.10,   # adaptive abs_thr 이후라 낮게 유지. visual_check 후처리 담당.
        "doc":   0.15,   # reranker 후처리 담당
        # AV는 per-query z-score CDF → 무관 결과 conf 10~25%, 관련 결과 60~100%.
        # 0.30 floor: 평균 미만 파일 제거. 음성/영상 쿼리는 명사가 직접 매칭되면 80%+.
        "video": 0.30,
        "audio": 0.30,
        "bgm":   0.25,
    }
    # raw cosine 무결성 floor — image/doc/bgm 만 적용.
    # [v18.8] video/audio raw floor 완전 제거 (v18.6 상태로 회귀):
    #   - cosine_top1 ≥ 0.30 (v18.7) 이 정상 결과까지 컷하는 회귀 발생
    #     ("코스모스 보이저호" all-domain video=0 — E13 voyager 결과까지 사라짐).
    #   - dense_agg (raw_dense) 는 NGC 코스모스 전 에피소드 ≥0.50 이라 floor 효과 X.
    #   - 결론: video/audio 는 conf floor (0.30) 만으로 게이트.
    #     "핵융합 실크로드" 같은 일부 노이즈는 감수.
    _DOMAIN_MIN_RAW = {
        # [v22] 이미지 탭 단독: 0.16 → 0.13 완화.
        #   단일어 쿼리("고양이")는 dense similarity가 구조적으로 낮아 실제 고양이 이미지도 0.14~0.16.
        #   SigLIP2 random noise ~0.14 이므로 0.13이면 noise 제거하면서 recall 확보 가능.
        #   전체 탭 이미지: MPLC 후 ranking으로 이미 필터링되므로 유지.
        "image": 0.13 if file_type == "image" else 0.16,
        "doc":   0.25,   # BGE-M3 noise ~0.20 (raw_dense)
        "bgm":   0.30,   # CLAP cosine (raw_dense)
    }

    def _passes_floor(r: dict) -> bool:
        ftype = r.get("file_type", "")
        conf  = float(r.get("confidence") or 0)
        raw   = float(r.get("raw_dense") or 0)

        # 0) 물리적 상한 체크 — cosine similarity 는 이론상 ≤1.0.
        #    video/audio: prebst_cosine (부스트 전 실제 cosine ≤1.0) 로 체크.
        #      dense_agg(부스트 후)가 1.0 초과 가능하지만 prebst_cosine 은 항상 ≤1.0.
        #      raw_dense = dense_agg 이므로 raw>1.05 체크에서 오탐 발생 방지.
        #    image/doc/bgm: raw_dense 는 커브 적용 전 cosine → 1.05 초과 시 버그 데이터.
        if ftype in ("video", "audio"):
            _prebst = float(r.get("prebst_cosine") or 0)
            if _prebst > 1.05:
                return False
        else:
            if raw > 1.05:
                return False

        # 1) 신뢰도 최소 게이트
        if conf < _DOMAIN_MIN_CONF.get(ftype, 0.10):
            return False

        # 2) raw cosine 무결성 — image/doc/bgm 전용 (video/audio 면제)
        if ftype not in ("video", "audio"):
            min_raw = _DOMAIN_MIN_RAW.get(ftype, 0)
            if min_raw > 0 and raw > 0 and raw < min_raw:
                return False

        # 3) [v18.9] video/audio mild raw floor — dense 유사도가 극히 낮은
        #    허위 매칭 차단 (예: "핵융합 발전" 쿼리에 실크로드 다큐 raw=0.31 진입).
        #    - 0.22 기준: NGC 코스모스 보이저호 raw=0.71 ✅ 보존
        #                 0.22 미만 결과만 제거 (사실상 노이즈)
        #    - video/audio 공통 적용.
        if ftype in ("video", "audio") and 0 < raw < 0.22:
            return False

        return True

    results = [r for r in results if _passes_floor(r)]
    # [DEBUG] _passes_floor 이후 도메인별 건수
    try:
        import datetime as _dtt3
        _dbg3 = r"C:\yssong\KDT-FT-team3-Chainers\DB_insight\av_debug.log"
        from collections import Counter as _Ctr
        _ftypes = _Ctr(r.get("file_type","?") for r in results)
        with open(_dbg3, "a", encoding="utf-8") as _lf3:
            _lf3.write(f"[{_dtt3.datetime.now()}] AFTER _passes_floor: {dict(_ftypes)}\n")
    except Exception:
        pass

    # [v15] 시각 일치성 검증 — 캡션 거짓말 케이스 차단 (image 도메인).
    # [v18.3] visual_check 전 최대 12건으로 캡 → SigLIP2 per-image 추론 과부하 방지.
    #   adaptive abs_thr 로 후보 품질이 충분하므로 12건이면 실제 반환 건수 커버 가능.
    try:
        from services.visual_check import filter_by_visual_match
        _vc_top   = sorted(results, key=lambda r: float(r.get("confidence") or 0), reverse=True)[:12]
        _vc_top_ids = {id(r) for r in _vc_top}
        _vc_rest  = [r for r in results if id(r) not in _vc_top_ids]
        _vc_top   = filter_by_visual_match(_vc_top, query, use_bayes=False)
        results   = _vc_top + _vc_rest
    except Exception:
        pass

    # [Phase E-2] audio 도메인 BGE-M3 일치성 검증 — z-score CDF 부풀림 차단.
    #   "보이저호" 검색 시 무관 다스뵈이다 등 100건이 dense 98%+ 부풀려지는 케이스.
    #   audio_check.py 에서 BGE-M3 raw cosine 직접 측정 → noise 분포 대비 페널티.
    try:
        from services.audio_check import filter_by_audio_match
        results = filter_by_audio_match(results, query)
    except Exception:
        pass

    # [v15-sweep] 정렬 키 env var 토글 — OMC_SORT_VARIANT (A/B/C/D/E/F/G/H).
    #   A (default, v14.1): (dense, rerank, conf)
    #   B: (rerank, dense, conf)
    #   C: (rerank, dense)
    #   D: (dense, rerank)
    #   E: (conf, rerank, dense)  — 옛날 설정 회귀
    #   F: 0.5·dense + 0.5·rerank
    #   G: 0.4·dense + 0.6·rerank
    #   H: 0.7·rerank + 0.3·dense
    import os as _os_sort
    _variant = _os_sort.environ.get("OMC_SORT_VARIANT", "A").strip().upper()

    def _r_norm(r):
        # rerank_score → sigmoid 로 0~1 정규화. None 은 0.
        rs = r.get("rerank_score")
        if rs is None:
            return 0.0
        try:
            import math
            return 1.0 / (1.0 + math.exp(-(float(rs) + 3.0) / 3.0))
        except Exception:
            return 0.0

    def _sort_key(r):
        # [v18.10] _rank_score 를 primary key 로 사용.
        # 이유: _rank_score 는 MPLC + intent boost + BGM/Audio raw_dense 보정 +
        #   doc rerank blend 를 모두 반영한 최적값.
        #   기존 primary key 였던 dense 는 generous_curve 적용 여부가 도메인마다
        #   달라 cross-domain 비교가 불공정함 (BGM=raw CLAP, image=curved).
        rank = float(r.get("_rank_score", r.get("confidence", 0)) or 0)
        ds = float(r.get("dense") or 0)
        rs_raw = r.get("rerank_score")
        rs = float(rs_raw) if rs_raw is not None else -999.0
        cf = float(r.get("confidence") or 0)
        rs_n = _r_norm(r)
        if _variant == "B":
            return (rs, ds, cf)
        if _variant == "C":
            return (rs, ds)
        if _variant == "D":
            return (ds, rs)
        if _variant == "E":
            return (cf, rs, ds)
        if _variant == "F":
            return (0.5 * ds + 0.5 * rs_n,)
        if _variant == "G":
            return (0.4 * ds + 0.6 * rs_n,)
        if _variant == "H":
            return (0.7 * rs_n + 0.3 * ds,)
        # A (default): _rank_score → dense → rerank
        return (rank, ds, rs)

    results.sort(key=_sort_key, reverse=True)

    # [v7] 최종 top_k 컷 — combined[:top_k*2] dedup 여유분으로 받았으나
    # 사용자 요청 top_k 정확히 맞춰 반환. (이전 v6 까지는 자르지 않아 30 요청에
    # 47건 반환되는 비직관적 동작 발생.)
    results = results[:top_k]

    # [JSON 안전성] NaN/inf → null 치환 (frontend "Unexpected token N" 오류 방지).
    import math as _math
    def _sanitize_nan(x):
        if isinstance(x, float):
            if _math.isnan(x) or _math.isinf(x):
                return None
            return x
        if isinstance(x, dict):
            return {k: _sanitize_nan(v) for k, v in x.items()}
        if isinstance(x, list):
            return [_sanitize_nan(v) for v in x]
        return x
    results = _sanitize_nan(results)

    return jsonify({"query": query, "results": results})


# ── TRI-CHEF 이미지·문서 검색 ──────────────────────────────────────

def _search_trichef(query: str, domains: list[str], top_k: int, _dense_only: bool = False) -> list[dict]:
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
            # [v18.9] _dense_only=True: 이미지 캡션 부족 쿼리 fallback 용 dense-only.
            _lex = not _dense_only
            _asf = not _dense_only
            hits = engine.search(query, domain=domain, topk=top_k,
                                 use_lexical=_lex, use_asf=_asf, pool=200)
        except Exception:
            continue
        for hit in hits:
            rid = hit.id
            if domain == "image":
                file_type = "image"
                reg_entry = img_reg.get(rid, {})
                # [v9 PC 호환] registry 의 'abs' 필드는 인덱싱한 PC 의 절대경로라
                # 다른 PC 에서 깨짐. rel_key + 현재 RAW_DB 로 매번 결합.
                from services.path_resolver import resolve_raw_path
                orig_path = resolve_raw_path(rid, "image", reg_entry)
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
                "z_score":        conf,         # image/doc: confidence 값을 z_score 로 노출
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
        except Exception as _av_ex:
            try:
                import traceback as _tb, datetime as _dtt
                _dbg = r"C:\yssong\KDT-FT-team3-Chainers\DB_insight\av_debug.log"
                with open(_dbg, "a", encoding="utf-8") as _lf:
                    _lf.write(f"[{_dtt.datetime.now()}] search_av EXCEPTION: domain={domain} q={query[:60]}\n{_tb.format_exc()}\n---\n")
            except Exception:
                pass
            continue

        if not av_res:
            # [DEBUG] AV 검색 결과 0건 — 로그 기록
            try:
                import datetime as _dtt
                _dbg = r"C:\yssong\KDT-FT-team3-Chainers\DB_insight\av_debug.log"
                with open(_dbg, "a", encoding="utf-8") as _lf:
                    _lf.write(f"[{_dtt.datetime.now()}] search_av 0건: domain={domain} q={query[:60]}\n")
            except Exception:
                pass

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
            # [v9 PC 호환] r.file_path 가 절대경로(인덱싱 PC) 또는 rel_key 인 경우
            # 모두 처리. abs 면 rel_key 추출 후 현재 RAW_DB 로 재결합.
            from services.path_resolver import resolve_raw_path
            _fp = r.file_path or ""
            _fp_norm = _fp.replace("\\", "/")
            # rel_key 추출: raw_DB/<domain>/ 이후 부분
            _domain_dir = "Movie" if file_type == "video" else "Rec"
            _marker = f"/raw_DB/{_domain_dir}/"
            if _marker in _fp_norm:
                _rel = _fp_norm.split(_marker, 1)[1]
            else:
                _rel = _fp_norm  # 이미 rel_key 형태
            file_path = resolve_raw_path(_rel, file_type)
            results.append({
                "file_path":      file_path,
                "file_name":      r.file_name,
                "file_type":      file_type,
                "confidence":     conf,
                "similarity":     conf,    # 하위 호환
                "snippet":        snippet,
                "preview_url":    preview_url,
                "segments":       r.segments,
                "trichef_domain": av_domain,
                # 점수 상세 (UI 메트릭 표시용)
                "dense":          round(float(av_meta.get("dense_agg",     0.0)), 4),
                # [E13 fix v2] prebst_cosine = 부스트 전 실제 cosine (≤1.0).
                # raw_dense 는 score_adjust 에서 dense(=dense_agg) 로 설정 — 0.22 floor/의도보정 캡에 사용.
                # prebst_cosine 은 _passes_floor raw>1.05 오탐 방지 + 오디오 인플레이션 캡에만 사용.
                "prebst_cosine":  round(float(av_meta.get("raw_dense_agg", 0.0)), 4),
                "cosine_top1":    round(float(av_meta.get("cosine_top1",   0.0)), 4),  # raw segment max cosine
                "z_score":        round(float(av_meta.get("z_dense",       0.0)), 4),
                "asf":            round(float(av_meta.get("asf_agg",       0.0)), 4),
                "lexical":        round(float(av_meta.get("sparse_agg",    0.0)), 4),
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
            "dense":       round(h["similarity"], 4),  # [CRITICAL-1 fix] raw_dense 설정용
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
            "dense":       round(h["similarity"], 4),  # [CRITICAL-1 fix] raw_dense 설정용
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
    """캡션 파일(json 또는 txt)에서 캡션 텍스트 읽기.

    탐색 순서:
      1. stem_key_for(key) 기반 해시 스템 (신포맷)
      2. Path(key).stem 단순 스템 (구포맷 — real_cat_31.txt 등)
    """
    def _is_clean(text: str) -> bool:
        """CJK 통합 한자(U+4E00-U+9FFF) 비율 >5% 이면 오염 텍스트로 판단."""
        if not text:
            return False
        n = len(text)
        cjk = sum(1 for c in text if "一" <= c <= "鿿")
        return (cjk / n) <= 0.05

    def _try_stems(stems):
        for stem in stems:
            for suffix in (f"{stem}.caption.json", f"{stem}.txt"):
                p = cap_root / suffix
                if p.exists():
                    try:
                        if suffix.endswith(".json"):
                            d = json.loads(p.read_text(encoding="utf-8"))
                            txt = d.get("L1") or ""
                        else:
                            txt = p.read_text(encoding="utf-8")[:300]
                        if _is_clean(txt):
                            return txt
                    except Exception:
                        pass
        return None

    # 1. 해시 포함 신포맷 스템
    try:
        from embedders.trichef.doc_page_render import stem_key_for
        hash_stem = stem_key_for(key)
    except Exception:
        hash_stem = key.replace("/", "_").replace("\\", "_")

    # 2. 단순 스템 (파일명에서 확장자 제거)
    simple_stem = Path(key).stem

    result = _try_stems([hash_stem])
    if result is None and simple_stem != hash_stem:
        result = _try_stems([simple_stem])
    base_text = result or ""

    # [v17] tags_kr stage 파일 포함 — Qwen 생성 한국어 키워드 → keyword_count feature 활성화.
    # key = "YS_1차/img.jpg" → stage파일 = "YS_1차__img.jpg_tags_kr.txt"
    # keyword_count(image) weight=0.86: 쿼리어가 tags_kr에 있으면 +0.86 logit → 이미지 MPLC ↑
    try:
        safe_key = key.replace("/", "__").replace("\\", "__")
        tags_path = cap_root / f"{safe_key}_tags_kr.txt"
        if tags_path.exists():
            tags_kr = tags_path.read_text(encoding="utf-8", errors="replace").strip()
            if tags_kr:
                return (base_text + " " + tags_kr).strip()
    except Exception:
        pass

    return base_text


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

    # [v9 PC 호환] registry 의 'abs' / 'abs_aliases' 는 인덱싱한 PC 의 절대경로라
    # 다른 PC 에서 깨짐. rel_key + 현재 RAW_DB 로 매번 결합 (resolve_raw_path).
    from services.path_resolver import resolve_raw_path

    # 1. 신포맷 (hash 포함)
    for rel_key, info in doc_reg.items():
        if not isinstance(info, dict):
            continue
        if stem_key_for(rel_key) == stem_key:
            orig = resolve_raw_path(rel_key, "doc", info)
            return orig, Path(rel_key).name

    # 2. 구포맷 — hash 제거된 raw stem_key 일 가능성
    # (예: "2015 건강보험_국세DB연계_취업통계연보")
    base_key = stem_key.rsplit("__", 1)[0] if "__" in stem_key else stem_key
    for rel_key, info in doc_reg.items():
        if not isinstance(info, dict):
            continue
        rel_stem = Path(rel_key).stem
        if _sanitize(rel_stem) == base_key or rel_stem == base_key:
            orig = resolve_raw_path(rel_key, "doc", info)
            return orig, Path(rel_key).name

    # 3. abs 경로 stem 매칭 — 옛 registry 가 abs 만 가진 케이스 fallback.
    #    rel_key 의 Path(...).stem 으로 base_key 매칭 후 동적 결합.
    for rel_key, info in doc_reg.items():
        if not isinstance(info, dict):
            continue
        if Path(rel_key).stem == base_key:
            return resolve_raw_path(rel_key, "doc", info), Path(rel_key).name

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

def _resolve_open_path(file_path: str) -> str:
    raw_path = (file_path or "").strip()
    if not raw_path:
        return ""

    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(os.path.abspath(str(candidate)))
    if candidate.exists():
        return os.path.normpath(str(candidate))

    # BGM 검색 결과는 filename 만 들고 올 수 있으므로 raw 폴더를 한 번 더 확인.
    try:
        from services.bgm import bgm_config
        bgm_candidate = bgm_config.RAW_BGM_DIR / Path(raw_path).name
        if bgm_candidate.exists():
            return os.path.normpath(str(bgm_candidate))
    except Exception:
        pass

    return os.path.normpath(str(candidate))


def _validate_open_path(file_path: str) -> tuple[str | None, tuple[dict, int] | None]:
    resolved_path = _resolve_open_path(file_path)
    if not resolved_path:
        return None, ({"error": "파일 경로가 없습니다."}, 400)
    if not os.path.exists(resolved_path):
        return None, ({"error": "파일이 존재하지 않습니다."}, 404)
    return resolved_path, None


def _open_with_default_app(target_path: str) -> None:
    system = platform.system()
    if system == "Windows":
        os.startfile(target_path)
    elif system == "Darwin":
        subprocess.Popen(["open", target_path])
    else:
        subprocess.Popen(["xdg-open", target_path])


def _open_in_file_explorer(target_path: str) -> None:
    system = platform.system()
    if system == "Windows":
        if os.path.isdir(target_path):
            os.startfile(target_path)
        else:
            # explorer 는 `/select,"C:\path with spaces\file.ext"` 형태의
            # 단일 command line 을 더 안정적으로 해석한다.
            subprocess.Popen(f'explorer.exe /select,"{target_path}"')
        return

    if system == "Darwin":
        if os.path.isdir(target_path):
            subprocess.Popen(["open", target_path])
        else:
            subprocess.Popen(["open", "-R", target_path])
        return

    folder_path = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
    subprocess.Popen(["xdg-open", folder_path or target_path])

@search_bp.post("/files/open")
def file_open():
    """POST /api/files/open  body: { "file_path": "C:/..." }"""
    data = request.get_json(silent=True) or {}
    file_path, error = _validate_open_path(data.get("file_path", ""))
    if error:
        body, status = error
        return jsonify(body), status

    try:
        _open_with_default_app(file_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"success": True, "file_path": file_path})


@search_bp.post("/files/open-folder")
def folder_open():
    """POST /api/files/open-folder  body: { "file_path": "C:/..." }

    탐색기에서 해당 파일을 선택한 상태로 부모 폴더를 엽니다.
    Windows: `explorer /select,<file>` 를 하나의 인자로 전달합니다.
    경로가 디렉터리이면 부모 + select 가 의미 없으므로 그냥 디렉터리를 엽니다.
    """
    data = request.get_json(silent=True) or {}
    file_path, error = _validate_open_path(data.get("file_path", ""))
    if error:
        body, status = error
        return jsonify(body), status

    try:
        _open_in_file_explorer(file_path)
    except Exception as e:
        fallback = os.path.dirname(file_path) or file_path
        try:
            _open_with_default_app(fallback)
        except Exception:
            return jsonify({"error": str(e)}), 500
    return jsonify({"success": True, "file_path": file_path})
