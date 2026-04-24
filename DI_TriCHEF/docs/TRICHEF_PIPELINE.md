# TRI-CHEF 멀티모달 검색 시스템 — 파이프라인 & 아키텍처

> 생성일: 2026-04-24  
> 범위: 1) Doc/Img vs Movie/Rec 파이프라인 상세도 · 독립성, 3) TRI-CHEF 전용 내용 정리

---

## 1. 파이프라인 상세도

### 1.1 Doc / Img 파이프라인 (텍스트/이미지 기반)

```
[RAW]                [EXTRACT]               [EMBED 3축]              [LEXICAL]              [INDEX]               [SEARCH]
raw_DB/Img/*.jpg → captions/{stem}.txt → Re: SigLIP2 (1152d)  → vocab/ASF/sparse →  .npy cache   → query
raw_DB/Doc/*.pdf →  (PDF text+render)  → Im: BGE-M3 (1024d)   →  (auto_vocab)     → img_ids.json →  dense+lex+asf
                 →  page_images/        → Z : DINOv2-L (1024d) →                   → ChromaDB     →   (RRF merge)
                                          (Gram-Schmidt orth.) →                   → concat 3200d →  calibration gate

모델:
  - 캡셔너:   Qwen2-VL-2B-Instruct (한국어, Wave3 이후 BLIP 대체)
  - Re축:    google/siglip2-so400m-patch14-384 (cross-modal 이미지-텍스트)
  - Im축:    BAAI/bge-m3 dense (다국어 캡션/텍스트)
  - Z축:     facebook/dinov2-large (self-supervised 시각 구조)
  - Sparse:  BAAI/bge-m3 sparse (lemma+subword 레벨 희소 표현)
  - Reranker (선택): BAAI/bge-reranker-v2-m3 (cross-encoder 재순위)

진입점 (App/backend/embedders/trichef/incremental_runner.py):
  - run_image_incremental()    : 신규 이미지 SHA-256 증분 처리
  - run_doc_incremental()      : PDF → 페이지별 렌더 + 캡션 + 원문 텍스트
```

#### 세부 단계 (Image)

| 단계 | 파일 | 모듈/함수 | 비고 |
|---|---|---|---|
| 1. 신규 탐지 | registry.json (SHA-256) | _load_registry, _sha256 | 변경/신규만 처리 |
| 2. 캡션 로드/생성 | captions/{stem}.txt | `_caption_for_im` | Qwen2-VL (W4-B 이후). plain-stem/hash-stem/json 모두 fallback |
| 3. Re 임베딩 | siglip2_re.py | `embed_images` | 384×384 입력, L2-norm |
| 4. Im 임베딩 | bgem3_caption_im.py | `embed_passage` | max_length=1024, L2-norm |
| 5. Z 임베딩 | dinov2_z.py | `embed_images` | 224×224 crop, CLS 토큰 |
| 6. Gram-Schmidt | tri_gs.py | `orthogonalize` | Im_perp, Z_perp 계산 |
| 7. 3축 npy 누적 | cache_img_{Re,Im,Z}.npy | np.vstack | 증분 append |
| 8. ChromaDB upsert | trichef_image 컬렉션 | `_upsert_chroma` | concat 3200d, cosine |
| 9. Lexical rebuild | lexical_rebuild.py | `rebuild_image_lexical` | vocab(2784) + ASF + BGE-M3 sparse |
| 10. Calibration | calibration.py | `calibrate_image_crossmodal` | W4-5, W4-1: 쿼리-doc null 분포 |

#### 세부 단계 (Document)

| 단계 | 파일 | 모듈/함수 | 비고 |
|---|---|---|---|
| 1. PDF 렌더 | doc_page_render.py | `render_pdf` | dpi=110, 페이지별 JPEG |
| 2. 페이지 캡션 | captions/{stem}/p0000.txt | `_caption_for_im` | Qwen2-VL |
| 3. PDF 원문 추출 | PyMuPDF (fitz) | `d.get_text("text")` | 페이지별 |
| 4. 3축 임베딩 | 동일 (Re=SigLIP2, Im=BGE-M3, Z=DINOv2) | | Im 입력 = "캡션\n원문" |
| 5. Lexical | lexical_rebuild.py | `rebuild_doc_lexical` | max_length=2048, vocab top 25000 |

### 1.2 Movie / Rec(Music) 파이프라인 (오디오-비주얼)

```
[RAW]                    [SEGMENT/STT]                [EMBED 3축]                  [INDEX]                [SEARCH]
raw_DB/Movie/*.mp4  → FFmpeg 씬 분할 or      → Re/Im/Z: 세그먼트 텍스트     → segments.json        → query
raw_DB/Rec/*.m4a    →  고정 구간 (예: 30s) →  + 선택적 CLAP (Z축 오디오)  →  cache_{movie,music}_ → search_av
                    → Whisper STT →           Qwen/CLAP Expand 선택적       →   {Re,Im,Z}.npy    →   파일 단위 집계
                    → Qwen 자막 캡션 (선택)                                                        →   top 세그먼트 타임라인

모델:
  - STT:      openai/whisper (large-v3 또는 small)
  - 텍스트:   BGE-M3 dense (Re=Im=Z 모두 동일 1024d — 멀티미디어 쿼리도 텍스트 기반)
  - 선택:     laion/clap-htsat-unfused (오디오 Z축, MR 계보)

진입점:
  - run_movie_incremental()
  - run_music_incremental()

출력 자료구조:
  - cache_music_Re.npy : (N_seg, 1024)
  - music_ids.json     : ["{file_id}#{seg_idx}", ...]
  - segments.json      : [{id, file_path, file_name, start_sec, end_sec, stt_text, caption}, ...]
```

#### 검색 플로우 (search_av)

```
query (예: "웃고 있는 강아지") 
  → _embed_query_for_domain("music") 
     → Music Re 축은 BGE-M3(1024d) 공간: q_Re = q_Im (text→text)
  → hermitian_score(q, all_segments)
  → abs_thr * 0.5 gate (AV 는 임계 절반으로 완화)
  → 파일별 best 세그먼트 집계 (file_best)
  → topk 파일 반환 + 상위 M개 세그먼트 타임라인 동봉
```

### 1.3 독립성 판정

| 항목 | Doc/Img | Movie/Rec |
|---|---|---|
| **진입점 분리** | `run_{image,doc}_incremental` | `run_{movie,music}_incremental` |
| **캐시 분리** | `TRICHEF_IMG_CACHE`, `TRICHEF_DOC_CACHE` | `TRICHEF_MOVIE_CACHE`, `TRICHEF_MUSIC_CACHE` |
| **Chroma 컬렉션** | `trichef_image`, `trichef_doc_page` | `trichef_movie`, `trichef_music` |
| **검색 API** | `engine.search()` | `engine.search_av()` |
| **Re 축 모델** | SigLIP2 (1152d, 이미지-텍스트) | BGE-M3 (1024d, 텍스트) |
| **Lexical(sparse) 채널** | ✅ 활성 | ❌ 미사용 |
| **ASF 필터** | ✅ 활성 | ❌ 미사용 |
| **세그먼트 집계** | ❌ (페이지/이미지 단위) | ✅ 파일/세그먼트 단위 |

**결론**: 두 파이프라인은 **데이터 구조 · 모델 · 검색 로직 모두 독립**이나, **공유 레이어**(hermitian score, calibration, Gram-Schmidt, TriChefEngine dispatch)를 통해 단일 API(`/api/trichef/search`) 뒤에 통합된다.

### 1.4 공유 모듈 매트릭스

| 모듈 | 파일 | Doc/Img | Movie/Rec | 역할 |
|---|---|---|---|---|
| TriChefEngine (dispatch) | services/trichef/unified_engine.py | ✅ | ✅ | domain=image/doc_page/movie/music 라우팅 |
| hermitian_score / orthogonalize | services/trichef/tri_gs.py | ✅ | ✅ | 3축 결합 점수 |
| calibration | services/trichef/calibration.py | ✅ | ✅ | abs_threshold, confidence CDF |
| qwen_expand (쿼리 변형) | embedders/trichef/qwen_expand.py | ✅ | ✅ | paraphrase 평균 |
| shared.reranker (BGE v2-m3) | shared/reranker.py | 선택 | 선택 | cross-encoder top-K 재순위 |
| RRF merge | unified_engine.py `_rrf_merge` | ✅ (Doc/Img 전용) | ❌ | dense/lex/asf 순위 융합 |
| asf_filter, auto_vocab, bgem3_sparse | services/trichef/*, embedders/trichef/bgem3_sparse.py | ✅ | ❌ | lexical 보조 |

---

## 2. TRI-CHEF 전용 내용 정리

### 2.1 디렉토리 구조

```
DB_insight/
├── App/backend/
│   ├── routes/
│   │   ├── trichef.py              # 공개 API (/api/trichef/*)
│   │   └── trichef_admin.py        # admin /inspect (per-row 점수 디버그)
│   ├── services/trichef/
│   │   ├── unified_engine.py       # TriChefEngine, search, search_av
│   │   ├── tri_gs.py               # 3축 점수 수학
│   │   ├── calibration.py          # abs_threshold + crossmodal calibration (W4-1)
│   │   ├── lexical_rebuild.py      # vocab/ASF/sparse 재구축
│   │   ├── auto_vocab.py           # IDF 기반 어휘 추출
│   │   ├── asf_filter.py           # Attention-Similarity-Filter
│   │   └── prune.py                # 제거된 파일 캐시 pruning
│   └── embedders/trichef/
│       ├── incremental_runner.py   # 증분 임베딩 러너 (4개 도메인)
│       ├── siglip2_re.py           # Re 축 (SigLIP2)
│       ├── bgem3_caption_im.py     # Im 축 (BGE-M3 dense)
│       ├── bgem3_sparse.py         # lexical 채널 (BGE-M3 sparse)
│       ├── dinov2_z.py             # Z 축 (DINOv2)
│       ├── qwen_caption.py         # 쿼리/캡션 Qwen 유틸 (quant)
│       ├── qwen_expand.py          # 쿼리 paraphrase
│       ├── blip_caption_triple.py  # (폐기) BLIP L1/L2/L3 triple
│       ├── doc_page_render.py      # PDF → JPEG + stem_key_for 해시
│       ├── doc_ingest.py           # HWP/DOCX → PDF 변환
│       └── caption_io.py           # 캡션 파일 I/O
├── DI_TriCHEF/
│   ├── captioner/
│   │   ├── qwen_vl_ko.py           # Qwen2-VL-2B 한국어 캡셔너 (W3)
│   │   ├── recaption_all.py        # 전체 재캡션 러너
│   │   └── fix_non_korean.py       # 비한국어 선별 재생성
│   └── reranker/
│       ├── post_rerank.py          # non-invasive 재순위 엔진
│       └── rerank_cli.py           # CLI 진입점
├── shared/
│   └── reranker.py                 # BgeRerankerV2 공유 래퍼
└── Data/
    ├── raw_DB/{Img,Doc,Movie,Rec}/
    ├── extracted_DB/{Img,Doc}/captions/
    └── embedded_DB/
        ├── Img/      (cache_img_{Re,Im,Z}.npy, vocab, sparse, ids)
        ├── Doc/      (cache_doc_page_{Re,Im,Z}.npy, ...)
        ├── Rec/      (cache_music_{Re,Im,Z}.npy, segments.json)
        ├── trichef/  (Chroma persistent)
        └── trichef_calibration.json
```

### 2.2 API 엔드포인트 (trichef.py)

| 메서드 | 경로 | 용도 |
|---|---|---|
| POST | `/api/trichef/search` | 멀티도메인 검색 (image/doc_page/movie/music) |
| POST | `/api/trichef/reindex` | scope={image,document,movie,music,all} 증분 |
| GET  | `/api/trichef/file` | 결과 파일 서빙 (path 쿼리) |
| GET  | `/api/trichef/status` | 캐시 현황 |
| GET  | `/api/trichef/image-tags` | 이미지 태그 JSON |
| POST | `/api/admin/inspect` | per-row dense/lex/asf/fused 스코어 (디버그) |

### 2.3 TriChefEngine 내부 구조

```
class TriChefEngine:
    __init__():
        _cache["image"]    = _build_entry(IMG_CACHE)      # 2390장
        _cache["doc_page"] = _build_entry(DOC_CACHE)      # 34170 페이지
        _cache["movie"]    = _build_av_entry(MOVIE_CACHE) # (선택)
        _cache["music"]    = _build_av_entry(MUSIC_CACHE) # (선택)
    
    search(query, domain, topk, use_lexical, use_asf, pool):
        q_Re, q_Im = _embed_query_for_domain(query, domain)
        dense_scores = hermitian_score(q, d)
        sparse_scores = bgem3_sparse.lexical_scores(q_sp, d.sparse)   [옵션]
        asf_s = asf_filter.asf_scores(query, d.asf_sets, d.vocab)     [옵션]
        rankings = [dense, sparse, asf]
        combined = _rrf_merge(rankings)
        gate: dense >= abs_threshold
        return TriChefResult(id, score, confidence, metadata)
    
    search_av(query, domain, topk, top_segments):
        seg_scores = hermitian_score(q, d_all_segments)
        gate: s >= abs_threshold * 0.5
        file_best, segs_list = 파일별 집계
        return TriChefAVResult(file_path, file_name, score, segments[])
```

### 2.4 데이터셋 현재 규모 (2026-04-24 스냅샷)

| 도메인 | raw 파일 | 임베딩 벡터 | 캐시 크기 |
|---|---|---|---|
| Img | **2391** | **2390** (Re 1152d / Im 1024d / Z 1024d) | ~30 MB |
| Doc | 444 (PDF/HWP/DOCX 등) | **34170 페이지** (Re 1152d / Im 1024d / Z 1024d) | ~419 MB |
| Movie | 163 | (STT 세그먼트 기준 가변) | — |
| Rec (Music) | 16 | (STT 세그먼트 기준) | cache_music_*.npy 존재 |

### 2.5 Calibration 현재 상태

```json
{
  "image": {
    "mu_null": 0.1865,
    "sigma_null": 0.0365,
    "abs_threshold": 0.2172,
    "far": 0.2,
    "N": 2390,
    "method": "crossmodal_v1",
    "n_queries": 200,
    "n_pairs": 1000
  }
}
```

`crossmodal_v1`: W4-1 에서 도입. query(SigLIP2 text + BGE-M3) ↔ doc(image feature) null pair 분포로 측정한다. 이전 `doc-doc self-similarity` 방식은 cross-modal 스케일을 과대추정하는 버그가 있어 폐기.

### 2.6 Wave 히스토리 (적용 순서)

| Wave | 내용 | 주요 산출물 |
|---|---|---|
| Wave1 | 공유 reranker / DI admin inspect 옵션 / DINOv2 Z축 / MR CLAP Z축 / MR sparse / MR qwen_expand 스캐폴드 | shared/reranker.py, DI_TriCHEF/ |
| Wave2 | 14장 샘플 Qwen 한국어 캡션 품질 검증 | Chinese leak 0 |
| Wave3 | Qwen 전체 재캡션 2340장 → BGE-M3 Im 재임베드 → vocab/ASF/sparse 재구축 → ChromaDB 3200d upsert → calibration 측정 | cache/trichef 전면 갱신 |
| Wave4 | `_caption_for_im` → Qwen 교체 · 신규 647장 흡수 (total 2390) · crossmodal calibration · KR-쿼리 lex/asf skip 제거 · auto-recalibrate 훅 | 본 문서 시점 |

### 2.7 성능 (2026-04-24 측정)

| 지표 | 값 |
|---|---|
| 레이턴시 p50 (image, topk=10) | 68 ms |
| 레이턴시 p95 | 77 ms |
| 콜드 스타트 첫 쿼리 | 430 ms |
| topk 1→100 증가분 | +12% |
| 멀티도메인(image+doc_page) | 130–175 ms |
| Top-1 confidence ≥ 0.90 비율 (15쿼리 한국어) | 93% |

---

## 부록 A — 핵심 수식 (요약)

**Hermitian score** (tri_gs.py)
```
s(q, d) = √(A² + (α·B)² + (β·C)²)
  A = ⟨q_Re, d_Re⟩    α = 0.4
  B = ⟨q_Im, d_Im_perp⟩   β = 0.2
  C = ⟨q_Z,  d_Z_perp⟩
```

**Gram-Schmidt (doc측)**
```
Im_perp = Im - proj(Im onto Re)   (동일 차원일 때)
Z_perp  = Z  - proj(Z  onto [Re, Im_perp])
# 실제 구현은 차원 불일치(1152 vs 1024)라 L2-normalize 만.
```

**Calibration (W4-1 crossmodal)**
```
K개 캡션을 pseudo-query 로 인코딩 (SigLIP2 text + BGE-M3 query)
각 query × 5 random non-self doc pair → hermitian_score
abs_threshold = μ_null + Φ⁻¹(1 - FAR) · σ_null     (Acklam 근사)
confidence(s) = 0.5 · (1 + erf((s-μ)/(σ·√2)))
```

**RRF 결합 (Doc/Img)**
```
score(d) = Σ_i  1 / (k + rank_i(d))       k = 60
i ∈ {dense, sparse, asf} 중 활성 채널
```

**Inspect 가중 fusion (trichef_admin.py)**
```
w_dense=0.6, w_lex=0.25, w_asf=0.15  (비활성 채널은 dense 에 재분배)
fused = w_d · minmax(dense) + w_l · minmax(lex) + w_a · minmax(asf)
```

---

*문서 끝 · `DI_TriCHEF/docs/TRICHEF_PIPELINE.md`*
