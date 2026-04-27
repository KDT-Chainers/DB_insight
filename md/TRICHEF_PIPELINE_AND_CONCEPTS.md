# TRI-CHEF — 파이프라인 & 핵심 개념

> 생성일: 2026-04-24
> 범위: (1) Doc/Img vs Movie/Rec 파이프라인 상세 · 독립성, (2) 적용한 핵심 개념 · 원리 · 수학적 기술 · 데이터셋 대응 판단 기준

---

## PART 1 — 파이프라인 상세도

### 1.1 Doc / Img 파이프라인 (텍스트/이미지 기반)

```
[RAW]                [EXTRACT]               [EMBED 3축]           [LEXICAL]          [INDEX]         [SEARCH]
raw_DB/Img/*.jpg → captions/{stem}.txt → Re: SigLIP2 (1152d)  → vocab/ASF/sparse  →  .npy cache   → query
raw_DB/Doc/*.pdf →  (PDF text+render)  → Im: BGE-M3 (1024d)   →  (auto_vocab)     → img_ids.json  →  dense+lex+asf
                 →  page_images/       → Z : DINOv2-L (1024d) →                   → ChromaDB      →   (RRF merge)
                                         (Gram-Schmidt orth.) →                   → concat 3200d  →  calibration gate
```

**모델 스택**

- 캡셔너: Qwen2-VL-2B-Instruct (한국어, Wave3 이후 BLIP 대체)
- Re축: `google/siglip2-so400m-patch14-384` (cross-modal 이미지-텍스트)
- Im축: `BAAI/bge-m3` dense (다국어 캡션/텍스트)
- Z축: `facebook/dinov2-large` (self-supervised 시각 구조)
- Sparse: `BAAI/bge-m3` sparse (lemma/subword 희소 표현)
- Reranker (선택): `BAAI/bge-reranker-v2-m3`

**진입점** — `App/backend/embedders/trichef/incremental_runner.py`

- `run_image_incremental()` — 신규 이미지 SHA-256 증분 처리
- `run_doc_incremental()` — PDF → 페이지별 렌더 + 캡션 + 원문 텍스트

#### Image 세부 단계

| 단계               | 산출물/파일                | 모듈·함수                    | 비고                                         |
| ------------------ | -------------------------- | ---------------------------- | -------------------------------------------- |
| 1. 신규 탐지       | `registry.json` (SHA-256)  | `_load_registry, _sha256`    | 변경/신규만                                  |
| 2. 캡션 로드/생성  | `captions/{stem}.txt`      | `_caption_for_im`            | Qwen2-VL. plain-stem/hash-stem/json fallback |
| 3. Re 임베딩       | `siglip2_re.py`            | `embed_images`               | 384×384, L2-norm                             |
| 4. Im 임베딩       | `bgem3_caption_im.py`      | `embed_passage`              | max_length=1024                              |
| 5. Z 임베딩        | `dinov2_z.py`              | `embed_images`               | 224×224, CLS                                 |
| 6. Gram-Schmidt    | `tri_gs.py`                | `orthogonalize`              | Im_perp, Z_perp                              |
| 7. 3축 npy 누적    | `cache_img_{Re,Im,Z}.npy`  | `np.vstack`                  | 증분 append                                  |
| 8. Chroma upsert   | `trichef_image`            | `_upsert_chroma`             | concat 3200d, cosine                         |
| 9. Lexical rebuild | vocab + ASF + sparse       | `lexical_rebuild`            | vocab=2784                                   |
| 10. Calibration    | `trichef_calibration.json` | `calibrate_image_crossmodal` | W4-1 crossmodal                              |

#### Document 세부 단계

| 단계             | 모듈·함수                        | 비고                       |
| ---------------- | -------------------------------- | -------------------------- |
| 1. PDF 렌더      | `doc_page_render.render_pdf`     | dpi=110 JPEG               |
| 2. 페이지 캡션   | `_caption_for_im`                | Qwen2-VL                   |
| 3. PDF 원문 추출 | `fitz.Document.get_text("text")` | 페이지별                   |
| 4. 3축 임베딩    | Re/Im/Z 동일                     | Im 입력 = "캡션\n원문"     |
| 5. Lexical       | `rebuild_doc_lexical`            | max_length=2048, top 25000 |

### 1.2 Movie / Rec(Music) 파이프라인 (오디오-비주얼)

```
[RAW]                    [SEGMENT/STT]                [EMBED 3축]                  [INDEX]                [SEARCH]
raw_DB/Movie/*.mp4  → FFmpeg 씬 분할 or      → Re/Im/Z: 세그먼트 텍스트     → segments.json        → query
raw_DB/Rec/*.m4a    →  고정 구간 (예: 30s) →  + 선택적 CLAP (Z축 오디오)  →  cache_{movie,music}_ → search_av
                    → Whisper STT →           Qwen/CLAP Expand 선택적       →   {Re,Im,Z}.npy    →   파일 단위 집계
                    → Qwen 자막 캡션 (선택)                                                        →   top 세그먼트 타임라인
```

**모델 스택**

- STT: `openai/whisper` (large-v3 또는 small)
- 텍스트: BGE-M3 dense (Re=Im=Z 모두 동일 1024d — 멀티미디어 쿼리도 텍스트 기반)
- 선택: `laion/clap-htsat-unfused` (오디오 Z축, MR 계보)

**진입점**: `run_movie_incremental()`, `run_music_incremental()`

**출력 자료구조**

- `cache_music_Re.npy` : (N_seg, 1024)
- `music_ids.json` : `["{file_id}#{seg_idx}", …]`
- `segments.json` : `[{id, file_path, file_name, start_sec, end_sec, stt_text, caption}, …]`

#### 검색 플로우 (`search_av`)

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

| 항목                | Doc/Img                             | Movie/Rec                        |
| ------------------- | ----------------------------------- | -------------------------------- |
| **진입점**          | `run_{image,doc}_incremental`       | `run_{movie,music}_incremental`  |
| **캐시**            | `TRICHEF_{IMG,DOC}_CACHE`           | `TRICHEF_{MOVIE,MUSIC}_CACHE`    |
| **Chroma 컬렉션**   | `trichef_image`, `trichef_doc_page` | `trichef_movie`, `trichef_music` |
| **검색 API**        | `engine.search()`                   | `engine.search_av()`             |
| **Re 축 모델**      | SigLIP2 (1152d, img-text)           | BGE-M3 (1024d, text)             |
| **Lexical(sparse)** | ✅ 활성                             | ❌ 미사용                        |
| **ASF 필터**        | ✅ 활성                             | ❌ 미사용                        |
| **세그먼트 집계**   | ❌ (페이지/이미지 단위)             | ✅ 파일/세그먼트 단위            |

**결론** — 두 파이프라인은 **데이터 구조 · 모델 · 검색 로직 모두 독립**이나, **공유 레이어**(hermitian score, calibration, Gram-Schmidt, TriChefEngine dispatch)를 통해 단일 API(`/api/trichef/search`) 뒤에 통합된다.

### 1.4 공유 모듈 매트릭스

| 모듈                                   | 파일                                                      | Doc/Img | Movie/Rec | 역할                          |
| -------------------------------------- | --------------------------------------------------------- | ------- | --------- | ----------------------------- |
| TriChefEngine                          | `services/trichef/unified_engine.py`                      | ✅      | ✅        | domain 라우팅                 |
| `hermitian_score / orthogonalize`      | `services/trichef/tri_gs.py`                              | ✅      | ✅        | 3축 결합 점수                 |
| calibration                            | `services/trichef/calibration.py`                         | ✅      | ✅        | abs_threshold, confidence CDF |
| `qwen_expand`                          | `embedders/trichef/qwen_expand.py`                        | ✅      | ✅        | paraphrase 평균               |
| `shared.reranker`                      | `shared/reranker.py`                                      | 선택    | 선택      | cross-encoder 재순위          |
| RRF merge                              | `_rrf_merge`                                              | ✅      | ❌        | dense/lex/asf 순위 융합       |
| asf_filter / auto_vocab / bgem3_sparse | `services/trichef/*`, `embedders/trichef/bgem3_sparse.py` | ✅      | ❌        | lexical 보조                  |

---

## PART 2 — 핵심 개념 · 원리 · 수학 · 데이터셋 대응 판단 기준

### 2.1 3축(Re/Im/Z) 복소-에르미트 설계 원리

**직관** — 이미지-텍스트 유사도는 단일 모델 한 축만으로는 편향된다. 직교 정보를 세 축에 나누어 결합하면 각 축의 실패 모드가 서로 보완된다.

| 축             | 해석                                                   | 제공 모델      | 실패 모드 보완                            |
| -------------- | ------------------------------------------------------ | -------------- | ----------------------------------------- |
| Re (real)      | **cross-modal 의미** — "질의와 이미지가 같은 개념인가" | SigLIP2-SO400M | 캡션이 부족해도 시각-텍스트 매칭          |
| Im (imaginary) | **언어·캡션 정합** — 다국어 텍스트 공간                | BGE-M3 dense   | 시각이 모호할 때 캡션/문서 원문 보조      |
| Z (ortho)      | **순수 시각 구조** — 라벨-무관 visual prior            | DINOv2-L       | 캡션 편향/노이즈 배제, 시각적 근접성 보존 |

**직교화** — Im, Z 는 Re 에 대해 Gram-Schmidt 직교성분(`Im_perp`, `Z_perp`)만 사용. Re 축과 중복된 정보를 제거해 채널 간 상관 noise 를 줄인다. (차원 불일치 시엔 L2-norm 만 적용)

### 2.2 수식 카탈로그

**Hermitian score** (`tri_gs.py`)

```
s(q, d) = √( A² + (α·B)² + (β·C)² )
  A = ⟨q_Re,     d_Re⟩         α = 0.4
  B = ⟨q_Im,     d_Im_perp⟩    β = 0.2
  C = ⟨q_Z,      d_Z_perp⟩
```

`α, β` 는 의미-시각 가중 균형. 실측 기준 Re 축이 지배적 신호이므로 Im/Z 는 감쇠.

**Gram-Schmidt (doc 측)**

```
Im_perp = Im - proj(Im onto Re)
Z_perp  = Z  - proj(Z  onto [Re, Im_perp])
```

실제 구현은 차원이 1152 vs 1024 로 다르면 projection 을 생략하고 L2-norm 만 수행.

**Cross-modal null calibration (W4-1)**

```
K개 캡션을 pseudo-query 로 인코딩  (SigLIP2 text + BGE-M3 query)
각 query × 5 random non-self doc → hermitian_score
μ_null = mean(scores), σ_null = std(scores)
abs_threshold = μ_null + Φ⁻¹(1 − FAR) · σ_null     (Acklam 근사)
confidence(s) = ½ · (1 + erf((s − μ) / (σ·√2)))
```

- `FAR_IMG = 0.2`, `FAR_DOC_PAGE = 0.1`, `FAR_DOC_TEXT = 0.05`
- 이전 "doc-doc self-similarity" 방식은 cross-modal 스케일을 과대추정하여 폐기.

**RRF (Reciprocal Rank Fusion)** — Doc/Img

```
score(d) = Σ_i  1 / (k + rank_i(d))          k = 60
i ∈ {dense, sparse, asf} 중 활성 채널
```

비교대상: min-max 정규화 후 가중합. RRF 가 스케일 불변성·극단값 내성을 가져 프로덕션 기본값.

**Inspect 가중 fusion** (`trichef_admin.py`)

```
w_dense=0.6, w_lex=0.25, w_asf=0.15
비활성 채널의 가중치는 dense 로 재분배
fused = w_d · minmax(dense) + w_l · minmax(lex) + w_a · minmax(asf)
```

**Abs threshold 상향 보호** (Inspect)

```
if domain == "image":
    abs_thr = max(abs_thr, μ + 3·σ)
```

calibration 의 σ 가 저평가됐을 때를 대비한 하한선.

### 2.3 Lexical 보조 채널

| 채널                                              | 구현                              | 역할                              | 스케일                          |
| ------------------------------------------------- | --------------------------------- | --------------------------------- | ------------------------------- |
| **auto_vocab** (`services/trichef/auto_vocab.py`) | IDF 기반 토큰화 + 후보 vocab 추출 | 한국어 substring 매칭 보조        | vocab ≈ 2784 (Img), 25000 (Doc) |
| **BGE-M3 sparse**                                 | 250002-dim sparse lexical         | 실제 lexical 유사도 (dot product) | nnz ≈ 70000                     |
| **ASF (Attention-Similarity-Filter)**             | token_set × vocab intersection    | 토큰 공통도 0~1                   | 정규화됨                        |

**활성 판정**

```python
lex_active = lex is not None and max(lex) > 0
asf_active = asf_s is not None and max(asf_s) > 0
```

신호 없는 채널은 가중치를 dense 로 재분배 — "noisy zero" 로 dense 를 깎는 사고 방지.

### 2.4 쿼리 확장 (Qwen expand)

```
variants = qwen_expand.expand(query)      # paraphrase K개
q_Re = normalize( mean(SigLIP2.embed_texts(variants)) )
q_Im = normalize( mean(BGE-M3.embed_query(variants)) )
q_Z  = q_Im                                 # Z축은 쿼리 측 시각 정보가 없어 Im 재사용
```

이유 — 단일 쿼리 표현 편향을 paraphrase 평균으로 완화. SigLIP2 의 자연어 민감성 보정에 특히 효과.

### 2.5 데이터셋 대응 판단 기준 (data-adaptive policy)

| 상황                       | 자동 판단 기준                                                       | 구현 위치                          |
| -------------------------- | -------------------------------------------------------------------- | ---------------------------------- |
| Img 신규 647장 증분        | SHA-256 registry 로 변경분만 re-embed                                | `incremental_runner`               |
| 캡션 품질 불확실           | 3-tier fallback: hash-stem(json→txt) → plain-stem(txt) → Qwen 재생성 | `_caption_for_im`                  |
| 차원 불일치 (1152 vs 1024) | Gram-Schmidt 스킵, L2-norm 만                                        | `tri_gs.orthogonalize`             |
| lexical/asf 신호 0         | 가중치 dense 재분배 (fallback)                                       | `trichef_admin.inspect`            |
| image 도메인 σ 저평가      | `abs_thr = max(abs_thr, μ+3σ)`                                       | `trichef_admin.inspect`            |
| 쿼리 한국어 여부           | 과거 image+KR → lex/asf skip (폐기, W4-4)                            | —                                  |
| AV 도메인 임계             | `abs_thr * 0.5` 완화 (segment-level noise 큼)                        | `engine.search_av`                 |
| calibration 재측정 트리거  | 증분 embed 완료 후 자동 hook 실행                                    | `incremental_runner` step 6 (W4-5) |
| FAR 도메인별 차등          | `FAR_IMG=0.2 > FAR_DOC_PAGE=0.1 > FAR_DOC_TEXT=0.05`                 | `TRICHEF_CFG`                      |
| Top-K pool                 | dense top-K 후보에만 lex/asf 계산 (전체 계산은 `/admin/inspect` 만)  | `engine.search`                    |

**원칙**

1. **신호가 없으면 자동으로 꺼진다** (noisy channel 차단).
2. **분포가 바뀌면 자동으로 재측정한다** (W4-5 auto-recalibrate).
3. **판정 기준은 항상 μ ± σ 로 확률적으로 표현** — 하드코드 임계 금지.
4. **도메인 물리적 특성에 맞춰 FAR 와 임계 감쇠율 차등화** — AV 는 segment 잡음 많아 임계 완화.

### 2.6 Confidence 해석 (사용자 노출 지표)

```
z = (s − μ_null) / σ_null
confidence = Φ(z) = ½·(1 + erf(z/√2))
```

- `0.50`: 완전 무관 쿼리 수준
- `0.80+`: 유의미
- `0.95+`: 강한 매칭 (UI 상 "정확히 일치" 배지)

### 2.7 왜 이 조합이 한국어-이미지 검색에 통하는가

- **SigLIP2** 는 다국어 대규모 학습으로 한국어 텍스트 → 이미지 매칭이 CLIP 대비 우수.
- **Qwen2-VL 한국어 캡션** 으로 Im 축에 자연스런 한국어 문장이 실려 BGE-M3 의 한국어 dense 를 활용 가능.
- **DINOv2 Z축** 은 언어 비의존적이라 쿼리 언어와 무관하게 시각 유사성 제공.
- **BGE-M3 sparse + auto_vocab ASF** 는 고유명사/도메인 용어 정밀 매칭.
- **Qwen expand** 로 질의 편향 완화.

이 5층 보완 구조 위에 **crossmodal calibration** 이 얹혀, per-query confidence 가 실제 쿼리-문서 분포 기준으로 교정된다.

---

_문서 끝 · `md/TRICHEF_PIPELINE_AND_CONCEPTS.md`_
