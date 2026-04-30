"""services/trichef/unified_engine.py — 3 도메인 검색 통합 엔진.

Search flow: query → expand → 3축 쿼리 임베딩 → Hermitian → threshold → top-K.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from config import PATHS, TRICHEF_CFG
from embedders.trichef import siglip2_re
from embedders.trichef import bgem3_caption_im as e5_caption_im  # v2 P1: e5→BGE-M3 호환 alias
from embedders.trichef import bgem3_sparse  # v2 P2: lexical channel
from scipy import sparse as sp
from services.trichef import asf_filter, auto_vocab, calibration, qwen_expand, tri_gs
from services.trichef import snippet  # [항목4] preview 추출

logger = logging.getLogger(__name__)


@dataclass
class TriChefResult:
    id: str
    score: float
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TriChefAVResult:
    """Movie/Music 검색 결과 — 파일 단위 집계 + 하이라이트 세그먼트 목록."""
    file_path: str
    file_name: str
    domain: str              # "movie" | "music"
    score: float
    confidence: float
    segments: list[dict]     # 상위 매칭 세그먼트 (start_sec, end_sec, text, score)
    metadata: dict[str, Any] = field(default_factory=dict)


class TriChefEngine:
    """3축 복소수 검색 엔진. 이미지/문서/영상/음원 재사용 가능."""

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        # 이미지
        idir = Path(PATHS["TRICHEF_IMG_CACHE"])
        if (idir / "cache_img_Re_siglip2.npy").exists():
            self._cache["image"] = self._build_entry(
                idir, "cache_img_Re_siglip2.npy", "cache_img_Im_e5cap.npy",
                "cache_img_Z_dinov2.npy", "img_ids.json", "cache_img_sparse.npz",
                domain_label="image",
            )
        # 문서 페이지
        ddir = Path(PATHS["TRICHEF_DOC_CACHE"])
        if (ddir / "cache_doc_page_Re.npy").exists():
            self._cache["doc_page"] = self._build_entry(
                ddir, "cache_doc_page_Re.npy", "cache_doc_page_Im.npy",
                "cache_doc_page_Z.npy", "doc_page_ids.json", "cache_doc_page_sparse.npz",
                domain_label="doc_page",
            )
        # Movie / Music (AV) — MR_TriCHEF 로 분리됨. PATHS 키 없으면 skip.
        mv_path = PATHS.get("TRICHEF_MOVIE_CACHE")
        if mv_path:
            mdir = Path(mv_path)
            if (mdir / "cache_movie_Re.npy").exists():
                self._cache["movie"] = self._build_av_entry(mdir, "movie")
        mu_path = PATHS.get("TRICHEF_MUSIC_CACHE")
        if mu_path:
            mudir = Path(mu_path)
            if (mudir / "cache_music_Re.npy").exists():
                self._cache["music"] = self._build_av_entry(mudir, "music")
        logger.info(f"[engine] 캐시 로드 완료: {list(self._cache.keys())}")

        # 캘리브레이션 파일이 없는 도메인은 self-calibration 자동 실행.
        # 이렇게 하면 최초 임베딩 이후 abs_threshold 가 실제 점수 범위에 맞춰진다.
        self._auto_calibrate_missing()

    def _auto_calibrate_missing(self) -> None:
        """캘리브레이션이 없는 도메인에 대해 self-score 기반 자동 보정 실행."""
        calib_data = calibration._load_all()
        for domain, d in self._cache.items():
            if domain in ("movie", "music"):
                continue  # AV 도메인은 segment-vs-segment 점수와 query-vs-segment 점수 범위가
                           # 달라 calibrate_domain 사용 불가 — search_av() 에서 별도 처리
            if domain in calib_data:
                thr = calib_data[domain].get("abs_threshold", 0.5)
                if thr < 0.45:  # 이미 유효한 캘리브레이션이 있음
                    continue
            # 아직 캘리브레이션 없음 → self-pair 분포로 추정
            Re = d["Re"]
            Im = d["Im"]
            Z  = d["Z"]
            if Re.shape[0] < 2:
                continue
            try:
                Im_perp, Z_perp = tri_gs.orthogonalize(Re, Im, Z)
                result = calibration.calibrate_domain(domain, Re, Im_perp, Z_perp)
                logger.info(
                    f"[engine] auto-calibrate {domain}: "
                    f"mu={result['mu_null']:.4f} sigma={result['sigma_null']:.4f} "
                    f"thr={result['abs_threshold']:.4f}"
                )
            except Exception as e:
                logger.warning(f"[engine] auto-calibrate {domain} 실패: {e}")

    def _build_entry(self, dir: Path, re_fn: str, im_fn: str, z_fn: str,
                     ids_fn: str, sparse_fn: str, domain_label: str) -> dict:
        Re = np.load(dir / re_fn)
        ids = json.loads((dir / ids_fn).read_text(encoding="utf-8"))["ids"]
        N = Re.shape[0]
        if len(ids) != N:
            logger.warning(f"[engine:{domain_label}] ids({len(ids)}) != Re({N}); "
                           f"ids를 Re 길이에 맞춰 절단")
            ids = ids[:N] if len(ids) > N else ids + [f"__missing__/{i}" for i in range(N - len(ids))]

        sparse_mat = _load_sparse(dir / sparse_fn)
        if sparse_mat is not None and sparse_mat.shape[0] != N:
            logger.warning(f"[engine:{domain_label}] sparse({sparse_mat.shape[0]}) != Re({N}); "
                           f"sparse 채널 비활성화 (rebuild 필요)")
            sparse_mat = None

        asf_sets = asf_filter.load_token_sets(dir / "asf_token_sets.json")
        if asf_sets and len(asf_sets) != N:
            logger.warning(f"[engine:{domain_label}] asf_sets({len(asf_sets)}) != Re({N}); "
                           f"ASF 채널 비활성화 (rebuild 필요)")
            asf_sets = []

        Im = np.load(dir / im_fn)

        # [Img 3-stage caption fusion] BLIP v2 스타일 L1/L2/L3 캡션 Im 캐시가
        # 모두 존재하면 기존 e5cap 대신 3채널 가중 평균으로 교체.
        # 각 레벨은 BGE-M3 (1024d) 동일 공간이므로 직접 가중 합산 가능.
        # w_L1=0.15 (주제), w_L2=0.25 (키워드), w_L3=0.60 (상세 묘사) — 상세도 비례.
        if domain_label == "image":
            L1p = dir / "cache_img_Im_L1.npy"
            L2p = dir / "cache_img_Im_L2.npy"
            L3p = dir / "cache_img_Im_L3.npy"
            if L1p.exists() and L2p.exists() and L3p.exists():
                L1 = np.load(L1p); L2 = np.load(L2p); L3 = np.load(L3p)
                if L1.shape == L2.shape == L3.shape and L1.shape[0] == Im.shape[0]:
                    w1 = float(TRICHEF_CFG.get("IMG_IM_L1_ALPHA", 0.15))
                    w2 = float(TRICHEF_CFG.get("IMG_IM_L2_ALPHA", 0.25))
                    w3 = float(TRICHEF_CFG.get("IMG_IM_L3_ALPHA", 0.60))
                    tot = max(w1 + w2 + w3, 1e-9)
                    w1, w2, w3 = w1/tot, w2/tot, w3/tot
                    Im_fused = w1 * L1 + w2 * L2 + w3 * L3
                    norms = np.linalg.norm(Im_fused, axis=1, keepdims=True)
                    Im = Im_fused / np.maximum(norms, 1e-9)
                    logger.info(f"[engine:image] L1/L2/L3 3-stage caption fusion "
                                f"활성화 (w=[{w1:.2f},{w2:.2f},{w3:.2f}], "
                                f"shape={Im.shape})")
                else:
                    logger.warning(f"[engine:image] L1/L2/L3 shape mismatch vs Im "
                                   f"{Im.shape} — 3-stage fusion 스킵")

        # [Doc Im_body fusion] PDF 본문 텍스트 Im 캐시가 있으면 caption과 혼합.
        # Im_body = pdfplumber 추출 텍스트 → BGE-M3 (1024d), 같은 공간.
        # Im_fused = α·Im_caption + (1-α)·Im_body  → renormalize
        # α=0.35: 시각 캡션 35%, 본문 텍스트 65% (텍스트 밀도 높은 문서에 유리)
        if domain_label == "doc_page":
            body_path = dir / "cache_doc_page_Im_body.npy"
            if body_path.exists():
                Im_body = np.load(body_path)
                if Im_body.shape == Im.shape:
                    _alpha = float(TRICHEF_CFG.get("DOC_IM_ALPHA", 0.35))
                    Im_fused = _alpha * Im + (1.0 - _alpha) * Im_body
                    norms = np.linalg.norm(Im_fused, axis=1, keepdims=True)
                    Im = Im_fused / np.maximum(norms, 1e-9)
                    logger.info(f"[engine:doc_page] Im_body fusion 활성화 "
                                f"(alpha={_alpha:.2f}, shape={Im.shape})")
                else:
                    logger.warning(f"[engine:doc_page] Im_body shape {Im_body.shape} "
                                   f"!= Im {Im.shape} — fusion 스킵")

        return {
            "Re": Re,
            "Im": Im,
            "Z":  np.load(dir / z_fn),
            "ids": ids,
            "sparse": sparse_mat,
            "vocab": auto_vocab.load_vocab(dir / "auto_vocab.json"),
            "asf_sets": asf_sets,
        }

    def _build_av_entry(self, cache_dir: Path, kind: str) -> dict:
        """Movie/Music 캐시 로드. segments.json을 함께 로드."""
        prefix  = "movie" if kind == "movie" else "music"
        Re      = np.load(cache_dir / f"cache_{prefix}_Re.npy")
        Im_path = cache_dir / f"cache_{prefix}_Im.npy"
        Im      = np.load(Im_path) if Im_path.exists() else Re
        Z_path  = cache_dir / f"cache_{prefix}_Z.npy"
        Z       = np.load(Z_path) if Z_path.exists() else np.zeros_like(Re)

        ids_path  = cache_dir / f"{prefix}_ids.json"
        # [W6-AV] segments.json 파일명 fallback — MR_TriCHEF 계보는 "{prefix}_segments.json"
        #   을 쓰지만 DI 측 기존 파일은 단순 "segments.json". 둘 다 허용.
        segs_path = cache_dir / f"{prefix}_segments.json"
        if not segs_path.exists():
            segs_path = cache_dir / "segments.json"
        ids  = json.loads(ids_path.read_text(encoding="utf-8"))["ids"] if ids_path.exists() else []
        segs = json.loads(segs_path.read_text(encoding="utf-8")) if segs_path.exists() else []
        # [W6-AV] 스키마 정규화 — 일부 세그먼트는 "file"/"t_start"/"t_end" 를 사용.
        #   search_av 는 file_path/file_name/start_sec/end_sec 를 기대하므로 변환한다.
        for s in segs:
            if "file_path" not in s and "file" in s:
                s["file_path"] = s["file"]
            if "file_name" not in s and "file" in s:
                from pathlib import Path as _Pp
                s["file_name"] = _Pp(s["file"]).name
            if "start_sec" not in s and "t_start" in s:
                s["start_sec"] = s["t_start"]
            if "end_sec" not in s and "t_end" in s:
                s["end_sec"] = s["t_end"]

        N = Re.shape[0]
        if len(ids) != N:
            logger.warning(f"[engine:{kind}] ids({len(ids)}) != Re({N}); 절단")
            ids  = ids[:N]
            segs = segs[:N]

        # ASF 자산 로드 (MR_TriCHEF search.py vocab_{kind}.json / {kind}_token_sets.json)
        av_vocab    = auto_vocab.load_vocab(cache_dir / f"vocab_{prefix}.json") \
                      if (cache_dir / f"vocab_{prefix}.json").exists() else {}
        av_asf_sets = asf_filter.load_token_sets(cache_dir / f"{prefix}_token_sets.json") \
                      if (cache_dir / f"{prefix}_token_sets.json").exists() else []
        if av_asf_sets and len(av_asf_sets) != N:
            logger.warning(f"[engine:{kind}] asf_sets({len(av_asf_sets)}) != Re({N}); "
                           f"AV ASF 비활성화 (build_asf_assets 재실행 필요)")
            av_asf_sets = []

        return {"Re": Re, "Im": Im, "Z": Z, "ids": ids, "segments": segs,
                "sparse": None, "vocab": av_vocab, "asf_sets": av_asf_sets}

    def _embed_query(self, query: str) -> tuple[np.ndarray, np.ndarray]:
        variants = qwen_expand.expand(query)
        q_Re = qwen_expand.avg_normalize(siglip2_re.embed_texts(variants))
        q_Im = qwen_expand.avg_normalize(e5_caption_im.embed_query(variants))
        return q_Re, q_Im

    def _embed_query_for_domain(self, query: str, domain: str
                                ) -> tuple[np.ndarray, np.ndarray]:
        """도메인별 쿼리 임베딩 반환.

        모든 도메인 Re = SigLIP2 text (1152d).
        Music Re 축이 SigLIP2 text-encoder 로 통일되어 Movie/Image 와 동일 공간.
        Im = BGE-M3 (1024d) — 언어 의미 채널.
        """
        variants = qwen_expand.expand(query)
        q_Re = qwen_expand.avg_normalize(siglip2_re.embed_texts(variants))
        q_Im = qwen_expand.avg_normalize(e5_caption_im.embed_query(variants))
        return q_Re, q_Im

    def search(self, query: str, domain: str, topk: int = 20,
               use_lexical: bool = True, use_asf: bool | None = None,
               pool: int = 200) -> list[TriChefResult]:
        if use_asf is None:
            use_asf = bool(TRICHEF_CFG.get("USE_ASF_DEFAULT", False))
        if domain not in self._cache:
            logger.warning(f"[engine] 도메인 {domain} 캐시 없음")
            return []

        # 도메인별 lexical/asf 게이팅 (bench v2, 2026-04-25):
        # image 도메인은 sparse/asf 가 dense 대비 -14~-24pp 손해라 화이트리스트에서 제외.
        lex_domains = TRICHEF_CFG.get("LEXICAL_DOMAINS")
        asf_domains = TRICHEF_CFG.get("ASF_DOMAINS")
        if lex_domains is not None and domain not in lex_domains:
            use_lexical = False
        if asf_domains is not None and domain not in asf_domains:
            use_asf = False
        q_Re, q_Im = self._embed_query_for_domain(query, domain)
        d = self._cache[domain]
        q_Z = q_Im
        dense_scores = tri_gs.hermitian_score(
            q_Re[None, :], q_Im[None, :], q_Z[None, :],
            d["Re"], d["Im"], d["Z"],
        )[0]
        dense_order = np.argsort(-dense_scores)

        # v2 P2: sparse lexical 채널
        sparse_scores = None
        rankings = [dense_order[:pool]]
        if use_lexical and d.get("sparse") is not None:
            q_sp = bgem3_sparse.embed_query_sparse(query)
            sparse_scores = bgem3_sparse.lexical_scores(q_sp, d["sparse"])
            rankings.append(np.argsort(-sparse_scores)[:pool])

        # v3 P4: ASF (Attention-Similarity-Filter) 채널
        asf_s = None
        if use_asf and d.get("asf_sets") and d.get("vocab"):
            asf_s = asf_filter.asf_scores(query, d["asf_sets"], d["vocab"])
            if asf_s.any():
                rankings.append(np.argsort(-asf_s)[:pool])

        # ── Weighted min-max fusion (DI_TriCHEF §8.1) ─────────────────────
        # 비활성 채널(max==0) 가중치는 dense 로 자동 이전.
        # RRF 는 §8.2 기준 "참고용"으로만 보존 (정렬 기준 아님).
        fused_scores = _weighted_minmax_fusion(dense_scores, sparse_scores, asf_s)
        combined_order = np.argsort(-fused_scores)
        # RRF 참고값 (메타 제공용)
        rrf_scores = _rrf_merge(rankings, n=len(dense_scores))

        cal = calibration.get_thresholds(domain)
        abs_thr = cal["abs_threshold"]

        # ── Per-query adaptive confidence ──────────────────────────────────
        # null calibration(same-modal cross-pair)과 text-query cross-modal 점수
        # 분포가 달라 직접 비교 불가. 대신 이 쿼리에 대한 dense_scores 분포로
        # confidence 를 정규화 → 모든 도메인이 동일 공식으로 비교 가능해진다.
        # sigma 하한: q_mu * 0.8 (점수가 몰려 있어도 z-score 폭발 방지).
        q_mu  = float(np.mean(dense_scores))
        q_sig = max(float(np.std(dense_scores)), q_mu * 0.8, 1e-6)

        out: list[TriChefResult] = []
        for i in combined_order[: topk * 3]:
            s = float(dense_scores[i])
            if s < abs_thr:
                continue
            z = (s - q_mu) / q_sig
            conf = 0.5 * (1 + math.erf(z / (2 ** 0.5)))
            # [항목3] low_confidence 이중 조건 (PROJECT_PIPELINE_SPEC §9)
            # cosine 점수 약 AND sparse lexical 신호도 없음 → confidence 상한 캡 0.40
            sparse_s = float(sparse_scores[i]) if sparse_scores is not None else None
            weak_evidence = (s < abs_thr * 1.1) and (sparse_s is None or sparse_s < 0.05)
            if weak_evidence:
                conf = min(conf, 0.40)
            meta = {
                "domain": domain, "dense": s, "low_confidence": weak_evidence,
                "fused": round(float(fused_scores[i]), 4),
                "rrf":   round(float(rrf_scores[i]), 4),
            }
            if sparse_scores is not None:
                meta["lexical"] = float(sparse_scores[i])
            if asf_s is not None:
                meta["asf"] = float(asf_s[i])
            out.append(TriChefResult(
                id=d["ids"][i], score=s, confidence=conf, metadata=meta,
            ))
            if len(out) >= topk:
                break

        # ── fallback: threshold 를 통과한 결과가 없을 때 상위 K개를 저신뢰도로 반환 ──
        # 캘리브레이션이 아직 실제 점수 범위에 맞지 않는 경우(새로 임베딩 직후 등)에도
        # 검색 결과가 완전히 비어 빈 화면이 뜨지 않도록 한다.
        if not out:
            logger.info(
                f"[engine:{domain}] threshold({abs_thr:.4f}) 통과 결과 없음 — "
                f"fallback: top-{topk} raw dense score 반환 (low_confidence=True)"
            )
            for i in combined_order[:topk]:
                s = float(dense_scores[i])
                # per-query adaptive confidence (다른 도메인과 동일 공식)
                z = (s - q_mu) / q_sig
                conf = 0.5 * (1 + math.erf(z / (2 ** 0.5)))
                meta = {
                    "domain": domain, "dense": s,
                    "low_confidence": True, "fallback": True,
                }
                out.append(TriChefResult(
                    id=d["ids"][i], score=s, confidence=conf, metadata=meta,
                ))
        return out

    def search_av(self, query: str, domain: str, topk: int = 10,
                  top_segments: int = 5) -> list[TriChefAVResult]:
        """Movie/Music 검색 — MR_TriCHEF search.py 방식으로 정렬.

        집계: 파일 내 top-3 세그먼트 dense 평균 → z-score → ASF 가중 합산.
        최종: final = α·z_dense + γ·asf  (α=0.75, γ=0.25)
        Confidence: sigmoid(final / 2.0)  — MR_TriCHEF WEIGHTS 기준.
        """
        if domain not in self._cache:
            logger.warning(f"[engine] AV 도메인 {domain} 캐시 없음")
            return []

        d = self._cache[domain]
        q_Re, q_Im = self._embed_query_for_domain(query, domain)
        q_Z = q_Im

        seg_scores = tri_gs.hermitian_score(
            q_Re[None, :], q_Im[None, :], q_Z[None, :],
            d["Re"], d["Im"], d["Z"],
        )[0]   # (N,)

        # AV는 null calibration(segment-vs-segment) 대신
        # 이 쿼리에 대한 실제 seg_scores 분포로 per-query 캘리브레이션한다.
        # image/doc 과 동일한 공식 → 전체 검색에서 도메인 간 confidence 비교 가능.
        # sigma 하한: q_mu * 0.8 (image/doc과 동일, z-score 폭발 방지)
        q_mu  = float(seg_scores.mean())
        q_sig = max(float(seg_scores.std()), q_mu * 0.8, 1e-6)
        abs_thr = q_mu   # 평균 미만 파일은 관련 없음으로 처리

        # ASF 세그먼트 점수 (MR_TriCHEF search.py _aggregate 방식)
        asf_seg: np.ndarray | None = None
        if d.get("asf_sets") and d.get("vocab") and len(d["asf_sets"]) == len(d["ids"]):
            try:
                asf_seg = asf_filter.asf_scores(query, d["asf_sets"], d["vocab"])
            except Exception as _ae:
                logger.debug(f"[engine:{domain}] ASF 스코어링 실패: {_ae}")

        # 파일별 세그먼트 인덱스 수집
        # AV는 query-vs-segment 점수가 segment-vs-segment null 분포와 달라
        # abs_thr 기반 하드 필터를 쓰지 않는다 (MR_TriCHEF 원본과 동일).
        file_idx: dict[str, list[int]] = {}
        for i, meta in enumerate(d["segments"]):
            fp = meta.get("file_path", d["ids"][i])
            file_idx.setdefault(fp, []).append(i)

        # MR_TriCHEF WEIGHTS: (α dense, β lexical=0, γ asf)
        _ALPHA, _GAMMA = 0.75, 0.25

        out: list[TriChefAVResult] = []
        for fp, idxs in file_idx.items():
            # ── 파일 내 top-3 dense 평균 (MR_TriCHEF _aggregate) ──────────
            d_ranked = sorted(
                [(i, float(seg_scores[i])) for i in idxs],
                key=lambda x: -x[1],
            )[:3]
            dense_agg = float(np.mean([s for _, s in d_ranked])) if d_ranked else 0.0

            # ── ASF 파일 내 max ────────────────────────────────────────────
            asf_agg = 0.0
            if asf_seg is not None:
                asf_agg = float(max(float(asf_seg[i]) for i in idxs))

            # ── per-query z-score → confidence (이미지/문서와 동일한 공식) ──
            # z > 0: 이 쿼리 대비 평균 이상 관련  z < 0: 평균 이하
            z_dense = (dense_agg - q_mu) / q_sig
            final   = _ALPHA * z_dense + _GAMMA * asf_agg
            conf    = 0.5 * (1.0 + math.erf(z_dense / (2 ** 0.5)))

            # 상위 세그먼트 메타 빌드
            seg_list: list[dict] = []
            for (i, s) in d_ranked[:top_segments]:
                meta = d["segments"][i]
                seg_text = meta.get("stt_text", "") or meta.get("caption", "")
                seg_list.append({
                    "start":   meta.get("start_sec", 0.0),
                    "end":     meta.get("end_sec", 0.0),
                    "score":   round(s, 4),
                    "text":    meta.get("stt_text", ""),
                    "caption": meta.get("caption", ""),
                    "type":    meta.get("type", "stt"),
                    "preview": snippet.extract_best_snippet(seg_text, query),
                })

            # [항목3] low_confidence: 점수 약 AND 텍스트 전혀 없음 (BGM/무음)
            no_text = not any(
                (seg.get("text", "").strip() or seg.get("caption", "").strip())
                for seg in seg_list
            )
            weak_evidence = (dense_agg < abs_thr * 1.1) and no_text
            if weak_evidence:
                conf = min(conf, 0.40)

            best_meta  = d["segments"][d_ranked[0][0]] if d_ranked else {}
            file_name  = best_meta.get("file_name", Path(fp).name)

            out.append(TriChefAVResult(
                file_path=fp,
                file_name=file_name,
                domain=domain,
                score=round(final, 4),
                confidence=round(conf, 4),
                segments=seg_list,
                metadata={
                    "low_confidence": weak_evidence,
                    "dense_agg": round(dense_agg, 4),
                    "z_dense":   round(z_dense, 4),
                    "asf_agg":   round(asf_agg, 4),
                },
            ))
            if len(out) >= topk * 3:
                break

        out.sort(key=lambda x: -x.score)
        return out[:topk]

    def reload(self) -> None:
        """캐시 재로드 (재임베딩 후 호출)."""
        self._cache.clear()
        self._load_all()


def _load_sparse(path: Path):
    if path.exists():
        return sp.load_npz(path)
    return None


def _weighted_minmax_fusion(
    dense: np.ndarray,
    lex: np.ndarray | None,
    asf: np.ndarray | None,
    w_dense: float = 0.60,
    w_lex: float   = 0.25,
    w_asf: float   = 0.15,
) -> np.ndarray:
    """가중 min-max 융합 (DI_TriCHEF §8.1).

    각 채널을 per-query min-max 정규화 후 가중 합산.
    비활성 채널(max==0 또는 None) 가중치는 dense 로 자동 이전.
    """
    eps = 1e-9

    def _norm(x: np.ndarray) -> np.ndarray:
        mn, mx = float(x.min()), float(x.max())
        return (x - mn) / (mx - mn + eps)

    w_d = w_dense
    result = w_d * _norm(dense)

    if lex is not None and float(lex.max()) > 0:
        result = result + w_lex * _norm(lex)
    else:
        result = result + w_lex * _norm(dense)   # dense 로 이전

    if asf is not None and float(asf.max()) > 0:
        result = result + w_asf * _norm(asf)
    else:
        result = result + w_asf * _norm(dense)   # dense 로 이전

    return result


def _rrf_merge(rankings: list[np.ndarray], n: int, k: int = 60) -> np.ndarray:
    """RRF: score(d) = Σ 1 / (k + rank_i(d)). n=전체 corpus 크기."""
    agg = np.zeros(n, dtype=np.float32)
    for order in rankings:
        for rank, idx in enumerate(order):
            agg[int(idx)] += 1.0 / (k + rank + 1)
    return agg
