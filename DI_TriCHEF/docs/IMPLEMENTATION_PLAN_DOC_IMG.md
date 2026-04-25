# Doc / Img 파이프라인 — 구현 계획서

> 문서 유형: 구현 계획서 (Implementation Plan)
> 대상 시스템: DB_insight · DI_TriCHEF · Doc / Img 도메인
> 작성일: 2026-04-24 · 버전: v1.0

---

## 1. 개요

### 1.1 목적
이미지(`raw_DB/Img`) 와 문서(`raw_DB/Doc`) 를 **3축 복소-에르미트 유사도** 로 통합 검색하는 멀티모달 검색 시스템을 구현한다. 자연어 질의(한국어 우선) 로 의미 · 언어 · 시각 구조 3가지 관점을 동시에 평가해 재현율(recall) 과 정밀도(precision) 를 함께 끌어올리는 것이 목표이다.

### 1.2 성공 기준 (Acceptance Criteria)

| 영역 | 지표 | 목표 |
|---|---|---|
| 지연 | p50 (topk=10, image) | ≤ 150 ms |
| 지연 | p95 | ≤ 250 ms |
| 품질 | Top-1 confidence ≥ 0.90 비율 (한국어 15쿼리) | ≥ 40% |
| 품질 | doc_page zero-hit 쿼리 (회귀 4쿼리) | 0 / 4 |
| 안정성 | calibration thr 2× 이상 폭증 시 자동 거부 | 필수 |
| 기동 | 첫 사용자 쿼리 cold-start 지연 | ≤ 첫 쿼리 600 ms |
| 증분 | 신규 이미지 흡수 — 2000장 기준 | ≤ 30 분 |

### 1.3 범위
- **대상**: 정적 이미지(JPG/PNG/WEBP), 문서(PDF/HWP/DOCX/PPTX/XLSX/ODT 등 20+ 확장자)
- **제외**: 동영상/음원 (→ Movie/Rec 별도 계획서)

---

## 2. 아키텍처

### 2.1 데이터 흐름 (고수준)

```
[RAW]                [EXTRACT]                [EMBED 3축]              [LEXICAL]              [INDEX]              [SEARCH]
raw_DB/Img/*.jpg → captions/{stem}.txt  → Re: SigLIP2 (1152d)  → vocab/ASF/sparse → .npy cache    → query
raw_DB/Doc/*.pdf →  (PDF text+render)   → Im: BGE-M3 (1024d)   →  (auto_vocab)    → ids.json      →  dense+lex+asf
                 →  page_images/        → Z : DINOv2-L (1024d) →                  → ChromaDB      →   (RRF merge)
                                          (Gram-Schmidt orth.) →                  → concat 3200d  →  calibration gate
```

### 2.2 모델 스택

| 축 / 채널 | 모델 | 차원 | 역할 |
|---|---|---|---|
| 캡셔너 | `Qwen/Qwen2-VL-2B-Instruct` | — | 한국어 자연어 캡션 |
| Re | `google/siglip2-so400m-patch14-384` | 1152 | cross-modal 의미 매칭 |
| Im | `BAAI/bge-m3` (dense) | 1024 | 한국어/다국어 캡션-텍스트 공간 |
| Z | `facebook/dinov2-large` | 1024 | 라벨-무관 시각 구조 |
| Sparse | `BAAI/bge-m3` (sparse) | 250002 | lemma/subword 희소 lexical |
| Reranker (옵션) | `BAAI/bge-reranker-v2-m3` | — | top-K cross-encoder 재순위 |

### 2.3 핵심 수식

```
Hermitian score:  s(q, d) = √(A² + (α·B)² + (β·C)²)
  A = ⟨q_Re, d_Re⟩       α = 0.4
  B = ⟨q_Im, d_Im_perp⟩  β = 0.2
  C = ⟨q_Z,  d_Z_perp⟩

Gram-Schmidt:  Im_perp = Im − proj(Im onto Re)
               Z_perp  = Z  − proj(Z  onto [Re, Im_perp])
               (차원 불일치면 projection 생략, L2-norm만)

Calibration:  K 개 캡션 pseudo-query → random non-self doc pair → score 분포
              abs_threshold = μ_null + Φ⁻¹(1 − FAR) · σ_null   (Acklam 근사)
              confidence(s) = ½·(1 + erf((s−μ)/(σ·√2)))

RRF merge:    score(d) = Σ_i 1/(k + rank_i(d)),  k = 60
```

### 2.4 모듈 구조

```
App/backend/
├── routes/
│   ├── trichef.py              # POST /api/trichef/search,  /reindex, /status
│   └── trichef_admin.py        # POST /api/admin/inspect,   /doc-text, /file
├── services/trichef/
│   ├── unified_engine.py       # TriChefEngine.search()
│   ├── tri_gs.py               # hermitian_score, orthogonalize
│   ├── calibration.py          # get_thresholds, calibrate_crossmodal (가드 포함)
│   ├── lexical_rebuild.py      # vocab / ASF / BGE-M3 sparse
│   ├── auto_vocab.py           # IDF 기반 토큰 추출
│   └── asf_filter.py           # Attention-Similarity-Filter
└── embedders/trichef/
    ├── incremental_runner.py   # run_{image,doc}_incremental
    ├── siglip2_re.py           # Re 축
    ├── bgem3_caption_im.py     # Im 축
    ├── bgem3_sparse.py         # sparse lexical
    ├── dinov2_z.py             # Z 축
    ├── doc_page_render.py      # PDF → JPEG (dpi=110) + stem_key_for
    ├── doc_ingest.py           # HWP/DOCX/PPTX → PDF 변환
    ├── qwen_caption.py         # 캡션 / paraphrase 유틸 (quant)
    ├── qwen_expand.py          # 쿼리 paraphrase 평균
    └── caption_io.py           # 캡션 파일 3-tier I/O
```

---

## 3. 구현 단계 (WBS)

### Phase 1 — 기반 구축 (완료)
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| P1-1 | Flask 서버 / Blueprint 등록 | `app.py` | ✅ |
| P1-2 | RAW → EXTRACT 경로 구성 | `config.PATHS` | ✅ |
| P1-3 | 3축 임베더 모듈 (`siglip2_re`/`bgem3_caption_im`/`dinov2_z`) | `embedders/trichef/*.py` | ✅ |
| P1-4 | Hermitian score + Gram-Schmidt | `services/trichef/tri_gs.py` | ✅ |
| P1-5 | SHA-256 registry 기반 증분 러너 | `incremental_runner.py` | ✅ |

### Phase 2 — 한국어 캡션 전환 (Wave2-W4-B, 완료)
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| P2-1 | Qwen2-VL 한국어 캡셔너 래퍼 | `DI_TriCHEF/captioner/qwen_vl_ko.py` | ✅ |
| P2-2 | 14장 샘플 품질 검증 (Chinese leak 0) | recaption 로그 | ✅ |
| P2-3 | 전체 재캡션 (2340장) | `extracted_DB/Img/captions/*.txt` | ✅ |
| P2-4 | BLIP → Qwen 스위치 (3-tier fallback) | `_caption_for_im` | ✅ |

### Phase 3 — Lexical 보조 채널 (완료)
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| P3-1 | BGE-M3 sparse 통합 | `bgem3_sparse.py` | ✅ |
| P3-2 | auto_vocab (IDF) | `auto_vocab.py` | ✅ |
| P3-3 | ASF 필터 | `asf_filter.py` | ✅ |
| P3-4 | RRF merge | `unified_engine._rrf_merge` | ✅ |

### Phase 4 — Calibration (Wave3-W5, 완료)
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| P4-1 | Acklam 분위수 근사 | `calibration._acklam_inv_phi` | ✅ |
| P4-2 | doc-doc null calibration (초기) | `calibrate_domain` | ✅ |
| P4-3 | **image crossmodal_v1** (W4-1) | `calibrate_image_crossmodal` | ✅ |
| P4-4 | 증분 완료 후 자동 재측정 훅 (W4-5) | `incremental_runner` step 6 | ✅ (image 한정) |
| P4-5 | **폭증 거부 가드** (W5 안전) | `calibrate_crossmodal` 2× 검사 | ✅ |

### Phase 5 — 운영 신뢰성 (Wave5, 일부 채택)
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| P5-1 | 백엔드 기동 warmup | `app.create_app` dummy search | ✅ |
| P5-2 | admin /inspect reranker opt-in | `trichef_admin.py use_rerank` | ✅ |
| P5-3 | regression 게이트 스위트 | `bench_w5.py --regression` | ✅ |
| P5-4 | (기각) `EXPAND_QUERY_N=5` | — | ❌ rollback |
| P5-5 | (기각) doc_page crossmodal | — | ❌ rollback |

### Phase 6 — 후속 로드맵 (미착수)
| ID | 작업 | 착수 조건 |
|---|---|---|
| P6-1 | Top-K pool 동적 튜닝 | pool=200 이 recall 에 영향 측정 |
| P6-2 | Multi-query batch endpoint | 배치 UI 확정 |
| P6-3 | Image thumbnail WebP 변환 | 프런트 요청 시 |
| P6-4 | Doc OCR 스캔 PDF 지원 | PyMuPDF extract 실패 검출 |
| P6-5 | Calibration 대시보드 | 관찰성 요구 증가 시 |

---

## 4. 데이터셋 / 스토리지 계획

| 경로 | 내용 | 비고 |
|---|---|---|
| `Data/raw_DB/Img/` | 원본 이미지 | SHA-256 로 중복 감지 |
| `Data/raw_DB/Doc/` | 원본 문서 | HWP/DOCX 등 → 내부적으로 PDF 로 변환 후 보관 |
| `Data/extracted_DB/Img/captions/{stem}.txt` | Qwen 한국어 캡션 | hash-stem / plain-stem 둘 다 조회 |
| `Data/extracted_DB/Doc/page_images/{stem}/pNNNN.jpg` | PDF 페이지 렌더 | dpi=110 |
| `Data/extracted_DB/Doc/captions/{stem}/pNNNN.txt` | 페이지 캡션 | Qwen |
| `Data/embedded_DB/Img/cache_img_{Re,Im,Z}.npy` | 증분 append | ids.json 과 행 수 일치 불변식 |
| `Data/embedded_DB/Doc/cache_doc_page_{Re,Im,Z}.npy` | 페이지 단위 | — |
| `Data/embedded_DB/trichef/` | Chroma persistent | `trichef_image`, `trichef_doc_page` 컬렉션 |
| `Data/embedded_DB/trichef_calibration.json` | μ/σ/thr | 도메인별 |

### 캐시 불변식 (CI 로 확인 가능)
1. `cache_{domain}_*.npy` 의 행 수 == `{domain}_ids.json` 길이
2. Chroma 컬렉션 id 1:1 with ids.json
3. vocab / asf_sets / sparse 는 ids 순서와 동일 인덱스

---

## 5. API 계약

### 5.1 공개

`POST /api/trichef/search`
```json
{
  "query": "강아지",
  "domain": "image" | "doc_page",
  "topk": 10,
  "use_lexical": true,
  "use_asf": true
}
```
응답: `{ query, stats: {per_domain}, top: [{id, domain, dense, lexical?, asf?, confidence, ...}] }`

`POST /api/trichef/reindex`
```json
{ "scope": "image" | "document" | "all" }
```

`GET /api/trichef/status` — 캐시 현황

`GET /api/trichef/file?path=...` — 파일 서빙

### 5.2 관리자

`POST /api/admin/inspect` — 전수 per-row 스코어 (top_n=200 기본). `use_rerank` 옵션 지원.

`GET /api/admin/doc-text?id=...&query=...` — 원문 + 매칭 토큰

`GET /api/admin/ui` — `admin_ui/admin.html` 서빙

---

## 6. 테스트 계획

### 6.1 단위
| 대상 | 도구 | 검증 |
|---|---|---|
| `tri_gs.hermitian_score` | pytest | 직교 기반 결합 정확성 |
| `calibration._acklam_inv_phi` | pytest | Φ⁻¹(0.8)=0.842 기준 허용오차 |
| `caption_io.load_caption` | pytest | hash-stem / plain-stem / 공백 순서 |

### 6.2 통합
| 스크립트 | 주기 |
|---|---|
| `DI_TriCHEF/scripts/bench_w5.py --regression` | 설정 변경 시마다 |
| `DI_TriCHEF/scripts/run_doc_crossmodal_calib.py` | 실험 시 수동 |
| `scripts/recalibrate_query_null.py` | doc reindex 후 수동 |

### 6.3 회귀 게이트 기준 (bench_w5 --regression)
- p95 ≤ 250ms
- mean_conf ≥ 0.40
- doc_page 4쿼리 모두 hits > 0

### 6.4 현 시점 성능 (Wave5 직후 측정)
| 지표 | 값 | 게이트 | 결과 |
|---|---|---|---|
| p50 | 143.9 ms | — | 기록 |
| p95 | 189.0 ms | ≤ 250 | PASS |
| mean_conf | 0.466 | ≥ 0.40 | PASS |
| doc_page zero-hit | 0/4 | = 0 | PASS |

---

## 7. 운영 · 모니터링

### 7.1 로그
- Flask access log
- 증분 러너 단계별 log (`embeddings done`, `lexical rebuilt`, `calibration: mu/sig/thr`)
- Calibration 거부 경고 (guard): `[calibration:doc_page] REJECTED new thr ...`

### 7.2 경보 기준
- Calibration 거부 로그 발생 → 담당자 리뷰 필요
- 회귀 게이트 FAIL → 배포 차단

### 7.3 백업 / 복구
- `trichef_calibration.json` 은 Git 에 커밋하지 않고 `embedded_DB/backup/` 에 타임스탬프 복사본 보관 (수동)
- Chroma 컬렉션 장애 시 `.npy` 에서 `_upsert_chroma` 로 복구 가능

---

## 8. 리스크 · 완화

| # | 리스크 | 영향 | 확률 | 완화 |
|---|---|---|---|---|
| R1 | Calibration 오염 (μ/σ 과소 · 과대 추정) | Recall / Precision 급락 | 중 | **2× 폭증 자동 거부 가드** + regression 게이트 |
| R2 | Qwen 캡션 다른 언어 섞임 | Im 축 품질 저하 | 저 | `fix_non_korean.py` 정기 스캔 |
| R3 | 신규 파일명 중복 / rename | 캡션 분실 | 중 | hash-stem 해시 우선, plain-stem fallback |
| R4 | 대용량 HWP/DOCX 변환 실패 | 인덱싱 누락 | 중 | `doc_ingest` 타임아웃 + 실패 로그 |
| R5 | GPU 메모리 부족 (reindex+service 동시) | OOM 크래시 | 중 | Calibration 스크립트에 `FORCE_CPU=1` 옵션 |
| R6 | Reranker 첫 호출 3~10s | admin UX 악화 | 저 | lazy singleton, off by default |
| R7 | 캐시 불변식 위반 (ids != Re len) | 검색 결과 어긋남 | 저 | `lexical_rebuild` 재실행 가이드 문서화 |

---

## 9. 의존성

### 9.1 외부 모델 (HuggingFace)
- `Qwen/Qwen2-VL-2B-Instruct` (캡셔너)
- `google/siglip2-so400m-patch14-384`
- `BAAI/bge-m3`
- `facebook/dinov2-large`
- `BAAI/bge-reranker-v2-m3` (옵션)

### 9.2 파이썬 주요 패키지
torch (CUDA/CPU), transformers, FlagEmbedding, chromadb, PyMuPDF (`fitz`), Pillow, numpy, scipy (sparse), flask, flask-cors

### 9.3 외부 도구
- HWP/DOCX → PDF 변환을 위한 LibreOffice (선택)
- NVIDIA GPU 권장 (CUDA 12.x)

---

## 10. 산출물 · 문서

| 문서 | 위치 |
|---|---|
| 본 계획서 | `DI_TriCHEF/docs/IMPLEMENTATION_PLAN_DOC_IMG.md` |
| 파이프라인 개요 + 핵심 개념 | `md/TRICHEF_PIPELINE_AND_CONCEPTS.md` |
| TriCHEF 전용 상세 | `md/TRICHEF_SPECIFIC.md` |
| 벤치/회귀 스위트 | `DI_TriCHEF/scripts/bench_w5.py` |
| Reranker 효과 스크립트 | `DI_TriCHEF/scripts/bench_rerank.py` |
| Doc crossmodal 실험 | `DI_TriCHEF/scripts/run_doc_crossmodal_calib.py` |

---

## 11. 완료 판정 체크리스트

- [x] 3축 임베딩 정상 산출 (Re 1152d / Im 1024d / Z 1024d)
- [x] Qwen 한국어 캡션 채택 (`_caption_for_im` 3-tier fallback)
- [x] RRF 기반 dense+lex+asf 융합 가동
- [x] Image 도메인 crossmodal calibration (`crossmodal_v1`)
- [x] Doc 도메인 random_query_null 기반 calibration 유지
- [x] Calibration 폭증 거부 가드
- [x] 백엔드 기동 warmup
- [x] Admin /inspect reranker opt-in
- [x] Regression 게이트 스위트 (bench_w5 --regression)
- [x] 성능 회귀 PASS (p95≤250ms, mean_conf≥0.40, doc_page 0/4 zero-hit)
- [ ] 21개 신규 문서 reindex 예약 실행 (사용자 결정 대기)

---

*문서 끝 · `DI_TriCHEF/docs/IMPLEMENTATION_PLAN_DOC_IMG.md`*
