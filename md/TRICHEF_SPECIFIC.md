# TRI-CHEF — 전용 내용 정리

> 생성일: 2026-04-24
> 범위: TRI-CHEF 서브시스템에만 해당하는 코드·API·데이터·히스토리 (다른 파이프라인과 공유되지 않는 내용)

---

## 1. 디렉토리 구조 (TriCHEF 관련만)

```
DB_insight/
├── App/backend/
│   ├── routes/
│   │   ├── trichef.py              # 공개 API (/api/trichef/*)
│   │   └── trichef_admin.py        # admin /inspect (per-row 점수 디버그)
│   ├── services/trichef/
│   │   ├── unified_engine.py       # TriChefEngine, search, search_av
│   │   ├── tri_gs.py               # 3축 점수 수학 (hermitian_score, GS)
│   │   ├── calibration.py          # abs_threshold + crossmodal calibration (W4-1)
│   │   ├── lexical_rebuild.py      # vocab/ASF/sparse 재구축
│   │   ├── auto_vocab.py           # IDF 기반 어휘 추출
│   │   ├── asf_filter.py           # Attention-Similarity-Filter
│   │   └── prune.py                # 제거된 파일 캐시 pruning
│   └── embedders/trichef/
│       ├── incremental_runner.py   # 증분 임베딩 러너 (4도메인)
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
├── DI_TriCHEF/                     # TriCHEF 사이드프로젝트 루트
│   ├── captioner/
│   │   ├── qwen_vl_ko.py           # Qwen2-VL-2B 한국어 캡셔너 (W3)
│   │   ├── recaption_all.py        # 전체 재캡션 러너
│   │   └── fix_non_korean.py       # 비한국어 선별 재생성
│   ├── reranker/
│   │   ├── post_rerank.py          # non-invasive 재순위 엔진
│   │   └── rerank_cli.py           # CLI 진입점
│   └── docs/
│       ├── TRICHEF_PIPELINE_AND_CONCEPTS.md
│       └── TRICHEF_SPECIFIC.md     # ← 본 문서
├── App/admin_ui/
│   ├── admin.html                  # /api/admin/ui 카드 그리드
│   └── serve.py                    # standalone 서빙
├── shared/
│   └── reranker.py                 # BgeRerankerV2 공유 래퍼 (TriCHEF 쓰임)
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

## 2. API 엔드포인트

### 2.1 공개 (`routes/trichef.py`)

| 메서드 | 경로 | 용도 |
|---|---|---|
| POST | `/api/trichef/search` | 멀티도메인 검색 (image/doc_page/movie/music) |
| POST | `/api/trichef/reindex` | `scope ∈ {image, document, movie, music, all}` 증분 |
| GET  | `/api/trichef/file` | 결과 파일 서빙 (path 쿼리) |
| GET  | `/api/trichef/status` | 캐시 현황 |
| GET  | `/api/trichef/image-tags` | 이미지 태그 JSON |

### 2.2 관리자 (`routes/trichef_admin.py`, prefix `/api/admin`)

| 메서드 | 경로 | 용도 |
|---|---|---|
| POST | `/api/admin/inspect` | per-row `dense/lex/asf/fused/rrf/confidence/z_score` — top-K 필터 無 |
| GET  | `/api/admin/doc-text` | doc_page id → 원문 + 매칭 토큰 |
| GET  | `/api/admin/file` | 도메인별 원본 파일 서빙 (썸네일) |
| GET  | `/api/admin/ui` | `App/admin_ui/admin.html` 서빙 (카드 그리드) |
| GET  | `/api/admin/domains` | 로드된 도메인 + 카운트 + sparse/asf/vocab 상태 |

### 2.3 Inspect 응답 필드 (카드별)

```json
{
  "rank": 1, "id": "…", "filename": "…", "source_path": "…", "page": 0,
  "dense": 0.71, "lexical": 0.43, "asf": 0.22,
  "rrf": 0.068, "fused": 0.88,
  "confidence": 0.96, "z_score": 2.12
}
```

## 3. TriChefEngine 내부 구조

```python
class TriChefEngine:
    __init__():
        _cache["image"]    = _build_entry(IMG_CACHE)      # 2390장
        _cache["doc_page"] = _build_entry(DOC_CACHE)      # 34170 페이지
        _cache["movie"]    = _build_av_entry(MOVIE_CACHE)
        _cache["music"]    = _build_av_entry(MUSIC_CACHE)

    search(query, domain, topk, use_lexical, use_asf, pool):
        q_Re, q_Im = _embed_query_for_domain(query, domain)
        dense_scores  = hermitian_score(q, d)
        sparse_scores = bgem3_sparse.lexical_scores(q_sp, d.sparse)   # 옵션
        asf_s         = asf_filter.asf_scores(query, d.asf_sets, d.vocab)  # 옵션
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

## 4. 데이터셋 현재 규모 (2026-04-24 스냅샷)

| 도메인 | raw 파일 | 임베딩 벡터 | 비고 |
|---|---|---|---|
| Img | **2391** | **2390** (Re 1152d / Im 1024d / Z 1024d) | ~30 MB |
| Doc | 444 (PDF/HWP/DOCX) | **34170 페이지** (Re 1152d / Im 1024d / Z 1024d) | ~419 MB |
| Movie | 163 | (STT 세그먼트 가변) | — |
| Rec (Music) | 16 | STT 세그먼트 | `cache_music_*.npy` 존재 |

## 5. Calibration 현재 상태 (`trichef_calibration.json`)

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

`crossmodal_v1` — W4-1 도입. query(SigLIP2 text + BGE-M3) ↔ doc(image feature) null pair 분포로 측정. 이전 `doc-doc self-similarity` 방식은 cross-modal 스케일을 과대추정하는 버그로 폐기.

## 6. Wave 히스토리 (TriCHEF 적용 순서)

| Wave | 내용 | 주요 산출물 |
|---|---|---|
| Wave1 | 공유 reranker / DI admin inspect 옵션 / DINOv2 Z축 / MR CLAP Z축 / MR sparse / MR qwen_expand 스캐폴드 | `shared/reranker.py`, `DI_TriCHEF/` |
| Wave2 | 14장 샘플 Qwen 한국어 캡션 품질 검증 | Chinese leak 0 |
| Wave3 | Qwen 전체 재캡션 2340장 → BGE-M3 Im 재임베드 → vocab/ASF/sparse 재구축 → ChromaDB 3200d upsert → calibration 측정 | cache/trichef 전면 갱신 |
| Wave4 | `_caption_for_im` → Qwen 교체 · 신규 647장 흡수 (total 2390) · crossmodal calibration · KR-쿼리 lex/asf skip 제거 · auto-recalibrate 훅 | 본 문서 시점 |

### 6.1 Wave4 세부 작업 매핑

| 코드 | 내용 | 핵심 파일 |
|---|---|---|
| W4-B | BLIP → Qwen2-VL 캡셔너 교체 | `incremental_runner._get_qwen_captioner` |
| W4-2 | 캡션 3-tier fallback (hash/plain-stem + new) | `_caption_for_im` |
| W4-3 | 신규 647장 증분 흡수 (2390 total) | `run_image_incremental` |
| W4-6(1차) | lexical/ASF/sparse 전면 rebuild | `lexical_rebuild` |
| W4-1 | cross-modal null calibration 신설 | `calibration.calibrate_image_crossmodal` |
| W4-4 | 과거 "image+KR → lex/asf skip" 휴리스틱 제거 | `routes/trichef_admin.inspect` |
| W4-5 | 증분 완료 후 auto-recalibrate hook | `incremental_runner` step 6 |

## 7. 성능 (2026-04-24 측정)

| 지표 | 값 |
|---|---|
| 레이턴시 p50 (image, topk=10) | 68 ms |
| 레이턴시 p95 | 77 ms |
| 콜드 스타트 첫 쿼리 | 430 ms |
| topk 1→100 증가분 | +12% |
| 멀티도메인(image+doc_page) | 130–175 ms |
| Top-1 confidence ≥ 0.90 비율 (한국어 15쿼리) | 93% |

## 8. 파일명 정책 / stem 해시

- **hash-stem** — `stem_key_for(path)` 가 반환하는 SHA-256 접두 해시. 파일 rename 에도 안정.
- **plain-stem** — 원본 파일명 (사람이 읽을 수 있음). 레거시 호환용.
- **캡션 조회 우선순위** — hash-stem json → hash-stem txt → plain-stem txt → (없으면 Qwen 생성).

## 9. 캐시 · 인덱스 불변식

1. `cache_{domain}_{Re,Im,Z}.npy` 의 행 수는 항상 `{domain}_ids.json` 길이와 일치.
2. Chroma `trichef_{domain}` 컬렉션의 id 는 ids.json 의 id 와 1:1.
3. `vocab`, `asf_sets`, `sparse` 는 ids 순서와 동일 인덱스로 정렬.
4. 불변식 깨짐 감지 시 `lexical_rebuild.rebuild_{image,doc}_lexical` 전체 재구축 필요.

## 10. 관리자 UI (`/api/admin/ui`)

- 카드 그리드 레이아웃. 각 카드 = `/api/admin/inspect` 한 행.
- 필드: 썸네일(이미지) 또는 doc 페이지 렌더, filename, dense/lex/asf, confidence bar.
- 쿼리 입력 후 전수 스코어 top_n=200 반환. top-K gate 없음 — 디버그/튜닝 전용.

## 11. 향후 개선 후보 (Wave5 예정)

| # | 항목 | 근거 |
|---|---|---|
| 1 | `abs_threshold` 0.217 → 0.20 상향, Qwen expand paraphrase 수 증가 | 한국어 recall↑ 가능성 |
| 2 | reranker `/inspect` 통합 (BGE v2-m3 cross-encoder top-K 재순위) | 근소 차이 분리력 |
| 3 | `doc_page` 도메인에도 crossmodal calibration 적용 | 현재는 doc-doc 방식 유지 |
| 4 | 백엔드 기동 시 warmup (SigLIP2/BGE-M3/DINOv2 선로딩) | 첫 쿼리 430ms 제거 |

---

*문서 끝 · `md/TRICHEF_SPECIFIC.md`*
