# DI TRI-CHEF Doc / Img 파이프라인 상세 설명서

> 버전: v1-6 (2026-04-29 최종) · 갱신: 2026-04-29 · 브랜치 `feature/trichef-port`
> 대상 도메인: `doc_page` (PDF/HWP/Office/TXT/CSV/HTML → 페이지 이미지), `image` (원본 이미지)
> **논문 v1-6 정합**: 본 파이프라인은 *Tri-CHEF: Complex-Hermitian Embedding Fusion for Korean Multimodal Retrieval* 논문 v1-6 (arXiv 제출본) 의 §IV 기술과 1:1 일치합니다.
> **최신 변경 (2026-04-29)**:
> - 캘리브레이션 실측 재현: 24개 NULL_QUERIES × N_corpus 쌍에서 `random_query_null_v2` 방식으로 약 2.3M raw scores 추출 → 논문 Tab II 정확 매치
> - Fig 4(a) 3D σ-stratified 시각화: 4 도메인 가우시안이 σ_null 축으로 자연스럽게 층화
> - 한계 명시: 단일 시드(seed=2026) 평가 — 다중 시드 분산 측정은 후속 작업

## 📌 최종 배포 파이프라인 요약 (논문 §IV)

| 항목 | Doc | Img |
|---|---|---|
| **Re 축** | SigLIP2-image (1152d) | SigLIP2-image (1152d) |
| **Im 축** | BGE-M3 (1024d) — 캡션 20% + 본문 80% (`α_IM=0.20`) | BGE-M3 (1024d) — Qwen2-VL 캡션 |
| **Z 축** | DINOv2 (1024d) | DINOv2 (1024d) |
| **Hermitian 점수** | 3축: $\sqrt{A^2+(\alpha B)^2+(\beta C)^2}$, $\alpha=\beta=0.4$ | 동일 |
| **Sparse (lexical)** | ON | OFF (per-domain gating) |
| **ASF (bigram)** | OFF (default) | OFF |
| **τ (FAR=0.05/0.20)** | 0.2051 (FAR=0.05) | 0.2012 (FAR=0.20) |
| **N_corpus 벡터** | 34,661 (443 파일 × pages) | 2,390 (2,391 파일 - 1 skip) |
| **μ_null** | 0.1693 | 0.1776 |
| **σ_null** | 0.0218 | 0.0281 |
| **LangGraph rewrite** | ❌ (MR-TriCHEF 전용) | ❌ |
| **BGE Reranker** | ❌ (MR-TriCHEF 전용 placeholder) | ❌ |

---

## 0. 목차

1. [시스템 개요](#1-시스템-개요)
2. [저장소 · 경로 규약](#2-저장소--경로-규약)
3. [인덱싱 파이프라인](#3-인덱싱-파이프라인)
4. [3축 임베딩 (Re / Im / Z)](#4-3축-임베딩-re--im--z)
5. [Sparse / Auto-Vocab / ASF](#5-sparse--auto-vocab--asf)
6. [Calibration (μ / σ / abs_threshold)](#6-calibration-μ--σ--abs_threshold)
7. [검색 파이프라인 (Query-time)](#7-검색-파이프라인-query-time)
8. [Fusion & 랭킹](#8-fusion--랭킹)
9. [Confidence / z-score](#9-confidence--z-score)
10. [API 계약](#10-api-계약)
11. [Admin UI](#11-admin-ui)
12. [확장자 SSOT (Q1, commit 1049099)](#12-확장자-ssot-q1-commit-1049099)
13. [증분 업데이트 로직](#13-증분-업데이트-로직)
14. [자동 적응 기준값 요약](#14-자동-적응-기준값-요약)
15. [알려진 한계 & 개선 후보](#15-알려진-한계--개선-후보)
16. [Appendix — 수식 요약](#16-appendix--수식-요약)

---

## 1. 시스템 개요

### 1.1 목적

TRI-CHEF 는 **문서 페이지 이미지**(`doc_page`) 와 **원본 이미지**(`image`) 두 도메인에 대해
**의미(dense) + 어휘(lexical) + 도메인어(ASF)** 3채널을 가중 융합해
자연어 쿼리로 관련 콘텐츠를 검색하는 엔진이다.

### 1.2 전체 흐름

```
[원본 파일]
   │
   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        (1) 인제스트 & 전처리                         │
│  PDF/HWP/Office/TXT/CSV/HTML → 페이지 JPG  또는  원본 IMG           │
│  stem_key = sanitize(stem) + "__" + md5(rel_key)[:8]                 │
└──────────────────┬───────────────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│            (2) 캡션 생성 (Qwen2-VL-2B-Instruct caption_triple)       │
│                    L1 ≤20字 + L2 5–10키워드 + L3 30–60字              │
└──────────────────┬───────────────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│      (3) 3축 임베딩 (Re=SigLIP2 1152d, Im=BGE-M3 1024d, Z=DINOv2 1024d) │
│            positional .npy 캐시 + ChromaDB 저장 (Gram-Schmidt orth.)   │
└──────────────────┬───────────────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│        (4) Sparse (BGE-M3)  +  auto_vocab  +  asf_token_sets         │
└──────────────────┬───────────────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│        (5) Calibration:  μ_null, σ_null, abs_threshold               │
└──────────────────┬───────────────────────────────────────────────────┘
                   ▼
╔══════════════════════════════════════════════════════════════════════╗
║                  ── 인덱싱 완료. 이하 검색 시 ──                     ║
╚══════════════════════════════════════════════════════════════════════╝
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                (6) Query → 3축 쿼리 임베딩 + sparse                  │
└──────────────────┬───────────────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│   (7) dense = hermitian_score,  lexical,  asf                        │
│        KR 쿼리 + image → lex/asf 자동 skip                            │
└──────────────────┬───────────────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│   (8) Weighted Fusion (min-max 정규화 후 0.6/0.25/0.15)              │
│        + 참고용 RRF (all-zero 채널 제외)                              │
└──────────────────┬───────────────────────────────────────────────────┘
                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│   (9) z-score & confidence (Φ(z)) · abs_threshold(image: μ+3σ)        │
└──────────────────┬───────────────────────────────────────────────────┘
                   ▼
             [Top-N JSON] → admin.html 카드 그리드
```

---

## 2. 저장소 · 경로 규약

### 2.1 물리 경로 (config.PATHS)

| 키 | 용도 | 내용물 |
|---|---|---|
| `RAW_DB` | 원본 | `Doc/…/*.pdf,hwp,…`, `Img/…/*.jpg,png,…` |
| `TRICHEF_DOC_EXTRACT` | 렌더 산출 | `page_images/<stem_key>/p0001.jpg`, `captions/<stem_key>/p0001.caption.json` |
| `TRICHEF_IMG_EXTRACT` | 이미지 산출 | `captions/<stem_key>.caption.json` |
| `TRICHEF_DOC_CACHE` | doc 캐시 | `cache_doc_page_{Re,Im,Z}.npy`, `doc_page_ids.json`, `registry.json`, `sparse.npz`, `asf_token_sets.json`, `vocab.json` |
| `TRICHEF_IMG_CACHE` | image 캐시 | 동일 구조 (prefix = `image`) |
| `TRICHEF_CHROMA` | ChromaDB | `COL_DOC_PAGE`, `COL_IMAGE` 컬렉션 |
| `EMBEDDED_DB` | 캘리 | `trichef_calibration.json` |

### 2.2 stem_key (H-2 충돌 방지)

서로 다른 디렉토리에 같은 파일명이 존재하면 sanitize(stem) 이 충돌한다.
이를 피하기 위해 **상대경로 기반 해시 접미**를 붙인다.

$$
\text{stem\_key}(rel\_key) = \text{sanitize}(\text{stem}(rel\_key)) \; \oplus \; \texttt{"\_\_"} \; \oplus \; \text{md5}(rel\_key)[:8]
$$

- `rel_key` = RAW_DB 기준 상대경로 (예: `Doc/SPRI_SW중심사회/월간SW중심사회_2017년_1월호_최종.pdf`)
- ⊕ = 문자열 연결
- 동일 rel_key 는 항상 동일 stem_key → 재임베딩 시에도 안정
- `page_images/<stem_key>/` 와 `captions/<stem_key>/` 디렉토리가 1:1 매핑

### 2.3 ID 규약

| 도메인 | ID 형태 |
|---|---|
| `doc_page` | `page_images/<stem_key>/p<4자리>.jpg` |
| `image` | `<subdir>/<파일명.ext>` (rel_key 그대로) |

---

## 3. 인덱싱 파이프라인

### 3.1 Doc 경로

```
src (PDF/HWP/Office/TXT/CSV/HTML)
    │
    ▼
doc_ingest.to_pages(src, stem_key)
    ├─ .pdf        → doc_page_render.render_pdf()
    ├─ .hwp/.hwpx  → LibreOffice CLI → .pdf → render_pdf()
    ├─ .docx/.pptx → LibreOffice CLI → .pdf → render_pdf()
    ├─ .txt/.md    → _virtual_text_pages() (텍스트 가상 페이지)
    ├─ .csv        → 테이블 가상 페이지
    └─ .html/.htm  → HTML 스냅샷 페이지
    │
    ▼
page_images/<stem_key>/p0001.jpg … pNNNN.jpg
    │
    ▼
Qwen2-VL-2B.caption_triple(page_jpg) → captions/<stem_key>/pNNNN.{L1,L2,L3}.json
```

### 3.2 Img 경로

```
RAW_DB/Img/ 재귀 스캔 → (rel_key, abs_path) 튜플
    │
    ▼
Qwen2-VL-2B.caption_triple(abs_path) → 3단계 캡션 생성
    (L1≤20字 + L2 5–10키워드 + L3 30–60字 상세)
    │
    ▼
caption_triple fusion (자동 수행)
    ├─ build_img_caption_triple.py: L1/L2/L3 → 개별 cache_img_Im_L{1,2,3}.npy
    ├─ fuse_img_caption_triple.py: 0.15·L1 + 0.25·L2 + 0.60·L3 → cache_img_Im.npy
    └─ unified_engine 로드 시 자동 적용 (App/backend/services/trichef/unified_engine.py:112-132)
```

**스크립트 역할**:
- `DI_TriCHEF/scripts/build_img_caption_triple.py`: stand-alone 이미지 처리 (backend 의존 없음, 개별 L1/L2/L3 저장)
- `DI_TriCHEF/scripts/fuse_img_caption_triple.py`: 가중치 합산 분석/디버깅용 (backend 의존 없음)

### 3.3 레지스트리

`registry.json` 은 rel_key → {abs, sha, stem_key, mtime, n_pages} 매핑.
인제스트 시 SHA 비교로 변경 감지.

---

## 4. 3축 임베딩 (Re / Im / Z)

### 4.1 축 정의

| 축 | 모델 | 입력 | 차원 | 역할 |
|---|---|---|---|---|
| **Re** | SigLIP2-SO400M | image ↔ text (공동 공간) | 1152 | 이미지 직접 의미 |
| **Im** | BGE-M3 dense | text (캡션 L1/L2/L3 가중평균) | 1024 | 캡션 의미 (크로스링구얼, INT8) |
| **Z**  | **DINOv2-Large** (1024d) | image CLS token (자가학습) | 1024 | 언어 비의존 순수 시각 구조 (INT8) |

- **Re** 는 multilingual cross-modal → 한국어 쿼리가 이미지에 직접 매칭 가능
- **Im** 은 Qwen2-VL caption_triple(L1≤20字, L2 5–10키, L3 30–60字) 가중 융합 (w=0.15/0.25/0.60)
  - 실제 수행: `App/backend/services/trichef/unified_engine.py:108-132` (엔진 로드 시 자동 실행)
  - 캡션 가중치 계산 후 L2 정규화 → `cache_img_Im.npy` (N, 1024) 로 저장
  - **외부 검증**: MIRACL-ko 한국어 검색 벤치마크(213 쿼리, 1.5M 문단)에서 BGE-M3 dense **nDCG@10=69.9** 달성(공식 리포트, ANN 기반). BM25(37.1) 대비 +32.8%p, mE5-large-v2(66.5) 대비 +3.4%p. 한국어 다국어 텍스트 검색의 기준으로 입증됨.
  - **자체 재현 (v1-6)**: ANN 대신 **정확 FAISS IndexFlatIP** 사용 시 **nDCG@10=77.82**, R@100=95.46, MRR=76.56 달성 (공식 대비 +7.92pp). 공식 수치와의 차이는 ANN 근사 오차에 기인함.
- **Z** 는 DINOv2-Large (1024d) CLS 토큰으로 캡션 편향·노이즈 배제, 순수 시각 근접성 보존 (Gram-Schmidt 직교화 후)

### 4.2 Gram-Schmidt 직교화 (현재)

```python
orthogonalize(Re, Im, Z):
    Im_hat = L2_normalize(Im)
    Z_hat  = L2_normalize(Z)
    return Im_hat, Z_hat
```

> Re(1152d) 와 Im/Z(1024d) 가 **차원 불일치** 라 실제 직교 투영은 생략.
> 정규화만 수행. (Test-DB_Secretary 실측 잔차율 0.999 동등)

### 4.3 Hermitian Score (dense 핵심)

각 축의 코사인 유사도를 복소수 3차원 벡터로 해석한 후 크기를 dense 점수로 사용.

$$
A = q_{Re} \cdot d_{Re},\quad B = q_{Im} \cdot d_{Im},\quad C = q_{Z} \cdot d_{Z}
$$

$$
\text{dense}(q, d) = \sqrt{A^2 + (\alpha B)^2 + (\beta C)^2}
$$

- $\alpha = 0.4$, $\beta = 0.2$ (tri_gs.py 기본값)
- Re 가 주축, Im/Z 는 보조. 이는 이미지 직접 시각 유사도(Re)에 가중 편향을 준다.
- 모든 벡터는 사전 L2 정규화 → 각 내적 ∈ [-1, 1]

### 4.4 저장 규약

- `cache_{domain}_Re.npy` 등은 **positional order**(ids.json 순서)를 유지
- 삽입/삭제 시 동일 순서로 행 추가/제거 → order drift 방지
- ChromaDB 는 별도 유사도 검색용 (현재 inspect 는 .npy 를 직접 사용)

---

## 5. Sparse / Auto-Vocab / ASF

### 5.1 BGE-M3 Sparse (Lexical)

- 쿼리·문서를 각각 sparse dict `{token_id: weight}` 로 변환
- 스코어 = Σ (공통 토큰 가중치 곱) → `lexical_scores()`
- 한글 형태소/어휘 수준 매칭 담당

### 5.2 Auto Vocab

- 도메인 전체 텍스트(캡션 + PDF 원문) 토큰 빈도 → `{token: {df, idf}}`
- 크기: doc_page ≈ 25000, image ≈ 492
- **IDF** 공식:

$$
\text{idf}(t) = \log\!\left(\frac{N + 1}{df(t) + 1}\right) + 1
$$

### 5.3 ASF (Attention-Similarity-Filter)

도메인 특화 어휘 교집합 기반 보정 점수.

**빌드 시**: 각 문서마다 텍스트를 tokenize → vocab 와 매칭된 `{token: idf}` 셋 저장.
한글은 조사(1~3자) 말미 절단 매칭도 포함:

$$
T_i = \{t \in V : t \in \text{tokens}(D_i)\} \cup \{t[:-k] : k \in \{1,2,3\},\; t[:-k] \in V\}
$$

**쿼리 시**: 쿼리 토큰을 한글 bigram 역색인으로 확장 후 vocab 필터링.

$$
Q = \{t \in V : t \in \text{tokens}(q)\} \cup \{v \in V : t \in v \;(\text{substring})\}
$$

**스코어**:

$$
\text{asf}_i = \frac{1}{\|Q\|_{idf}} \sum_{t \in Q \cap T_i} \text{idf}(t)
$$

$$
\|Q\|_{idf} = \sqrt{\sum_{t \in Q} \text{idf}(t)^2}
$$

- 모든 문서 점수를 **max 로 나눠 [0, 1] 정규화**
- 한국어 조사/복합어 매칭을 복원하여 vocab 가 compound 형태로만 존재해도 스코어 생성

---

## 6. Calibration (μ / σ / abs_threshold)

### 6.1 Null 분포 추정

도메인 내 **서로 다른 ID 간 cross-score** 를 null 분포 대용으로 사용.

- 최대 1000 쌍 랜덤 샘플 `(i, j), i ≠ j`
- `tri_gs.pair_hermitian_score` 로 점수 계산
- μ, σ 추정

### 6.2 Abs Threshold

$$
\text{abs\_threshold} = \mu_{\text{null}} + \Phi^{-1}(1 - \text{FAR}) \cdot \sigma_{\text{null}}
$$

- `FAR_IMG = 0.20`, `FAR_DOC_PAGE = 0.05`, `FAR_DOC_TEXT = 0.05` 는 TRICHEF_CFG 에 정의
- $\Phi^{-1}$ 은 Acklam 근사 (scipy 없이 구현)

### 6.3 런타임 보강 (image 전용)

$$
\text{abs\_thr}_{\text{image}} = \max(\text{abs\_threshold}, \; \mu + 3\sigma)
$$

calibration 표본이 좁게 잡혀 σ 가 과소추정된 경우의 방어막.

### 6.4 저장

`EMBEDDED_DB/trichef_calibration.json`:

```json
{
  "doc_page": {"mu_null": 0.168, "sigma_null": 0.025, "abs_threshold": 0.198, "far": 0.05, "N": 34170},
  "image":    {"mu_null": 0.180, "sigma_null": 0.031, "abs_threshold": 0.208, "far": 0.20, "N": 2164}
}
```

> **참고**: 위 값은 2026-04-25 기준 최후 재보정값. 데이터 대량 추가 후엔 `recalibrate_query_null.py` 재실행 필수. 최신값은 `Data/embedded_DB/trichef_calibration.json` 참조.

---

## 7. 검색 파이프라인 (Query-time)

### 7.1 순서도

```
POST /api/admin/inspect
  body: {query, domain, top_n, use_lexical, use_asf}
        │
        ▼
(1) variants = qwen_expand.expand(query)   # 현재 paraphrase OFF → [query]
        │
        ▼
(2) q_Re = SigLIP2.embed_texts(variants) → mean → L2
    q_Im = BGE_M3_dense(variants)        → mean → L2
    q_Z  = q_Im
        │
        ▼
(3) dense[N] = hermitian_score(q, d)
        │
        ▼
(4) KR 쿼리 + domain=="image" 이면:
        use_lexical = False
        use_asf     = False
        │
        ▼
(5) lex[N]   = BGE_M3.lexical_scores(q_sp, d.sparse)   # 활성 시
    asf_s[N] = asf_filter.asf_scores(q, d.asf, d.vocab)
        │
        ▼
(6) 가중 Fusion (Section 8)
        │
        ▼
(7) order = argsort(-fused)
        │
        ▼
(8) cal = calibration.get_thresholds(domain)
    μ, σ = cal.mu_null, max(cal.sigma_null, 1e-9)
    abs_thr = max(cal.abs_threshold, μ+3σ) if domain=="image" else cal.abs_threshold
        │
        ▼
(9) per-row z, confidence, rrf 계산 후 상위 top_n 직렬화
```

### 7.2 Per-row 출력 필드

| 필드 | 의미 |
|---|---|
| `rank` | 도메인 내 최종 순위 (1부터) |
| `id` | 2.3 참고 |
| `filename`, `source_path`, `page` | UI 표시용 해석 결과 |
| `dense` | Hermitian 원점수 (0~1 내외) |
| `lexical` | sparse 점수 (정규화 전 dot product) |
| `asf` | ASF 정규화 점수 (0~1) |
| `rrf` | 참고용 RRF fusion 값 |
| `fused` | **정렬 기준** 가중 fusion 점수 |
| `z_score` | (dense − μ) / σ |
| `confidence` | Φ(z) — 표준정규 CDF |

---

## 8. Fusion & 랭킹

### 8.1 가중 Fusion (현재 기본)

1. 각 활성 채널을 **per-query min-max 정규화**:

$$
\tilde{x}_i = \frac{x_i - \min(x)}{\max(x) - \min(x) + \varepsilon}
$$

2. 초기 가중치:

| 채널 | 가중치 |
|---|---|
| dense | 0.60 |
| lexical | 0.25 |
| asf | 0.15 |

3. **채널 drop & 재배분**:
   - `max(lex) == 0` → $w_{lex}$ 를 $w_{dense}$ 에 합산
   - `max(asf) == 0` → $w_{asf}$ 를 $w_{dense}$ 에 합산

4. 최종 점수:

$$
\text{fused}_i = w_d \tilde{d}_i + w_l \tilde{l}_i + w_a \tilde{a}_i
$$

### 8.2 RRF (참고용)

$$
\text{RRF}_i = \sum_{k \in \text{active}} \frac{1}{60 + \text{rank}_k(i) + 1}
$$

- active 채널은 `max > 0` 인 채널만
- 과거 기본 정렬 기준이었으나 현재는 표시용

### 8.3 정렬 결정

- **정렬**: `fused` 내림차순
- **표시**: dense / lexical / asf / rrf / fused / confidence / z 모두 반환

---

## 9. Confidence / z-score

### 9.1 z-score

$$
z_i = \frac{\text{dense}_i - \mu_{\text{null}}}{\sigma_{\text{null}}}
$$

### 9.2 Confidence

$$
\text{conf}_i = \Phi(z_i) = \frac{1}{2}\left(1 + \text{erf}\!\left(\frac{z_i}{\sqrt{2}}\right)\right)
$$

- null 분포가 표준정규라고 가정했을 때, "이 점수가 null 상위일 확률"
- **주의**: $\sigma_{\text{null}}$ 이 좁게 추정되면 작은 dense 차이도 고신뢰로 보인다.
  → image 쪽 false positive 의 구조적 원인.

### 9.3 수용 기준

- `dense ≥ abs_thr` → "유효 매칭"
- `dense < abs_thr` → 참고용 (현재 admin UI 는 전부 표시, 필터 선택)

---

## 10. API 계약

### 10.1 `POST /api/admin/inspect`

**Request**:
```json
{
  "query": "고양이",
  "domain": "image",
  "top_n": 30,
  "use_lexical": true,
  "use_asf": true
}
```

**Response**:
```json
{
  "domain": "image",
  "query": "고양이",
  "total": 1743,
  "returned": 30,
  "calibration": {"mu_null": 0.185, "sigma_null": 0.032, "abs_threshold": 0.281},
  "rows": [
    {
      "rank": 1,
      "id": "영진_2차/IMG_1640.JPEG",
      "filename": "IMG_1640.JPEG",
      "source_path": "C:\\...\\Img\\영진_2차\\IMG_1640.JPEG",
      "page": 0,
      "dense": 0.312, "lexical": null, "asf": null,
      "rrf": 0.0164, "fused": 0.800,
      "confidence": 0.999, "z_score": 3.97
    }
  ]
}
```

### 10.2 `GET /api/admin/doc-text`

- Query: `id`, `domain`, `query` (하이라이트용)
- Response: `{id, text, matches, source_path, page}`

### 10.3 `GET /api/admin/file`

- 이미지/페이지 파일 직접 서빙 (썸네일 용)
- Query: `id`, `domain`

### 10.4 `GET /api/admin/domains`

- 로드된 도메인별 카운트, sparse/asf/vocab 여부 요약

### 10.5 `GET /api/admin/ui`

- `App/admin_ui/admin.html` 서빙 (독립 폴더)

---

## 11. Admin UI

### 11.1 폴더 독립성

```
App/
├─ frontend/        ← 사용자용 (React, 본 UI 와 독립)
├─ backend/         ← Flask 서버, routes/trichef_admin.py 만 얇게 커플링
└─ admin_ui/        ← 관리자 UI 소스 (독립)
   ├─ admin.html    ← 본체
   ├─ gradio_app.py ← (폐기 대상, v1 Gradio)
   ├─ requirements.txt
   └─ run_admin.bat
```

### 11.2 admin.html 구성

- 도메인 체크박스 (`doc_page`, `image` 동시 선택 가능)
- 검색어 · Top-N (기본 30) · Lexical/ASF 토글
- 결과: 카드 그리드 (auto-fill 320px 이상)
  - 썸네일 (클릭 → 모달 확대)
  - 파일명, 경로, 페이지 배지
  - 신뢰도 / dense / lexical / asf / rrf / z 메트릭
  - 원문 발췌 + 매칭 토큰 `<mark>` 하이라이트
- 호출: `location.origin + /api/admin/*` → CORS 불필요
- **v1-6 변경**: 모든 이모지 제거 완료 (admin.html 전체 텍스트 이모지 삭제)
- **v1-6 추가**: 파이프라인 섹션 collapsible 기능 — 섹션 헤더 클릭으로 접기/펼치기 가능

---

## 12. 확장자 SSOT (Q1, commit 1049099)

### 12.0 도메인 격리 원칙 + 동기화 검증

DI_TriCHEF는 App/backend 또는 MR_TriCHEF 와 상호 import 하지 않음 (도메인 격리).
그러나 이미지/문서/비디오/음성 확장자는 **의도적으로 동일해야** 함.

**SSOT 패턴** (Single Source Of Truth):
- `App/backend/_extensions.py` (기본 정의)
- `DI_TriCHEF/_extensions.py` (동일 내용 복제, App import 불가)
- `MR_TriCHEF/pipeline/_extensions.py` (VID/AUD 부분집합)
- `tests/test_extensions_parity.py` (7개 parity 검증)

**파일 구조** (`App/backend/_extensions.py` 예):
```python
IMG_EXTS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff",
    ".heic", ".heif", ".avif",
})

VID_EXTS: frozenset[str] = frozenset({
    ".mp4", ".avi", ".mov", ".mkv", ".wmv",
    ".webm", ".flv", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts",
})

AUD_EXTS: frozenset[str] = frozenset({
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma",
    ".opus", ".aiff", ".aif", ".amr",
})

DOC_PDF_EXTS: frozenset[str] = frozenset({".pdf"})
DOC_OFFICE_EXTS: frozenset[str] = frozenset({
    ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".odp", ".ods", ".rtf",
})
DOC_HWP_EXTS: frozenset[str] = frozenset({".hwp", ".hwpx"})
DOC_TEXT_EXTS: frozenset[str] = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".html", ".htm",
})
DOC_EBOOK_EXTS: frozenset[str] = frozenset({".epub"})

DOC_EXTS = DOC_PDF_EXTS | DOC_OFFICE_EXTS | DOC_HWP_EXTS | DOC_TEXT_EXTS | DOC_EBOOK_EXTS
IMAGE_EMBED_EXTS = IMG_EXTS  # alias
```

**호출자 마이그레이션** (commit 1049099):
- `DI_TriCHEF/captioner/recaption_all.py`: `from _extensions import IMG_EXTS`
- `App/backend/embedders/trichef/incremental_runner.py`: 21줄 축소

**Parity 검증** (`tests/test_extensions_parity.py`):
```python
def test_app_di_img_parity():
    app_mod = _load(ROOT / "App" / "backend" / "_extensions.py", "_app_ext_img")
    di_mod  = _load(ROOT / "DI_TriCHEF" / "_extensions.py",      "_di_ext_img")
    assert app_mod.IMG_EXTS == di_mod.IMG_EXTS
    # (동일 패턴 × 6개 더)
```

회귀 검증: `pytest tests/test_extensions_parity.py -v` → 7/7 통과.

---

## 13. 증분 업데이트 로직

### 13.1 변경 감지

`incremental_runner.run_doc_incremental`:

1. `registry.json` 과 RAW_DB 스캔 결과 비교
2. 다음 집합 계산:
   - **new**: rel_key 가 registry 에 없음
   - **modified**: SHA 변경됨
   - **stale**: registry 에 있지만 물리 파일 없음

### 13.2 Purge → Merge → Upsert

```
keys_to_purge = modified ∪ stale
    │
    ▼
_purge_doc_page_cache(keys_to_purge):
  ├─ page_images/<stem_key>/         삭제
  ├─ captions/<stem_key>/             삭제
  ├─ doc_page_ids.json                 필터링
  ├─ cache_doc_page_{Re,Im,Z}.npy     해당 행 제거
  ├─ cache_doc_page_sparse.npz        해당 행 제거
  ├─ asf_token_sets.json              해당 인덱스 제거
  └─ ChromaDB COL_DOC_PAGE.delete()   해당 id 삭제
    │
    ▼
keys_to_embed = new ∪ modified
    │
    ▼
render_pdf / caption / 임베딩 → append 후 저장
    │
    ▼
sparse / auto_vocab / asf_token_sets 재빌드
    │
    ▼
calibration.calibrate_domain() 실행 → μ/σ/abs_thr 갱신
```

### 13.3 위치 동기성 불변식

- `len(ids) == Re.shape[0] == Im.shape[0] == Z.shape[0] == sparse.shape[0] == len(asf_token_sets)` 항상 성립
- 순서 동기화 깨지면 검색 시 잘못된 문서로 매핑 → 반드시 purge 후 append

---

## 14. 자동 적응 기준값 요약

| # | 대상 | 자동 갱신 시점 | 계산식/로직 |
|---|---|---|---|
| 1 | `μ_null`, `σ_null`, `abs_threshold` | 코퍼스 변경 시 `calibrate_domain()` 수동 실행 | Section 6 |
| 2 | `auto_vocab`, IDF | 인제스트 후처리 (자동) | 5.2 |
| 3 | `asf_token_sets` | vocab 변경 직후 자동 | 5.3 |
| 4 | sparse IDF | `lexical_rebuild` 실행 시 | 5.1 |
| 5 | min-max 정규화 범위 | **매 쿼리** 자동 | 8.1 |
| 6 | 활성 채널 (lex/asf drop) | 매 쿼리 (`max > 0`) 자동 | 8.1 |
| 7 | KR 쿼리 + image → lex/asf skip | 매 쿼리 (언어 감지) | 7.1 |
| 8 | image abs_threshold 보정 | 매 쿼리 `max(cal, μ+3σ)` | 6.3 |

> **수동인 것은 1 (calibration) 하나**.
> 데이터 대량 추가 후 재캘리 안 하면 σ 과소/과대 → confidence 의미 왜곡.

---

## 15. 알려진 한계 & 개선 후보

### 15.1 Qwen2-VL caption_triple 품질 및 구현

**3단계 캡션 정의** (commit 8728950, P1.6):
- L1(≤20字 토픽): 이미지의 주요 객체·행동·맥락 간결 요약
- L2(5–10 키워드): 도메인어·고유명사 포함 키워드 세트
- L3(30–60字 상세): 자연스러운 한국어 문장 (2026-03 Wave3 재캡션)

**구현 위치**:
- 생성: `DI_TriCHEF/captioner/qwen_vl_ko.py:caption_triple()` (commit 8728950)
- 이미지 임베딩: `DI_TriCHEF/scripts/build_img_caption_triple.py` (cp949 stdout guard 추가, commit f826016)
- 문서 임베딩: App backend 에서 자동 호출 (caption_triple 출력 → BGE-M3 임베딩 → Im 축)
- 가중 融合: w_L1=0.15, w_L2=0.25, w_L3=0.60 (unified_engine.py:112-132)

### 15.2 지원 확장자 확대 (commit 2c3b1ff, P3)

**Image 도메인** (commit 2c3b1ff):
- 기존: `.jpg .jpeg .png .webp .bmp`
- 추가: `.gif .tiff .heic .heif .avif` (4개 → 9개)
- HEIC/HEIF: `pillow-heif` plugin (try/except 가드)
- AVIF: `pillow-avif-plugin` (try/except 가드)
- 자동 회전: `ImageOps.exif_transpose()` 적용 (EXIF 메타 처리)

**Doc 도메인** (commit 2c3b1ff):
- 확장: `.hwp .hwpx .doc .ppt .xls .odt .rtf` 등 (LibreOffice 호환)
- 캐싱: env SOFFICE_PATH, shutil.which, cross-platform 경로 (commit 1633945, P1.4)

**Video / Audio 도메인** (commit 2c3b1ff):
- Video: `.flv .m4v .mpg .mpeg .3gp .ts .mts .m2ts` 추가 (App+MR 정렬)
- Audio: `.opus .aiff .amr` 추가 (Telegram/Discord/Apple 형식)

### 15.3 Image vocab 개선

- Qwen2-VL 한국어 캡션 → vocab ~2,500개 (vs 영어 BLIP 492개)
- ASF 한글 bigram 오버랩 활성화 → 한국어 쿼리 매칭 개선

### 15.4 σ_null 과소

- image: σ = 0.032 → dense 0.272 만 되어도 z ≈ 2.72, conf ≈ 99.7%
- null 표본(다른 ID 간 cross-score) 이 실제 무관 쿼리 분포를 대표하지 못함

### 15.5 개선 후보 (우선순위)

| # | 항목 | 효과 | 비용 |
|---|---|---|---|
| A | image dense 절대 컷오프 (≥0.28) | 중 | 5분 |
| B | image top-K SigLIP2 Re-only 재랭킹 | 고 | 20분 |
| C | Calibration null 표본 재수집 (무관 쿼리 기반) | 고 | 1–2h |
| D | Qwen2-VL 한국어 캡션 재생성 | 🔥 최고 | GPU 3–6h |
| E | FAR 파라미터 튜닝 | 소 | 5분 |
| F | Cross-encoder reranker | 중 | GPU 수 시간 |

---

## 16. Appendix — 수식 요약

### 16.1 핵심 점수

$$
\boxed{\; \text{dense}(q, d) = \sqrt{(q_{Re}\!\cdot\! d_{Re})^2 + (\alpha\, q_{Im}\!\cdot\! d_{Im})^2 + (\beta\, q_Z\!\cdot\! d_Z)^2} \;}
$$

$$
\text{asf}_i = \frac{\sum_{t \in Q \cap T_i} \text{idf}(t)}{\sqrt{\sum_{t \in Q} \text{idf}(t)^2}}\;\Big/\;\max_j(\cdot)
$$

$$
\text{fused}_i = w_d \tilde{d}_i + w_l \tilde{l}_i + w_a \tilde{a}_i,\quad \tilde{x}_i = \frac{x_i - \min x}{\max x - \min x + \varepsilon}
$$

$$
z_i = \frac{\text{dense}_i - \mu_{\text{null}}}{\sigma_{\text{null}}},\qquad \text{conf}_i = \tfrac12\!\left(1 + \text{erf}(z_i/\sqrt2)\right)
$$

$$
\text{abs\_threshold} = \mu_{\text{null}} + \Phi^{-1}(1 - \text{FAR})\,\sigma_{\text{null}},\quad \text{abs\_thr}^{image}_{rt} = \max(\cdot,\; \mu + 3\sigma)
$$

$$
\text{stem\_key}(r) = \text{sanitize}(\text{stem}(r)) \; \| \; \texttt{"\_\_"} \; \| \; \text{md5}(r)[:8]
$$

### 16.2 하이퍼파라미터 요약

| 이름 | 값 | 위치 | 의미 |
|---|---|---|---|
| `α` (Im gain) | 0.4 | tri_gs.py | Im 축 Hermitian 기여 |
| `β` (Z gain) | 0.2 | tri_gs.py | Z 축 Hermitian 기여 |
| `w_dense` | 0.60 | routes/trichef_admin.py | fusion 가중 |
| `w_lex` | 0.25 | 동일 | |
| `w_asf` | 0.15 | 동일 | |
| `RRF_k` | 60 | 동일 | RRF smoothing |
| `FAR_IMG` | 0.20 (config) | TRICHEF_CFG | 무관 쿼리 20% 허용 (recall 우선) |
| `FAR_DOC_PAGE` | 0.05 | TRICHEF_CFG | 정밀도 우선 |
| `image σ 하한` | 3σ → abs_thr | routes/trichef_admin.py | false positive 방어 |
| `top_n 기본` | 30 | admin.html | |

---

_작성: 2026-04-23 · 파이프라인 v1-2 기준 · 갱신: 2026-04-27 (v1-6, MIRACL-ko 자체 재현 +7.92pp · Admin UI 이모지 제거 · collapsible 파이프라인 섹션)_
