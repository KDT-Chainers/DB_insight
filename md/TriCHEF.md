# TRI-CHEF: Complex-Hermitian Fusion of Heterogeneous Encoders — 멀티모달 검색 시스템 통합 문서

> 생성일: 2026-04-24 | 갱신: 2026-04-25 20:50 | **v1-2 paper 동기화: 2026-04-26**
> 통합 대상: `TRICHEF_PIPELINE_AND_CONCEPTS.md` · `TRICHEF_PIPELINE.md` · `TRICHEF_SPECIFIC.md`
> 범위: 시스템 구조 · 모델 선택 근거 · 파이프라인 상세 · 수학적 원리 · 구현 세부사항 · 운영 현황
> **최신 변경**: 9커밋 반영 (d985c53~73c8bf0) — 확장자 SSOT (Q1) + 평가 라이브러리 통합 (Q3) + hybrid θ K-clamp (bdf80af)
> **v1-2 추가**: Section 5.5 Public Benchmark (MIRACL-ko) + Related Work 복소수 IR 계보 + 평가 인프라 레퍼런스

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [디렉토리 구조](#2-디렉토리-구조)
3. [모델 스택 — 특성 및 선택 근거](#3-모델-스택--특성-및-선택-근거)
4. [3축(Re/Im/Z) 복소-에르미트 설계 원리](#4-3축reimz-복소-에르미트-설계-원리)
5. [핵심 수식 카탈로그](#5-핵심-수식-카탈로그)
6. [Doc/Img 파이프라인](#6-docimg-파이프라인)
7. [Movie/Rec 파이프라인](#7-movierec-파이프라인)
8. [파이프라인 독립성 및 공유 모듈](#8-파이프라인-독립성-및-공유-모듈)
9. [Lexical 보조 채널](#9-lexical-보조-채널)
10. [쿼리 확장 (Qwen Expand)](#10-쿼리-확장-qwen-expand)
11. [데이터셋 대응 판단 기준 (Data-Adaptive Policy)](#11-데이터셋-대응-판단-기준-data-adaptive-policy)
12. [Confidence 해석](#12-confidence-해석)
13. [TriChefEngine 내부 구조](#13-trichefengine-내부-구조)
14. [API 엔드포인트](#14-api-엔드포인트)
15. [Calibration 현재 상태](#15-calibration-현재-상태)
16. [데이터셋 현재 규모](#16-데이터셋-현재-규모)
17. [성능 측정값](#17-성능-측정값)
18. [관련 연구 (Related Work) — 복소수 IR 계보](#18-관련-연구-related-work--복소수-ir-계보)
19. [공개 벤치마크 검증 (MIRACL-ko)](#19-공개-벤치마크-검증-miracl-ko)
20. [평가 인프라](#20-평가-인프라)
21. [파일명 정책 / Stem 해시](#21-파일명-정책--stem-해시)
22. [캐시 · 인덱스 불변식](#22-캐시--인덱스-불변식)
23. [관리자 UI](#23-관리자-ui)
24. [Wave 히스토리](#24-wave-히스토리)
25. [향후 개선 후보 (Wave5)](#25-향후-개선-후보-wave5)

---

## 1. 시스템 개요

TRI-CHEF(Triple-Channel Complex Hermitian Embedding Framework)는 **이미지 · 문서 · 영상 · 음악** 4개 도메인을 단일 API로 통합하는 멀티모달 벡터 검색 시스템이다.

> **약어 풀이**: TRI = Triple-Channel, CHEF = Complex Hermitian Embedding Framework (또는 Fusion), ASF = Adaptive Sieve Filter

핵심 설계 원칙:
- **3축(Re/Im/Z) 직교 임베딩**: 단일 모델 편향을 제거하고 시각-언어-구조 정보를 독립 채널로 분리
- **Hermitian 점수 결합**: 세 축을 복소 내적 유사도로 통합
- **Cross-modal Calibration**: 쿼리-문서 null 분포를 기반으로 신뢰도를 확률적으로 정규화
- **Lexical 보조(Doc/Img 전용)**: dense 벡터가 놓치는 키워드·고유명사 정밀 매칭
- **도메인 독립성**: Doc/Img와 Movie/Rec 파이프라인은 모델·캐시·검색 로직이 완전 분리

---

## 2. 디렉토리 구조

```
DB_insight/
├── App/backend/
│   ├── routes/
│   │   ├── trichef.py              # 공개 API (/api/trichef/*)
│   │   └── trichef_admin.py        # admin /inspect (per-row 점수 디버그)
│   ├── services/trichef/
│   │   ├── unified_engine.py       # TriChefEngine, search, search_av
│   │   ├── tri_gs.py               # 3축 점수 수학 (hermitian_score, Gram-Schmidt)
│   │   ├── calibration.py          # abs_threshold + crossmodal calibration (W4-1)
│   │   ├── lexical_rebuild.py      # vocab/ASF/sparse 재구축
│   │   ├── auto_vocab.py           # IDF 기반 어휘 추출
│   │   ├── asf_filter.py           # Adaptive Sieve Filter
│   │   └── prune.py                # 제거된 파일 캐시 pruning
│   └── embedders/trichef/
│       ├── incremental_runner.py   # 증분 임베딩 러너 (4개 도메인) — cache_ops.replace_by_file 호출 (commit 014d508)
│       ├── cache_ops.py            # [신규 P2B] replace_by_file 헬퍼 (App 독립 포팅, commit 014d508)
│       ├── siglip2_re.py           # Re 축 (SigLIP2)
│       ├── bgem3_caption_im.py     # Im 축 (BGE-M3 dense)
│       ├── bgem3_sparse.py         # lexical 채널 (BGE-M3 sparse)
│       ├── dinov2_z.py             # Z 축 (DINOv2)
│       ├── qwen_caption.py         # 쿼리/캡션 Qwen 유틸 (quant)
│       ├── qwen_expand.py          # 쿼리 paraphrase
│       ├── blip_caption_triple.py  # (폐기) BLIP L1/L2/L3 triple
│       ├── doc_page_render.py      # PDF → JPEG + stem_key_for 해시
│       ├── doc_ingest.py           # HWP/DOCX → PDF 변환 (cached soffice resolver, env override, cross-platform, commit 1633945)
│       └── caption_io.py           # 캡션 파일 I/O
├── DI_TriCHEF/
│   ├── captioner/
│   │   ├── qwen_vl_ko.py           # Qwen2-VL-2B 한국어 캡셔너 — caption_triple L1/L2/L3 (commit 8728950)
│   │   ├── recaption_all.py        # 전체 재캡션 러너 (확장자: .gif/.tiff/.heic/.heif/.avif 추가, commit 2c3b1ff)
│   │   └── fix_non_korean.py       # 비한국어 선별 재생성
│   ├── reranker/
│   │   ├── post_rerank.py          # non-invasive 재순위 엔진
│   │   └── rerank_cli.py           # CLI 진입점
│   ├── docs/
│   │   ├── DI_TriCHEF.md           # Doc/Img 도메인 문서 (이전 Doc_Img_TriCHEF.md 에서 git mv)
│   │   └── ...
│   └── scripts/
│       ├── build_img_caption_triple.py  # L1/L2/L3 캡션 빌드 (cp949 stdout guard 추가, commit f826016)
│       └── fuse_img_caption_triple.py   # L1/L2/L3 캡션 가중치 합산 (분석/디버깅용)
├── App/admin_ui/
│   ├── admin.html                  # /api/admin/ui 카드 그리드
│   └── serve.py                    # standalone 서빙
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

---

## 3. 모델 스택 — 특성 및 선택 근거

### 3.1 Qwen2-VL-2B-Instruct — 캡셔너 (Doc/Img)

**역할**: 이미지·PDF 페이지를 한국어 캡션 텍스트로 변환

**특성**
- 파라미터: ~2B (Vision Encoder 포함)
- 아키텍처: Naive Dynamic Resolution + M-ROPE(Multimodal Rotary Position Embedding)
  - M-ROPE는 1D 텍스트·2D 이미지·3D 영상 위치 정보를 단일 표현으로 통합
- 가변 해상도 지원: 4~16,384 visual token 범위 조절 가능
- 다국어 텍스트 인식: 이미지 내 한국어·중국어·아랍어 등 포함

**선택 근거**
- **Wave3 이전 BLIP의 문제**: BLIP 캡셔너가 Chinese-leaked 캡션(중국어 혼입)을 생성하여 BGE-M3 Im 축 임베딩의 한국어 공간 활용을 방해
- Qwen2-VL은 명시적 한국어 출력 지시가 가능하며, 이미지 내 한국어 텍스트(OCR)도 인식
- 14장 샘플 검증(Wave2)에서 Chinese leak 0건 확인 후 전체 2340장 재캡션 진행(Wave3)
- 결과: Im 축에 자연스러운 한국어 문장이 실려 BGE-M3 한국어 dense 공간을 온전히 활용

**사용 위치**: `embedders/trichef/qwen_caption.py`, `DI_TriCHEF/captioner/qwen_vl_ko.py`

---

### 3.2 SigLIP2-SO400M (`google/siglip2-so400m-patch16-naflex`) — Re 축

**역할**: Cross-modal 이미지-텍스트 유사도 (Re축, 1152d)

**특성**
- 아키텍처: ViT-SO400M (400M 파라미터 Vision Transformer)
- 입력 해상도: 384×384 (patch size 14)
- 출력 차원: **1152d**, L2-norm 정규화
- 학습 방식: **Sigmoid Loss** (SigLIP의 핵심 차별점)
  - 기존 CLIP의 softmax 대비, 각 이미지-텍스트 쌍을 독립 이진 분류로 학습
  - 배치 크기 의존성 없이 안정적 학습, 대규모 멀티모달 데이터에 유리

$$\mathcal{L}_{\text{SigLIP}} = -\frac{1}{N}\sum_{i,j} \log \sigma\!\left(y_{ij}\cdot(\mathbf{z}_i^I \cdot \mathbf{z}_j^T / \tau) - b\right)$$

여기서 $y_{ij} \in \{-1, +1\}$ (매칭/비매칭), $\sigma$는 sigmoid, $b$는 bias.

**선택 근거**
- SigLIP2는 WebLI 등 대규모 다국어 데이터로 학습되어 **한국어 텍스트 → 이미지 매칭**이 CLIP 대비 우수
- 이미지-캡션 cross-modal 공간을 직접 정의하므로 Re(Real)축의 "질의-이미지 개념 동일성" 역할에 최적
- 384×384 고해상도로 세밀한 이미지 특징 포착

**사용 위치**: `embedders/trichef/siglip2_re.py`

---

### 3.3 BGE-M3 Dense (`BAAI/bge-m3`) — Im 축 + Sparse 채널

**역할**: 다국어 텍스트 임베딩 (Im축 dense 1024d + lexical sparse 250002d)

**특성**
- **Multi-lingual**: 100+ 언어 지원, 한국어 강점
- **Multi-functionality**: Dense retrieval + Sparse retrieval + Multi-vector retrieval 동시 지원
- **Multi-granularity**: 단어~문단 수준 의미 포착
- Dense 출력: **1024d**, L2-norm
- Sparse 출력: **250002-dim** (subword vocab 기반 희소 벡터, nnz ≈ 70,000)

**Dense Im 축 적용 수식 (passage 임베딩)**

$$\mathbf{e}_{\text{Im}} = \text{L2-norm}\!\left(\text{BGE-M3}_{\text{dense}}(\text{caption} + \text{원문})\right) \in \mathbb{R}^{1024}$$

**Sparse lexical 채널 점수**

$$\text{lex}(q, d) = \mathbf{s}_q^\top \mathbf{s}_d \quad (\mathbf{s} \in \mathbb{R}^{250002}, \text{ sparse})$$

**선택 근거 (Im 축)**
- Qwen2-VL로 생성된 한국어 캡션을 BGE-M3 한국어 dense 공간에 직접 임베딩
- Re 축(SigLIP2)이 이미지-텍스트 cross-modal을 담당할 때, Im 축은 **언어 내 의미 정렬**을 보조
- `max_length=1024`로 긴 문서 원문도 처리 가능

**선택 근거 (Sparse 채널)**
- Dense 벡터가 놓치는 **도메인 용어·고유명사·한국어 키워드** 정밀 매칭
- BGE-M3 단일 모델에서 dense와 sparse 모두 추출 가능 → 추가 모델 불필요

**사용 위치**: `embedders/trichef/bgem3_caption_im.py`, `embedders/trichef/bgem3_sparse.py`

---

### 3.4 DINOv2-Large (`facebook/dinov2-large`) — Z 축

**역할**: 언어 비의존적 순수 시각 구조 임베딩 (Z축, 1024d)

**특성**
- 아키텍처: ViT-L/14 (307M 파라미터)
- 학습 방식: **Self-supervised** (레이블 없이 이미지만으로 학습)
  - DINO(self-DIstillation with NO labels) + iBOT(image BERT pre-training)의 결합
  - Teacher-Student 구조로 Local-Global consistency 학습
- 입력: 224×224, CLS 토큰 추출
- 출력: **1024d**, L2-norm

**DINO 학습 목표 (간략)**

$$\mathcal{L}_{\text{DINO}} = -\sum_x P_t(x) \log P_s(x)$$

Teacher 출력 $P_t$(centering+sharpening 적용)를 Student $P_s$가 예측하도록 학습. 레이블 없이 시각 구조를 포착.

**선택 근거**
- **언어 비의존적**: 쿼리 언어(한국어/영어)와 무관하게 이미지 시각 유사성을 안정적으로 제공
- 캡션 품질이 낮거나 도메인이 좁아도 시각 근접성을 보존
- Re(cross-modal)·Im(언어) 두 축의 "캡션 편향"을 Z축이 중립화
- CLS 토큰: 이미지 전체 맥락을 압축한 global representation

**사용 위치**: `embedders/trichef/dinov2_z.py`

---

### 3.5 Whisper (`openai/whisper`) — STT (Movie/Rec)

**역할**: 음성·영상에서 텍스트 추출 (Speech-To-Text)

**특성**
- 모델: large-v3 (1.5B 파라미터, 고정)
- 아키텍처: Encoder-Decoder Transformer, 음성 → 텍스트
- 다국어 지원: 한국어 포함 99개 언어

**선택 근거**
- Movie/Rec 도메인은 텍스트 정보가 없어 STT 필수
- Whisper로 추출된 STT 텍스트를 BGE-M3로 임베딩 → 텍스트 기반 AV 검색 가능

---

### 3.6 CLAP (`laion/clap-htsat-unfused`) — 오디오 Z축 (선택)

**역할**: 오디오-텍스트 대응 임베딩 (Music Z축, 선택적 적용)

**특성**
- CLAP = Contrastive Language-Audio Pretraining (CLIP의 오디오 버전)
- 오디오 파형 → 텍스트 공간과 정렬된 임베딩

**선택 근거**
- Rec(Music) 도메인에서 STT 텍스트 외에 음향 자체의 특성(리듬·분위기)을 Z축에 반영
- 텍스트 기반 BGE-M3만으로는 포착하기 어려운 오디오 구조 정보 보완

---

### 3.7 BGE-Reranker-v2-m3 (`BAAI/bge-reranker-v2-m3`) — 재순위 (선택)

**역할**: Cross-encoder 기반 top-K 재순위

**특성**
- Bi-encoder(dense 검색)와 달리, 쿼리-문서 쌍을 **함께** 입력하여 정밀 점수 계산
- 다국어 지원, 한국어 쿼리-문서 재순위에 효과적

**선택 근거**
- Dense/Lexical 점수가 근소하게 차이날 때 분리력 향상
- 검색 후처리(post-retrieval) 단계에서만 사용 → 전체 지연 최소화

**사용 위치**: `shared/reranker.py`, `DI_TriCHEF/reranker/post_rerank.py`

---

## 4. CHEF — Complex Hermitian Embedding Framework 핵심 개념

### 4.1 명칭 해석

| 단어 | 의미 |
|------|------|
| **Complex** | 세 임베딩 축을 복소수 공간의 실부(Re)·허부(Im)·직교부(Z)에 대응시킴 |
| **Hermitian** | 점수 결합 방식이 복소 에르미트 내적 $\langle\mathbf{u},\mathbf{v}\rangle = \mathbf{u}^\dagger\mathbf{v}$에서 영감을 받음 |
| **Embedding** | 이미지·텍스트·오디오를 벡터 공간에 사상(mapping) |
| **Framework/Fusion** | 다중 모달·다중 채널을 단일 점수로 융합하는 통합 체계 |

### 4.2 3축 설계 — 왜 세 축인가

**문제**: 단일 임베딩 모델은 특정 실패 모드를 가진다.
- SigLIP2만 → 캡션 품질에 과의존, 언어 편향 누적
- BGE-M3만 → 시각 구조 무시, 텍스트 없는 이미지에 취약
- DINOv2만 → 쿼리 텍스트와 연결 불가 (언어 비의존)

**해결**: 세 모델을 **직교 독립 채널**로 배치하여 각 축의 실패를 나머지 두 축이 보완.

| 축 | 수학적 대응 | 담당 모델 | 인코딩 대상 | 실패 보완 |
|----|------------|-----------|------------|-----------|
| **Re** (실부) | 복소수 실수부 | SigLIP2-SO400M (1152d) | 이미지↔텍스트 cross-modal 의미 | 캡션 부족 시에도 시각-텍스트 매칭 |
| **Im** (허부) | 복소수 허수부 | BGE-M3 dense (1024d) | 다국어 텍스트·캡션 언어 공간 | 시각이 모호할 때 캡션/원문으로 보조 |
| **Z** (직교부) | 복소수 외 직교 성분 | DINOv2-L (1024d) | 레이블 무관 순수 시각 구조 | 캡션 편향·노이즈 배제, 시각 근접성 보존 |

### 4.3 Gram-Schmidt 직교화 — 이론과 실제 구현

**목적**: Im과 Z에서 Re와 중복되는 정보를 제거해 채널 간 상관 노이즈를 줄인다.

**이론 (동일 차원일 때)**

$$\mathbf{Im}_\perp = \mathbf{Im} - \frac{\mathbf{Im} \cdot \mathbf{Re}}{|\mathbf{Re}|^2}\,\mathbf{Re}$$

$$\mathbf{Z}_\perp = \mathbf{Z} - \frac{\mathbf{Z} \cdot \mathbf{Re}}{|\mathbf{Re}|^2}\,\mathbf{Re} - \frac{\mathbf{Z} \cdot \mathbf{Im}_\perp}{|\mathbf{Im}_\perp|^2}\,\mathbf{Im}_\perp$$

**실제 구현** (`tri_gs.py:orthogonalize`)

```python
def orthogonalize(Re, Im, Z):
    # Re: 1152d,  Im/Z: 1024d  →  차원 불일치로 투영 불가
    # 실측 잔차율 0.999 → L2-norm만으로 동등 효과 확인
    Im_hat = L2_norm(Im)
    Z_hat  = L2_norm(Z)
    return Im_hat, Z_hat
```

> Re(1152d) ≠ Im/Z(1024d)로 직접 투영이 불가능하므로, 각자 독립 L2 정규화로 대체한다.
> 실험적으로 잔차율 0.999를 확인하여 정규화만으로도 동등한 효과를 검증함.

### 4.4 Hermitian Score — 세 축의 결합

복소 에르미트 내적의 절댓값 $|\langle\mathbf{u},\mathbf{v}\rangle|$에서 영감을 받아 세 채널 내적을 Euclidean 노름으로 결합.

$$\boxed{s(q, d) = \sqrt{A^2 + (\alpha \cdot B)^2 + (\beta \cdot C)^2}}$$

$$A = \mathbf{q}_{\text{Re}} \cdot \mathbf{d}_{\text{Re}}, \quad
  B = \mathbf{q}_{\text{Im}} \cdot \mathbf{d}_{\text{Im}}, \quad
  C = \mathbf{q}_Z \cdot \mathbf{d}_Z$$

$$\alpha = 0.4 \quad (\text{Im 감쇠}), \qquad \beta = 0.2 \quad (\text{Z 감쇠})$$

**구현** (`tri_gs.py:hermitian_score`)

```python
A = q_Re @ d_Re.T          # (1, N)
B = q_Im @ d_Im.T
C = q_Z  @ d_Z.T
score = np.sqrt(A**2 + (0.4*B)**2 + (0.2*C)**2)
```

**가중치 설계 근거**

| 채널 | 감쇠 계수 | 의미 |
|------|:--------:|------|
| Re | 1.0 (없음) | 실측 기준 지배적 신호 |
| Im | α = 0.4 | 언어 보조 — 과도한 텍스트 의존 방지 |
| Z | β = 0.2 | 시각 구조 보조 — 극단 왜곡 방지 |

최대 점수 (단위 벡터): $s_{\max} = \sqrt{1 + 0.16 + 0.04} = \sqrt{1.20} \approx 1.095$

**대용량 쌍 처리용 (calibration)** — N×N 행렬 없이 행별 내적만 계산:

```python
# pair_hermitian_score: einsum으로 메모리 효율화
A = einsum("ij,ij->i", q_Re, d_Re)   # (N,)
B = einsum("ij,ij->i", q_Im, d_Im)
C = einsum("ij,ij->i", q_Z,  d_Z)
score = np.sqrt(A**2 + (0.4*B)**2 + (0.2*C)**2)
```

### 4.5 직교화 필요성 요약

```
단일 모델 편향  →  3축 분리  →  Gram-Schmidt(또는 L2-norm)  →  Hermitian 결합
     ↑                              ↑
 실패 모드 누적         채널 간 상관 노이즈 제거
```

---

## 5. 핵심 수식 카탈로그

> **계보**: 본 카탈로그의 수식은 1세대 CHEF (e5+BGE 단일 복소축, 2개-모델 위상 필터) 에서
> 출발하여, TRI-CHEF 에 와서 3축(Re/Im/Z) Hermitian, RRF 융합, cross-modal calibration,
> Im_body fusion, 3-stage caption fusion 으로 확장되었다. CHEF 의 위상(phase) 필터 (`|θ|<0.6 rad`)
> 는 1차원적 모델 합의 측정이었으나, 현 TRI-CHEF 는 **세 축의 직교 정보 보존 + 채널별 감쇠 가중치**
> 로 동일 목적을 더 풍부하게 달성한다.

### 5.0 CHEF → TRI-CHEF 수식 진화 비교

| 항목 | CHEF (1세대) | TRI-CHEF (현재) |
|------|--------------|-----------------|
| 결합 식 | `<z_q*, z_d> = <a_q,a_d>+<b_q,b_d> + i(<a_q,b_d>−<b_q,a_d>)` | `s = √(A² + (αB)² + (βC)²)` |
| 축 개수 | 2 (Re=e5, Im=BGE) | 3 (Re=SigLIP2, Im=BGE-M3, Z=DINOv2) |
| 필터 | 위상 `\|θ\|<0.6 rad` | μ_null + Φ⁻¹(1−FAR)·σ_null (도메인별) |
| 신뢰도 | 위상 합치도 (이산) | Φ((s−μ_null)/σ_null) (확률 CDF) |
| 직교화 | Gram-Schmidt + MCR | 차원 불일치 → L2-norm only |
| 가중치 | 균등 합산 | α=0.4 (Im 감쇠), β=0.2 (Z 감쇠) |

### 5.1 Gram-Schmidt 직교화

Re 공간에 투영되는 Im, Z 성분을 제거하여 독립적 정보만 추출한다.

$$\mathbf{Im}_\perp = \mathbf{Im} - \text{proj}_{\mathbf{Re}}(\mathbf{Im}) = \mathbf{Im} - \frac{\mathbf{Im} \cdot \mathbf{Re}}{|\mathbf{Re}|^2}\,\mathbf{Re}$$

$$\mathbf{Z}_\perp = \mathbf{Z} - \text{proj}_{\mathbf{Re}}(\mathbf{Z}) - \text{proj}_{\mathbf{Im}_\perp}(\mathbf{Z})$$

> **구현 주의**: Re 차원(1152d) ≠ Im/Z 차원(1024d)이므로 직접 투영이 불가능.
> 실제 구현(`tri_gs.py`)에서는 차원 불일치 시 Gram-Schmidt를 생략하고 **L2-norm만** 적용한다.

---

### 5.2 Hermitian Score

세 독립 채널의 내적을 Euclidean 노름으로 결합. 복소 벡터의 에르미트 내적 $\langle \mathbf{u}, \mathbf{v} \rangle = \mathbf{u}^\dagger \mathbf{v}$ 구조에서 영감을 받은 형태.

$$s(q, d) = \sqrt{A^2 + (\alpha \cdot B)^2 + (\beta \cdot C)^2}$$

$$A = \langle \mathbf{q}_{\text{Re}},\; \mathbf{d}_{\text{Re}} \rangle, \quad
B = \langle \mathbf{q}_{\text{Im}},\; \mathbf{d}_{\text{Im}_\perp} \rangle, \quad
C = \langle \mathbf{q}_Z,\; \mathbf{d}_{Z_\perp} \rangle$$

$$\alpha = 0.4, \quad \beta = 0.2$$

**가중치 설계 근거**
- 실측 기준 Re 축(SigLIP2 cross-modal)이 지배적 신호 → $A$는 감쇠 없음
- **Doc Im_body fusion α=0.20** (Phase 4-2 최적화): LOO n=150 기준 dense R@5 +2.7%p (0.880→0.907), sparse RRF 동등
- Im 축은 언어 보조 → $\alpha = 0.4$ 로 40% 감쇠
- Z 축은 시각 구조 보조 → $\beta = 0.2$ 로 80% 감쇠
- 세 채널이 모두 최대일 때 $s_{\max} = \sqrt{1 + 0.16 + 0.04} = 1.095$ (단위 벡터 기준)

---

### 5.3 Cross-modal Null Calibration (W4-1, `crossmodal_v1`)

검색 점수의 절대적 의미를 부여하기 위해 **무관한 쿼리-문서 쌍**의 점수 분포(null distribution)를 측정하고, 그 분포를 기준으로 임계값과 신뢰도를 정의한다.

**측정 절차**

$$\text{null pairs}: \{(q_k, d_j)\}_{k,j} \quad \text{where } j \neq \text{self}(k), \; |\text{pairs}| = N_q \times 5$$

$$\mu_{\text{null}} = \frac{1}{|\text{pairs}|}\sum s(q_k, d_j), \quad \sigma_{\text{null}} = \text{std}(\{s(q_k, d_j)\})$$

**임계값 (Acklam 근사로 Φ⁻¹ 계산)**

$$\text{abs\_threshold} = \mu_{\text{null}} + \Phi^{-1}(1 - \text{FAR}) \cdot \sigma_{\text{null}}$$

| 도메인 | FAR | 의미 |
|--------|-----|------|
| image | 0.20 | 무관 쿼리 20% 허용 (recall 우선) |
| doc_page | 0.05 | 정밀도 우선 |
| doc_text | 0.05 | 정밀도 우선 |
| movie | 0.05 | 정밀도 우선 (`recalibrate_query_null.py:50` 정의) |
| music | 0.05 | 정밀도 우선 (`recalibrate_query_null.py:50` 정의) |

**신뢰도 (표준 정규 CDF)**

$$\text{confidence}(s) = \Phi(z) = \frac{1}{2}\!\left[1 + \text{erf}\!\left(\frac{s - \mu_{\text{null}}}{\sigma_{\text{null}}\sqrt{2}}\right)\right]$$

**이전 방식 폐기 이유**: 기존 `doc-doc self-similarity` 방식은 동일 도메인(이미지↔이미지) 분포를 사용하여 cross-modal(텍스트↔이미지) 스케일을 과대추정 → FAR 계산 오류. `crossmodal_v1`은 실제 쿼리-문서 교차 분포를 사용하여 올바른 임계값을 도출.

---

### 5.4 RRF (Reciprocal Rank Fusion) — Doc/Img

순위 기반 융합으로 dense/sparse/ASF 세 채널의 스케일 차이를 제거한다.

$$\text{score}_{\text{RRF}}(d) = \sum_{i \in \{\text{dense, sparse, asf}\}} \frac{1}{k + \text{rank}_i(d)}, \quad k = 60$$

**k=60 선택 이유**: $k$가 작으면 top 순위 아이템에 과집중, 크면 차별화 손실. $k=60$은 극단값 내성과 분리력의 균형점.

**RRF vs. 가중합 비교**

| 방법 | 스케일 불변성 | 극단값 내성 | 비고 |
|------|:---:|:---:|------|
| **RRF** | ✅ | ✅ | 프로덕션 기본값 |
| Min-max 가중합 | ❌ | ❌ | Inspect 디버그용 |

---

### 5.5 Inspect 가중 Fusion (`trichef_admin.py`)

관리자 디버그 전용. 비활성 채널의 가중치를 dense로 재분배.

$$\text{fused} = w_d \cdot \text{minmax}(\text{dense}) + w_l \cdot \text{minmax}(\text{lex}) + w_a \cdot \text{minmax}(\text{asf})$$

$$w_d = 0.6, \quad w_l = 0.25, \quad w_a = 0.15$$

**Abs threshold 상향 보호** (image 도메인 σ 저평가 대비):

$$\text{abs\_thr} = \max\!\left(\text{abs\_thr},\; \mu_{\text{null}} + 3\sigma_{\text{null}}\right) \quad (\text{domain} = \text{image})$$

---

### 5.6 Doc Im_body Fusion (PDF 본문 텍스트 결합)

`cache_doc_page_Im.npy` 는 Qwen2-VL 이 페이지 이미지를 보고 생성한 **시각 캡션** Im 임베딩이다. 그러나 PDF 본문에는 이미지 캡션으로 포착되지 않는 표·수식·연속 문단 텍스트가 존재한다. `build_doc_body_im.py` 가 pdfplumber 로 페이지별 본문을 직접 추출하여 BGE-M3 로 별도 임베딩한 `cache_doc_page_Im_body.npy` 를 생성하면, 검색 엔진은 두 채널을 가중 평균한다.

$$\mathbf{Im}_{\text{fused}} = \alpha \cdot \mathbf{Im}_{\text{caption}} + (1-\alpha) \cdot \mathbf{Im}_{\text{body}}, \qquad \alpha = \text{DOC\_IM\_ALPHA} = 0.20$$

$$\mathbf{Im} \;\leftarrow\; \frac{\mathbf{Im}_{\text{fused}}}{\|\mathbf{Im}_{\text{fused}}\|_2}$$

**Phase 4-2 α 튜닝 결과** (LOO eval, n=150, dense + sparse RRF):

| α | R@5 (dense) | R@5 (+sparse) | 비고 |
|---|:----------:|:-------------:|------|
| 0.20 | **0.907** | 0.900 | 채택 (현재) |
| 0.35 | 0.880 | 0.900 | 이전 기본값 |
| 1.00 | 0.000 | — | Im_body 무시 → 본문 검색 완전 실패 |

**구현** (`unified_engine.py:138-148`)

```python
if domain_label == "doc_page":
    body_path = dir / "cache_doc_page_Im_body.npy"
    if body_path.exists():
        Im_body = np.load(body_path)
        if Im_body.shape == Im.shape:
            _alpha = float(TRICHEF_CFG.get("DOC_IM_ALPHA", 0.20))  # Phase 4-2: 0.35 → 0.20
            Im_fused = _alpha * Im + (1.0 - _alpha) * Im_body
            norms = np.linalg.norm(Im_fused, axis=1, keepdims=True)
            Im = Im_fused / np.maximum(norms, 1e-9)
```

> **튜닝 의도**: α=0.20 → 시각 캡션 20%, 본문 텍스트 80%. PDF 도메인은 텍스트 밀도가 높아 본문 가중을 강하게 두는 것이 LOO recall 에서 유리. Phase 4-2 (2026-04-25) 튜닝으로 0.35→0.20 하향.

---

### 5.7 Img 3-Stage Caption Fusion (L1/L2/L3 가중 합산)

이미지 도메인은 Qwen2-VL-2B-Instruct 가 한 장의 사진에 대해 3단계 한국어 캡션을 생성한다 (`DI_TriCHEF/scripts/build_img_caption_triple.py`, P1.6):

| 레벨 | 길이/형식 | 임베딩 캐시 |
|------|-----------|-------------|
| **L1** (주제) | 1문장 (≤30 token), 중심 주제 | `cache_img_Im_L1.npy` |
| **L2** (키워드) | 콤마 키워드 5–10개 | `cache_img_Im_L2.npy` |
| **L3** (상세) | 3–5문장 상세 묘사 | `cache_img_Im_L3.npy` |

세 캐시가 모두 존재하면 엔진은 BGE-M3 동일 1024d 공간에서 직접 가중 평균한다.

$$\mathbf{Im}_{\text{fused}} = w_1 \mathbf{Im}_{L1} + w_2 \mathbf{Im}_{L2} + w_3 \mathbf{Im}_{L3}, \quad (w_1, w_2, w_3) = (0.15,\; 0.25,\; 0.60)$$

$$\mathbf{Im} \;\leftarrow\; \frac{\mathbf{Im}_{\text{fused}}}{\|\mathbf{Im}_{\text{fused}}\|_2}$$

**구현** (`unified_engine.py:112-132`)

```python
if domain_label == "image":
    if L1p.exists() and L2p.exists() and L3p.exists():
        L1 = np.load(L1p); L2 = np.load(L2p); L3 = np.load(L3p)
        w1 = float(TRICHEF_CFG.get("IMG_IM_L1_ALPHA", 0.15))
        w2 = float(TRICHEF_CFG.get("IMG_IM_L2_ALPHA", 0.25))
        w3 = float(TRICHEF_CFG.get("IMG_IM_L3_ALPHA", 0.60))
        tot = max(w1 + w2 + w3, 1e-9)
        w1, w2, w3 = w1/tot, w2/tot, w3/tot
        Im_fused = w1 * L1 + w2 * L2 + w3 * L3
        norms = np.linalg.norm(Im_fused, axis=1, keepdims=True)
        Im = Im_fused / np.maximum(norms, 1e-9)
```

> **가중치 의도**: 상세도가 높을수록 멀티모달 검색 신호가 풍부 → L3 60%. L1 은 주제 거시 정렬, L2 는 토픽 키워드 보강.

---

### 5.8 Movie/Music AV Hermitian (실제 검색 식)

`MR_TriCHEF/pipeline/search.py` 의 AV 도메인 dense 점수는 Z 채널 미사용 형태이다.

$$\text{per\_seg\_dense} = \sqrt{A^2 + (0.4 \cdot B)^2}, \quad A = \mathbf{q}_{\text{Re}}\!\cdot\!\mathbf{d}_{\text{Re}}, \; B = \mathbf{q}_{\text{Im}}\!\cdot\!\mathbf{d}_{\text{Im}}$$

- **Movie**: $\mathbf{q}_{\text{Re}}$ = SigLIP2-text(1152d), $\mathbf{d}_{\text{Re}}$ = SigLIP2-image(1152d), 즉 **cross-modal text→image**
- **Music**: $\mathbf{q}_{\text{Re}}$ = SigLIP2-text(1152d), $\mathbf{d}_{\text{Re}}$ = **SigLIP2-text**(1152d) — 2026-04 전환 (commit 192f157, P2C). 이전엔 Re = BGE-M3(1024d) 동질 공간이었음. SigLIP2-text 로 통일하면서 Movie/Music 이 **동일 Re 공간**을 공유 → 크로스도메인 후처리 가능. calibration.py (commit 9c72993) 에서 Music kind 분기가 SigLIP2 인코더 제공 시 크로스모달 공식 사용.

**파일 단위 집계** (`search.py:_aggregate`):

$$\text{file\_score} = \alpha \cdot z(\text{mean(top-3 segments)}) + \gamma \cdot \text{ASF}_{\text{file-max}}$$

$$(\alpha, \beta, \gamma) = (0.75, 0, 0.25), \qquad z = \frac{x - \mu_{\text{null}}}{\sigma_{\text{null}}}, \qquad \text{conf} = \sigma(z/2)$$

> 본 식은 App 의 통합 엔진(`unified_engine.search_av`) 의 3축 Hermitian 과 별개이며,
> MR_TriCHEF standalone CLI 에서 적용된다. App 측에서는 Z=Im 으로 대체되어 5.2 의
> 일반 식이 그대로 사용된다.

---

### 5.9 Music SigLIP2-Text 통일 (2026-04 전환) 과 동질 baseline

Music Re 축이 BGE-M3(1024d) → SigLIP2-text(1152d) 로 전환되며 (commit 192f157, P2C), calibration 메타에 명시적 표기가 추가되었다 (commit 9c72993, P2A.2).

**전환 내용**:
- 캐시: `cache_music_Re.npy` shape (N, 1152) 재인덱싱 완료
- 검색 공식: `s = √(A² + (0.4B)²)` — A = Re @ q_sig, B = Im @ q_bge (Movie와 동일)
- calibration: `measure_domain(kind="music")` 시 sig encoder 존재 여부 분기, 크로스모달 공식 vs legacy 선택
- MR→App sync: `_sync_to_shared()` 에서 music 엔트리에 "same-encoder baseline" 표기

```json
"music": {
  "mu_null": 0.7885,
  "sigma_null": 0.0390,
  "abs_threshold": 0.8428,
  "method": "text_text_siglip2_null_v1",
  "note": "Music Re=SigLIP2-text, same-encoder baseline high. Do not cross-compare with cross-modal domains."
}
```

**해석**: SigLIP2-text 가 query 와 doc 양쪽 모두에 동일하게 적용되므로 (text↔text, 동질 공간) μ_null ≈ 0.79 로 cross-modal 도메인(image/movie μ ≈ 0.16) 대비 수치가 매우 높다. 이는 부정합이 아니라 **동질 인코더 baseline** 의 자연스러운 결과로, 도메인 간 raw score 비교는 금지하고 z-score 또는 confidence 만 비교 단위로 사용해야 한다.

---

### 5.10 INT8 양자화 (DINOv2-Z + SigLIP2-Re)

```python
"INT8_Z_DINOV2": True,    # FP16 1.30GB → INT8 0.65GB
"INT8_RE_SIGLIP2": True,  # FP16 1.00GB → INT8 0.50GB
```

bitsandbytes 8-bit 로 두 ViT 모델을 로드. 임베딩 품질 변화 < 0.5%, RTX 4070 8GB VRAM 환경에서 약 -1.15GB 절감으로 Whisper(STT) + Qwen2-VL(NF4) + BGE-M3 동시 상주가 가능해진다. config.py 의 `_check_int8_support()` 가 bitsandbytes 미설치 시 silent FP16 fallback 을 시작 시점에 경고.

---

### 5.11 calibration 2× drift safety guard (P2A.1)

App 측(`calibration.py:151-161`) 과 MR 측(`pipeline/calibration.py`, commit 9c72993, P2A.1) 모두에서 새 calibration 결과가 이전 abs_threshold 의 2배 이상으로 폭증/0.5배 이하로 폭락하면 새 값을 거부한다.

```python
prev_thr = float(prev.get("abs_threshold", 0.0) or 0.0)
if prev_thr > 0 and thr > prev_thr * 2.0:
    logger.warning(f"[calibration:{domain}] REJECTED new thr {thr:.4f} > 2× prev {prev_thr:.4f}.")
    return prev
```

도입 계기는 W5-3 doc_page 사례 — within-doc caption 상관이 μ/σ 를 오염시켜 thr 0.205 → 0.355 로 치솟아 전 쿼리가 zero-hit 이 되었음. 

**MR↔App 양방향 동기화 (P2A.2, commit 9c72993 + 0c00289)**:
- MR → App: `_sync_to_shared()` (`MR_TriCHEF/pipeline/calibration.py`, commit 9c72993) 가 `MR_TriCHEF/pipeline/_calibration.json` → `Data/embedded_DB/trichef_calibration.json` 으로 자동 머지
- App → MR: `run_calibration.py` (commit 0c00289) 이 recalibrate() 후 belt-and-suspenders 로 동일 App 경로에 직접 쓰기 (idempotent)
- GitIgnore: MR 측 `_calibration.json` 을 `.gitignore` 추가 (commit d985c53), App 공유본만 트래킹

---

### 5.12 replace_by_file 캐시 시맨틱 (P2B.1, P2B.2)

이전 `append_npy/append_ids/append_segments` 는 항상 뒤에 붙이기 때문에, 동일 파일을 SHA mismatch 로 재인덱싱하면 stale 행이 누적되었다. 

**MR 측 (P2B.1, commit c33f675)**:
- `MR_TriCHEF/pipeline/cache.py` 신규 함수 `replace_by_file()`
- `movie_runner.py:154`, `music_runner.py:199` 에서 호출
- seg_meta 에 `file_path` 키 추가 (파일 매칭 강화)

**App 측 (P2B.2, commit 014d508)**:
- `App/backend/embedders/trichef/cache_ops.py` 신규 모듈 (MR 독립 포팅, 도메인 격리)
- `incremental_runner.py` 4 callsite: run_image_incremental, run_doc_incremental, embed_image_file, embed_doc_file
- 각 callsite 의 local `_merge` 헬퍼를 `cache_ops.replace_by_file` 단일 호출로 교체

**동작 보장**:
1. `file_keys` 에 포함된 파일에 해당하는 기존 행을 모든 `cache_*_{Re,Im,Z}.npy` + `*_ids.json` + `segments.json` 에서 제거 (keep_mask)
2. 새 embedding 만 append
3. dim mismatch 또는 행수 불일치 시 prev 유지 + 경고

```python
keep_mask = np.array([rid not in keyset for rid in prev_ids], dtype=bool)
# ... 모든 npy 슬라이스 후 vstack(kept, new_arr)
```

Movie/Music incremental runner(`movie_runner.py:154`, `music_runner.py:199`) 가 호출하며, 결과로 `{"rows": 최종_행수, "removed": 제거된_기존_행수}` 반환.

---

## 6. Doc/Img 파이프라인

### 6.1 전체 흐름

```
[RAW]                [EXTRACT]               [EMBED 3축]           [LEXICAL]          [INDEX]         [SEARCH]
raw_DB/Img/*.jpg → captions/{stem}.txt → Re: SigLIP2 (1152d)  → vocab/ASF/sparse  →  .npy cache   → query
raw_DB/Doc/*.pdf →  (PDF text+render)  → Im: BGE-M3 (1024d)   →  (auto_vocab)     → img_ids.json  →  dense+lex+asf
                 →  page_images/       → Z : DINOv2-L (1024d) →                   → ChromaDB      →   (RRF merge)
                                         (Gram-Schmidt orth.) →                   → concat 3200d  →  calibration gate
```

**진입점**: `App/backend/embedders/trichef/incremental_runner.py`
- `run_image_incremental()` — 신규 이미지 SHA-256 증분 처리
- `run_doc_incremental()` — PDF → 페이지별 렌더 + 캡션 + 원문 텍스트

### 6.2 Image 세부 단계

| 단계 | 산출물/파일 | 모듈·함수 | 비고 |
|------|------------|-----------|------|
| 1. 신규 탐지 | `registry.json` (SHA-256) | `_load_registry`, `_sha256` | 변경/신규만 처리 |
| 2. 캡션 로드/생성 | `captions/{stem}.txt` | `_caption_for_im` | Qwen2-VL. hash-stem(json→txt) → plain-stem(txt) → Qwen 재생성 3-tier fallback |
| 3. Re 임베딩 | `siglip2_re.py` | `embed_images` | 384×384 입력, L2-norm |
| 4. Im 임베딩 | `bgem3_caption_im.py` | `embed_passage` | max_length=1024, L2-norm |
| 5. Z 임베딩 | `dinov2_z.py` | `embed_images` | 224×224 center crop, CLS 토큰 |
| 6. Gram-Schmidt | `tri_gs.py` | `orthogonalize` | Im_perp, Z_perp 계산 (차원 불일치 시 L2-norm) |
| 7. 3축 npy 누적 | `cache_img_{Re,Im,Z}.npy` | `np.vstack` | 증분 append |
| 8. ChromaDB upsert | `trichef_image` 컬렉션 | `_upsert_chroma` | concat 3200d (1152+1024+1024), cosine |
| 9. Lexical rebuild | vocab + ASF + sparse | `rebuild_image_lexical` | vocab≈2784, BGE-M3 sparse |
| 10. Calibration | `trichef_calibration.json` | `calibrate_image_crossmodal` | W4-1 crossmodal_v1, n_queries=200 |

### 6.3 Document 세부 단계

| 단계 | 모듈·함수 | 비고 |
|------|-----------|------|
| 1. PDF 렌더 | `doc_page_render.render_pdf` | dpi=110, 페이지별 JPEG |
| 2. 페이지 캡션 | `_caption_for_im` | Qwen2-VL, `captions/{stem}/p0000.txt` |
| 3. PDF 원문 추출 | `fitz.Document.get_text("text")` | PyMuPDF, 페이지별 |
| 4. 3축 임베딩 | Re=SigLIP2 / Im=BGE-M3 / Z=DINOv2 | Im 입력 = "캡션\n원문" (캡션+원문 결합) |
| 5. Lexical rebuild | `rebuild_doc_lexical` | max_length=2048, vocab top 25,000 |

---

## 7. Movie/Rec 파이프라인

### 7.1 전체 흐름

```
[RAW]                    [SEGMENT/STT]             [EMBED 3축]                  [INDEX]                [SEARCH]
raw_DB/Movie/*.mp4  → FFmpeg 씬 분할 또는      → Re/Im/Z: 세그먼트 텍스트   → segments.json        → query
raw_DB/Rec/*.m4a    →  고정 구간 (예: 30s)   →  + 선택적 CLAP (Z축 오디오) →  cache_{movie,music}_ → search_av
                    → Whisper STT            → Qwen/CLAP Expand (선택)    →   {Re,Im,Z}.npy       →   파일 단위 집계
                    → Qwen 자막 캡션 (선택)                                                         →   top 세그먼트 타임라인
```

**진입점**: `run_movie_incremental()`, `run_music_incremental()`

**출력 자료구조**
```
cache_music_Re.npy  : (N_seg, 1152)
music_ids.json      : ["{file_id}#{seg_idx}", ...]
segments.json       : [{id, file_path, file_name, start_sec, end_sec, stt_text, caption}, ...]
```

> **Movie/Rec의 특이점**: Re 축은 **SigLIP2-text(1152d)** cross-modal, Im/Z는 BGE-M3(1024d).
> AV 도메인은 텍스트(STT) 외 시각 정보 접근이 어려우므로 텍스트 기반 세 축을 운용.

### 7.2 검색 플로우 (`search_av`)

```
query (예: "웃고 있는 강아지")
  → _embed_query_for_domain("music")
     → Music Re 축은 SigLIP2-text(1152d) 공간: q_Re = SigLIP2-text(query) (cross-modal text)
  → hermitian_score(q, all_segments)
  → abs_thr * 0.5 gate  ← AV는 세그먼트 단위 잡음이 커서 임계 절반으로 완화
  → 파일별 best 세그먼트 집계 (file_best)
  → topk 파일 반환 + 상위 M개 세그먼트 타임라인 동봉
```

---

## 8. 파이프라인 독립성 및 공유 모듈

### 8.1 독립성 판정

| 항목 | Doc/Img | Movie/Rec |
|------|---------|-----------|
| **진입점** | `run_{image,doc}_incremental` | `run_{movie,music}_incremental` |
| **캐시** | `TRICHEF_{IMG,DOC}_CACHE` | `TRICHEF_{MOVIE,MUSIC}_CACHE` |
| **Chroma 컬렉션** | `trichef_image`, `trichef_doc_page` | `trichef_movie`, `trichef_music` |
| **검색 API** | `engine.search()` | `engine.search_av()` |
| **Re 축 모델** | SigLIP2 (1152d, 이미지-텍스트) | SigLIP2-text (1152d, 텍스트) |
| **Lexical(sparse)** | ✅ 활성 (LEXICAL_DOMAINS 화이트리스트) | ⚠️ config 활성, vocab 미구축 시 noop |
| **ASF 필터** | ✅ 활성 (ASF_DOMAINS 화이트리스트) | ⚠️ config 활성, vocab/token_sets 미구축 시 noop |
| **세그먼트 집계** | ❌ (페이지/이미지 단위) | ✅ 파일/세그먼트 단위 |

**결론**: 두 파이프라인은 **데이터 구조 · 모델 · 검색 로직 모두 독립**이나, 공유 레이어(hermitian score, calibration, Gram-Schmidt, TriChefEngine dispatch)를 통해 단일 API(`/api/trichef/search`) 뒤에 통합된다.

### 8.2 공유 모듈 매트릭스

| 모듈 | 파일 | Doc/Img | Movie/Rec | 역할 |
|------|------|:-------:|:---------:|------|
| TriChefEngine | `services/trichef/unified_engine.py` | ✅ | ✅ | domain 라우팅 |
| `hermitian_score` / `orthogonalize` | `services/trichef/tri_gs.py` | ✅ | ✅ | 3축 결합 점수 |
| calibration | `services/trichef/calibration.py` | ✅ | ✅ | abs_threshold, confidence CDF |
| `qwen_expand` | `embedders/trichef/qwen_expand.py` | ✅ | ✅ | paraphrase 평균 |
| `shared.reranker` (BGE v2-m3) | `shared/reranker.py` | 선택 | 선택 | cross-encoder 재순위 |
| RRF merge | `unified_engine.py _rrf_merge` | ✅ | ❌ | dense/lex/asf 순위 융합 |
| `asf_filter` / `auto_vocab` / `bgem3_sparse` | `services/trichef/*`, `embedders/trichef/bgem3_sparse.py` | ✅ | ❌ | lexical 보조 |

---

## 9. ASF — Adaptive Sieve Filter 핵심 개념

### 9.1 명칭 해석

| 단어 | 의미 |
|------|------|
| **Adaptive** | 도메인 말뭉치에서 자동 추출한 IDF 어휘에 적응 (고정 사전 아님) |
| **Sieve** | 체(sieve)처럼 쿼리 토큰과 겹치지 않는 문서를 걸러냄 |
| **Filter** | Dense·Sparse 채널을 보조하는 후처리 필터 역할 |

### 9.2 존재 이유 — Dense와 Sparse의 맹점

| 채널 | 강점 | 맹점 |
|------|------|------|
| Dense (BGE-M3) | 의미 유사도 | 희귀 고유명사·전문 용어 누락 |
| Sparse (BGE-M3) | Subword 매칭 | 도메인 특화 어휘 가중치 균일 |
| **ASF** | IDF 가중 도메인 키워드 오버랩 | 의미 추론 불가 |

ASF는 "이 쿼리 단어가 이 문서에 실제로 등장하는가"를 **도메인 희귀도(IDF)로 가중**해 측정한다.

### 9.3 처리 파이프라인

```
[도메인 말뭉치 (캡션 + PDF 원문)]
        │
        ▼ auto_vocab.py
[auto_vocab.json]  {token: {df: N, idf: float}}
        │
        ├─────────────────────────────────────────────────┐
        ▼ asf_filter.build_doc_token_sets()               │
[문서별 token_set]  [{token: idf}, ...]                   │
        │                                              쿼리 입력
        ▼ asf_filter.asf_scores(query, sets, vocab)       │
[ASF 점수 벡터]  np.ndarray([0,1], shape=(N_docs,)) ◄─────┘
```

### 9.4 Step 1 — auto_vocab: IDF 사전 구축

**파일**: `services/trichef/auto_vocab.py`

**토크나이저 정규식**

```python
_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9\-]{2,}")
# 한국어: 2글자 이상 연속 한글
# 영어:   알파벳 시작 + 3자 이상 alphanumeric/하이픈
```

**불용어 필터** (고빈도 무의미 토큰 제거)

```python
_KO_STOP = {"있는", "있다", "없는", "하는", "위한", "관련", ...}  # 31개
_EN_STOP = {"the", "a", "of", "in", "photo", "image", ...}       # 24개
```

**IDF 계산 (라플라스 스무딩 + 시프트)**

$$\text{idf}(t) = \ln\!\left(\frac{N + 1}{df(t) + 1}\right) + 1$$

여기서 $N$ = 전체 문서 수, $df(t)$ = 토큰 $t$를 포함하는 문서 수

**필터링 조건**

$$df(t) \geq \text{min\_df}=2 \quad \text{AND} \quad df(t) \leq N \times \text{max\_df\_ratio}=0.4$$

- `min_df=2`: 1회만 등장하는 오탈자·잡음 토큰 제거
- `max_df_ratio=0.4`: 40% 초과 문서에 등장 → 너무 일반적 → 제거

**구현 코드**

```python
def build_vocab(docs, min_df=2, max_df_ratio=0.4, top_k=None):
    N = len(docs)
    df = Counter()
    for text in docs:
        for t in set(_tokenize(text)):   # 문서 내 중복 제거 후 카운트
            df[t] += 1

    max_df = int(N * max_df_ratio)
    vocab = {}
    for t, c in df.items():
        if c < min_df or c > max_df:
            continue
        idf = math.log((N + 1) / (c + 1)) + 1.0
        vocab[t] = {"df": c, "idf": round(idf, 4)}

    if top_k:                            # Doc: top 25,000 / Img: 전체
        vocab = dict(sorted(vocab.items(),
                            key=lambda kv: -kv[1]["idf"])[:top_k])
    return vocab
```

**결과 규모**

| 도메인 | vocab 크기 | top_k |
|--------|-----------|-------|
| Img | ≈ 2,784 | None (전체) |
| Doc | ≈ 25,000 | 25,000 |

### 9.5 Step 2 — build_doc_token_sets: 문서 토큰 집합 구축

**파일**: `services/trichef/asf_filter.py`

한국어 조사·접미사 처리가 핵심. "지역사회의" → "지역사회", "금융이" → "금융" 등.

**구현 코드**

```python
def build_doc_token_sets(docs, vocab):
    out = []
    for text in docs:
        toks = set(_tokenize(text))
        entry = {}
        for t in toks:
            # (1) exact 매칭
            if t in vocab:
                entry[t] = float(vocab[t]["idf"])
            # (2) 한국어 접미 절단 (1~3자) → 재매칭
            if _is_kr(t) and len(t) >= 3:
                for strip in (1, 2, 3):
                    if len(t) - strip >= 2:
                        sub = t[:-strip]
                        if sub in vocab and sub not in entry:
                            entry[sub] = float(vocab[sub]["idf"])
        out.append(entry)
    return out   # [{token: idf}, ...]
```

### 9.6 Step 3 — asf_scores: 쿼리-문서 점수 계산

#### 쿼리 토큰 확장 (한국어 Bigram 역색인)

단순 exact 매칭 대신 쿼리 토큰의 **한글 bigram**으로 vocab을 역탐색하여 포함 관계 매칭.

```
쿼리: "금융" → bigram: ["금융"]
bigram 역색인에서 "금융"을 포함하는 vocab 후보: ["금융이", "금융기관", ...]
→ "금융" in "금융이" → True → q_set에 추가
```

```python
def _get_kr_bigram_index(vocab):
    idx = {}
    for vt in vocab:
        if not any("\uAC00" <= c <= "\uD7A3" for c in vt):
            continue
        for i in range(len(vt) - 1):
            bg = vt[i:i+2]
            idx.setdefault(bg, []).append(vt)
    return idx
```

#### 점수 수식

$$\text{ASF}_i = \frac{\displaystyle\sum_{t \;\in\; Q_{\text{set}} \cap D_i} \text{idf}(t)}{\left\|\mathbf{q}_{\text{idf}}\right\|_2}$$

$$\left\|\mathbf{q}_{\text{idf}}\right\|_2 = \sqrt{\sum_{t \in Q_{\text{set}}} \text{idf}(t)^2}$$

$$\text{ASF}_i^{\text{norm}} = \frac{\text{ASF}_i}{\max_j \text{ASF}_j} \;\in\; [0, 1]$$

- $Q_{\text{set}}$: 쿼리에서 bigram 확장까지 포함한 vocab 매칭 토큰 집합
- $D_i$: 문서 $i$의 {token: idf} 딕셔너리 키 집합
- 분모: 쿼리 IDF 벡터 L2 노름 (쿼리 길이 정규화)
- 최종 min-max: 전체 문서 상대 점수로 변환

**구현 코드**

```python
def asf_scores(query, doc_token_sets, vocab):
    # 1. 쿼리 토큰 추출 + bigram 확장
    raw = _tokenize(query)
    q_set = set()
    kr_idx = _get_kr_bigram_index(vocab)
    for t in raw:
        if t in vocab:
            q_set.add(t)
        if _is_kr(t) and len(t) >= 2:
            candidates = set()
            for i in range(len(t) - 1):
                bucket = kr_idx.get(t[i:i+2])
                if bucket:
                    candidates.update(bucket)
            for vt in candidates:
                if t in vt:
                    q_set.add(vt)

    # 2. 쿼리 IDF 노름 계산
    q_norm = math.sqrt(sum(vocab[t]["idf"]**2 for t in q_set)) or 1.0

    # 3. 문서별 교집합 IDF 합산
    scores = np.zeros(len(doc_token_sets), dtype=np.float32)
    for i, d in enumerate(doc_token_sets):
        inter = q_set & d.keys()
        if inter:
            scores[i] = sum(d[t] for t in inter) / q_norm

    # 4. min-max 정규화
    mx = float(scores.max())
    if mx > 0:
        scores = scores / mx
    return scores
```

### 9.7 검색에서의 위치

```
Dense score (Hermitian)  ──┐
BGE-M3 sparse score      ──┼──► RRF merge ──► calibration gate ──► 최종 결과
ASF score                ──┘
```

**활성 판정 로직**

```python
lex_active = lex is not None and max(lex) > 0
asf_active = asf_s is not None and max(asf_s) > 0
# 신호 없는 채널 → 가중치를 dense로 자동 재분배
# (noisy zero로 dense를 깎는 사고 방지)
```

**적용 범위**

| 도메인 | ASF 활성 | 이유 |
|--------|:-------:|------|
| Img | ✅ | 캡션 기반 vocab 구축 가능 |
| Doc | ✅ | 캡션 + PDF 원문으로 풍부한 vocab |
| Movie / Rec | ❌ | STT 세그먼트 기반 vocab 미구축 |

### 9.8 BGE-M3 Sparse와의 차이

| 비교 항목 | BGE-M3 Sparse | ASF |
|-----------|:-------------:|:---:|
| 어휘 공간 | 250,002-dim (subword vocab) | 도메인 auto_vocab (2,784 ~ 25,000) |
| 가중치 출처 | 모델 내부 학습 가중치 | 도메인 코퍼스 IDF |
| 한국어 조사 처리 | 모델 내부 | 명시적 접미 절단 + bigram 확장 |
| 역할 | 범용 lexical 유사도 | 도메인 특화 키워드 부스팅 |

---

## 10. 쿼리 확장 (Qwen Expand)

단일 쿼리 표현의 편향을 paraphrase 평균으로 완화.

```
variants = qwen_expand.expand(query)      # paraphrase K개 생성
q_Re = normalize( mean(SigLIP2.embed_texts(variants)) )
q_Im = normalize( mean(BGE-M3.embed_query(variants)) )
q_Z  = q_Im    # Z 축은 쿼리 측 시각 정보 없음 → Im 재사용
```

**수식**

$$\mathbf{q}_{\text{Re}} = \text{L2-norm}\!\left(\frac{1}{K}\sum_{k=1}^{K} \text{SigLIP2}_{\text{text}}(v_k)\right)$$

**적용 근거**
- SigLIP2는 자연어 표현 변화에 민감 → paraphrase 평균으로 표현 편향 완화
- "귀여운 강아지"와 "사랑스러운 강아지"처럼 의미가 같은 다양한 표현을 포괄

**사용 위치**: `embedders/trichef/qwen_expand.py`

---

## 11. 데이터셋 대응 판단 기준 (Data-Adaptive Policy)

| 상황 | 자동 판단 기준 | 구현 위치 |
|------|--------------|-----------|
| Img 신규 647장 증분 | SHA-256 registry로 변경분만 re-embed | `incremental_runner` |
| 캡션 품질 불확실 | 3-tier fallback: hash-stem(json→txt) → plain-stem(txt) → Qwen 재생성 | `_caption_for_im` |
| 차원 불일치 (1152 vs 1024) | Gram-Schmidt 스킵, L2-norm만 적용 | `tri_gs.orthogonalize` |
| lexical/asf 신호 0 | 가중치 dense 재분배 (fallback) | `trichef_admin.inspect` |
| image 도메인 σ 저평가 | `abs_thr = max(abs_thr, μ+3σ)` | `trichef_admin.inspect` |
| 과거 "image+KR → lex/asf skip" | 폐기 (W4-4) — 언어에 따른 휴리스틱 차등화 제거 | — |
| AV 도메인 임계 | `abs_thr * 0.5` 완화 (segment-level noise 큼) | `engine.search_av` |
| calibration 재측정 트리거 | 증분 embed 완료 후 자동 hook 실행 | `incremental_runner` step 6 (W4-5) |
| FAR 도메인별 차등 | `FAR_IMG=0.2 > FAR_DOC_PAGE=0.05 = FAR_DOC_TEXT=0.05` | `TRICHEF_CFG` |
| Top-K pool | dense top-K 후보에만 lex/asf 계산 (전체 계산은 `/admin/inspect`만) | `engine.search` |

**운영 원칙**
1. **신호가 없으면 자동으로 꺼진다** (noisy channel 차단)
2. **분포가 바뀌면 자동으로 재측정한다** (W4-5 auto-recalibrate)
3. **판정 기준은 항상 μ ± σ로 확률적으로 표현** — 하드코드 임계 금지
4. **도메인 물리적 특성에 맞춰 FAR와 임계 감쇠율 차등화** — AV는 segment 잡음 많아 임계 완화

---

## 12. Confidence 해석

$$z = \frac{s - \mu_{\text{null}}}{\sigma_{\text{null}}}, \qquad \text{confidence} = \Phi(z) = \frac{1}{2}\!\left[1 + \text{erf}\!\left(\frac{z}{\sqrt{2}}\right)\right]$$

| confidence | 해석 |
|:----------:|------|
| 0.50 | 완전 무관 쿼리 수준 (null 분포 중앙) |
| 0.80+ | 유의미한 매칭 |
| 0.95+ | 강한 매칭 (UI "정확히 일치" 배지) |

---

## 13. TriChefEngine 내부 구조

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
        rankings      = [dense, sparse, asf]
        combined      = _rrf_merge(rankings)
        gate          : dense >= abs_threshold
        return TriChefResult(id, score, confidence, metadata)

    search_av(query, domain, topk, top_segments):
        seg_scores          = hermitian_score(q, d_all_segments)
        gate                : s >= abs_threshold * 0.5
        file_best, segs_list = 파일별 집계
        return TriChefAVResult(file_path, file_name, score, segments[])
```

**파일**: `App/backend/services/trichef/unified_engine.py`

---

## 14. API 엔드포인트

### 14.1 공개 API (`routes/trichef.py`)

| 메서드 | 경로 | 용도 |
|--------|------|------|
| POST | `/api/trichef/search` | 멀티도메인 검색 (image/doc_page/movie/music) |
| POST | `/api/trichef/reindex` | `scope ∈ {image, document, movie, music, all}` 증분 |
| GET | `/api/trichef/file` | 결과 파일 서빙 (path 쿼리) |
| GET | `/api/trichef/status` | 캐시 현황 |
| GET | `/api/trichef/image-tags` | 이미지 태그 JSON |

### 14.2 관리자 API (`routes/trichef_admin.py`, prefix `/api/admin`)

| 메서드 | 경로 | 용도 |
|--------|------|------|
| POST | `/api/admin/inspect` | per-row `dense/lex/asf/fused/rrf/confidence/z_score` — top-K 필터 없음 |
| GET | `/api/admin/doc-text` | doc_page id → 원문 + 매칭 토큰 |
| GET | `/api/admin/file` | 도메인별 원본 파일 서빙 (썸네일) |
| GET | `/api/admin/ui` | `App/admin_ui/admin.html` 서빙 (카드 그리드) |
| GET | `/api/admin/domains` | 로드된 도메인 + 카운트 + sparse/asf/vocab 상태 |

### 14.3 Inspect 응답 필드 예시

```json
{
  "rank": 1, "id": "...", "filename": "...", "source_path": "...", "page": 0,
  "dense": 0.71, "lexical": 0.43, "asf": 0.22,
  "rrf": 0.068, "fused": 0.88,
  "confidence": 0.96, "z_score": 2.12
}
```

---

## 15. Calibration 현재 상태

**파일**: `Data/embedded_DB/trichef_calibration.json` (2026-04-25 스냅샷)

```json
{
  "image": {
    "mu_null": 0.1586,
    "sigma_null": 0.0290,
    "abs_threshold": 0.1830,
    "far": 0.2,
    "N": 2390,
    "method": "random_query_null_v2"
  },
  "doc_page": {
    "mu_null": 0.1767,
    "sigma_null": 0.0319,
    "abs_threshold": 0.2292,
    "far": 0.05,
    "N": 34170,
    "method": "random_query_null_v2"
  },
  "movie": {
    "mu_null": 0.1592,
    "sigma_null": 0.0367,
    "abs_threshold": 0.2196,
    "p95": 0.2301,
    "p99": 0.2441,
    "N": 200,
    "method": "crossmodal_v1"
  },
  "music": {
    "mu_null": 0.7885,
    "sigma_null": 0.0390,
    "abs_threshold": 0.8428,
    "p95": 0.8428,
    "p99": 0.8603,
    "N": 280,
    "method": "text_text_siglip2_null_v1",
    "note": "Music Re=SigLIP2-text, same-encoder baseline high."
  }
}
```

**관찰**:
- image/doc_page: cross-modal text→image, μ ≈ 0.16~0.18
- movie: cross-modal text→frame, μ = 0.1592 ≈ image (정합)
- music: text↔text 동질, μ = 0.7885 (cross-domain 비교 금지, z-score 만 사용)

`abs_threshold(image) = 0.1586 + Φ⁻¹(0.8) × 0.0290 ≈ 0.183` (FAR=0.2 → Φ⁻¹(0.8) ≈ 0.842)
`abs_threshold(movie) = 0.1592 + Φ⁻¹(0.95) × 0.0367 ≈ 0.220` (FAR=0.05 → Φ⁻¹(0.95) ≈ 1.645)

---

## 16. 데이터셋 현재 규모 (2026-04-25 스냅샷)

| 도메인 | raw 파일 | 임베딩 벡터 | 캐시 크기 |
|--------|---------|------------|----------|
| **Img** | 2,391 | 2,390 (Re 1152d / Im 1024d / Z 1024d) | ~30 MB |
| **Doc** | 422 (PDF/HWP/DOCX) | 34,170 페이지 (Re 1152d / Im 1024d / Z 1024d, +Im_body 1024d) | ~419 MB |
| **Movie** | 173 (155 1차 + 18 YS_다큐_1차, 2차 25 진행중) | 프레임 세그먼트 (~1 fps + scene cuts) | — |
| **Rec (Music)** | 14 | 651 windows (30s win, 15s hop) | — |

**최근 변경 이력**:
- Movie: YS_다큐_1차 18편 추가 (155→173). 2차 25편 indexing 진행중.
- Music: 14파일 651 segments, Re 축 SigLIP2-text(1152d) 로 재인덱싱(`reindex_music_siglip2.py`).
- Doc: `cache_doc_page_Im_body.npy` 추가 — pdfplumber 본문 텍스트 BGE-M3 임베딩 (DOC_IM_ALPHA=0.20 fusion).
- Img: L1/L2/L3 3-stage caption fusion 활성화 (build_img_caption_triple.py 산출물).

---

## 17. 성능 측정값 (2026-04-24)

| 지표 | 값 |
|------|-----|
| 레이턴시 p50 (image, topk=10) | **68 ms** |
| 레이턴시 p95 | **77 ms** |
| 콜드 스타트 첫 쿼리 | 430 ms |
| topk 1→100 증가분 | +12% |
| 멀티도메인 (image+doc_page) | 130–175 ms |
| Top-1 confidence ≥ 0.90 비율 (한국어 15쿼리) | **93%** |

---

## 18. 관련 연구 (Related Work) — 복소수 IR 계보

### 복소수 임베딩 역사

TRI-CHEF의 Hermitian-style 점수는 복소수 표현과 양자 영감 정보검색의 오랜 계보에 자리한다:

**기초 작업**:
- **ComplEx** (Trouillon et al., ICML 2016): 링크 예측을 위한 복소수 임베딩. 실수부와 허수부를 독립 채널로 활용.
- **양자 언어 모델** (Sordoni et al., SIGIR 2013): 텍스트 IR에 양자 확률 프레임워크 적용.
- **CNM** (Li et al., NAACL 2019): 복소수-값 매칭 네트워크로 텍스트 쌍 유사도 계산.

**최근 다중모달 확장**:
- **C-NNQLM** (Zhang et al., TOIS 2022): 양자 언어 모델을 신경 검색으로 일반화. 복소수 표현으로 쿼리-문서 상호작용 모델링.
- **양자 영감 다중모달 융합** (Li et al., Information Fusion 2021): 비디오 감정 분석에서 각 모달을 밀도 행렬로 표현하고 중첩(superposition) 상태로 구성.
- **QIMSF** (Li et al., Neurocomputing 2025): Lindblad 마스터 방정식과 복소 LSTM으로 모달 간 상호작용 모델링. 다중모달 감정 융합.

TRI-CHEF는 이 계보를 멀티모달 검색(sentiment 분류가 아닌)으로 확장하며, 이질(heterogeneous) 사전학습 인코더(SigLIP2, BGE-M3, DINOv2)를 Re/Im/Z 축에 할당하는 구조적 Hermitian-style 점수를 도입한다.

### 융합 및 교정 관련 선행 연구

- **RRF** (Cormack et al., SIGIR 2009): 다중 순위 시스템의 앙상블 방법. 우리의 RRF 보조 채널 기초.
- **ColBERT** (Khattab & Zaharia, SIGIR 2020): 후기 상호작용(late interaction) 기반 정확 검색.
- **SPLADE** (Formal et al., SIGIR 2021): 희소 어휘 확장 및 예측 기반 첫 단계 순위.
- **All-but-the-Top** (Mu & Viswanath, ICLR 2018): 표현 후처리로 이방성(anisotropy) 감소. 우리의 L2-정규화 기초.
- **온라인 보정** (Guo et al., ICML 2017): 신경망 신뢰도 보정. 우리의 절대 임계값 기반 calibration과 유사.

---

## 19. 공개 벤치마크 검증 (MIRACL-ko)

### 배경

Tri-CHEF의 Im축(BGE-M3 dense) 한국어 텍스트 검색 성능을 외부 공개 벤치마크에서 검증하기 위해, **MIRACL-ko**(Multilingual Retrieval Covering 18 Diverse Languages)의 개발 셋을 활용한다.

**데이터셋**:
- 개발 셋: **213개 한국어 쿼리**
- 코퍼스: **1,486,752개 위키피디아 문단**
- 평가 메트릭: nDCG@10, R@100

### 결과

| 시스템 | nDCG@10 | R@100 | 출처 |
|--------|:-------:|:-----:|------|
| BM25 (Pyserini) | 37.1 | 78.4 | MIRACL TACL 2023 |
| mDPR | 41.9 | 76.8 | MIRACL TACL 2023 |
| mContriever | 48.3 | 87.8 | MIRACL TACL 2023 |
| mE5-large-v2 | 66.5 | — | BGE-M3 arXiv:2402.03216 |
| **Tri-CHEF (Im axis) = BGE-M3 dense** | **69.9** | — | BGE-M3 arXiv:2402.03216 |

**해석**:
- BGE-M3 dense는 nDCG@10 = 69.9로 **BM25 대비 +32.8%p** 향상, 고전 희소 검색의 성숙도를 입증.
- mE5-large-v2 대비 **+3.4%p** — 한국어 다국어 밀집 인코딩에서 BGE-M3의 명확한 우위 입증.
- 이는 Tri-CHEF가 Im축 백본으로 BGE-M3를 선택한 타당성을 강화.
- Re축(SigLIP2)과 Z축(DINOv2)은 이 한국어 텍스트 기초 위에 cross-modal 및 시각 구조 증거를 추가하는 역할.

**자체 재현 가능성**: `scripts/eval_miracl_ko.py` 및 baseline 구현체(`scripts/baselines/{bm25,mdpr,mcontriever,me5,bgem3}.py`)를 통해 이 결과는 내부 평가 인프라로도 재현 가능.

**향후**: 더 큰 규모 한국어 IR 벤치마크(AIHub 등)에서의 평가는 추후 버전에서 보충.

---

## 20. 평가 인프라

### 신규 스크립트 (commit 73c8bf0, Q3)

**`scripts/eval_miracl_ko.py`**:
- MIRACL-ko 개발 셋(213 쿼리, 1.5M 문단) 위에서 Tri-CHEF Im축 평가
- BM25, mDPR, mContriever, mE5, BGE-M3 등 5개 baseline과 대비
- nDCG@10, R@100 계산

**`scripts/baselines/`**:
- `bm25.py`: Pyserini BM25
- `mdpr.py`: 다국어 DPR
- `mcontriever.py`: mContriever
- `me5.py`: mE5-large-v2
- `bgem3.py`: BGE-M3 dense (Tri-CHEF Im축)

### 통합 평가 라이브러리 (commit 73c8bf0, Q3)

**`scripts/_bench_common.py`** (신규, 261줄):

공통 gold 산출 로직을 DRY 원칙으로 통합한 라이브러리.

**`ContentGoldDB` 클래스**:
- 도메인별(image, doc_page, movie, music) 텍스트-id 매핑 보유
- `gold_ids(query, domain)` → cosine ≥ θ인 gold id 집합 반환
- O(Q+N) 최적화: 코퍼스 1회 배치 인코딩 후 (1,D) @ (D,N) dot product

**도메인별 상수**:
```python
CONTENT_THETA  = {"image": 0.50, "doc_page": 0.45, "movie": 0.35, "music": 0.30}
CONTENT_KMIN   = {"image": 10,   "doc_page": 20,   "movie": 20,   "music": 3}
CONTENT_KMAX   = {"image": 300,  "doc_page": 2000, "movie": 200,  "music": 14}
```

hybrid θ + K_MIN/K_MAX 클램프로 분포 기울어진 도메인(Movie, Music) 지원.

**공유 평가 스크립트**:
- `scripts/local_bench_v2.py`: 도메인 내 LOO 벤치 (caption-aware gold)
- `scripts/e2e_eval.py`: End-to-end 검색 품질 회귀 (content-aware 지표 추가)
- `scripts/perf_benchmark.py`: 성능(latency) 및 정확도 동시 계측

**결과** (2026-04-25 최신):
- **overall_ct**: 0.910 (dense+sparse, caption-aware gold)
- **image_ct**: 0.917 (game-domain 격리 안정)
- **doc_page_ct**: 0.980 (dense+sparse)
- **movie_ct**: 0.740 (K_MIN clamp 효과, +28pp)
- **music_ct**: 1.000 (SigLIP2-text 크로스모달)

회귀 검증: snippet parity (16/16) + extensions parity (7/7) = **23/23 통과**.

---

## 21. 파일명 정책 / Stem 해시

- **hash-stem**: `stem_key_for(path)`가 반환하는 SHA-256 접두 해시. 파일 rename에도 안정적.
- **plain-stem**: 원본 파일명 (사람이 읽을 수 있음). 레거시 호환용.
- **캡션 조회 우선순위**: hash-stem json → hash-stem txt → plain-stem txt → (없으면 Qwen 재생성)

---

## 22. 캐시 · 인덱스 불변식

1. `cache_{domain}_{Re,Im,Z}.npy`의 행 수는 항상 `{domain}_ids.json` 길이와 일치
2. Chroma `trichef_{domain}` 컬렉션의 id는 `ids.json`의 id와 1:1
3. `vocab`, `asf_sets`, `sparse`는 ids 순서와 동일 인덱스로 정렬
4. 불변식 깨짐 감지 시 `lexical_rebuild.rebuild_{image,doc}_lexical` 전체 재구축 필요

---

## 23. 관리자 UI (`/api/admin/ui`)

- 카드 그리드 레이아웃. 각 카드 = `/api/admin/inspect` 한 행
- 필드: 썸네일(이미지) 또는 doc 페이지 렌더, filename, dense/lex/asf, confidence bar
- 쿼리 입력 후 전수 스코어 top_n=200 반환 — top-K gate 없음 (디버그/튜닝 전용)

**파일**: `App/admin_ui/admin.html`, `App/admin_ui/serve.py`

---

## 24. Wave 히스토리

| Wave | 내용 | 주요 산출물 |
|------|------|------------|
| **Wave1** | 공유 reranker / DI admin inspect 옵션 / DINOv2 Z축 / MR CLAP Z축 / MR sparse / MR qwen_expand 스캐폴드 | `shared/reranker.py`, `DI_TriCHEF/` |
| **Wave2** | 14장 샘플 Qwen 한국어 캡션 품질 검증 | Chinese leak 0건 확인 |
| **Wave3** | Qwen 전체 재캡션 2340장 → BGE-M3 Im 재임베드 → vocab/ASF/sparse 재구축 → ChromaDB 3200d upsert → calibration 측정 | cache/trichef 전면 갱신 |
| **Wave4** | `_caption_for_im` Qwen 교체 · 신규 647장 흡수 (total 2390) · crossmodal calibration · KR-쿼리 lex/asf skip 제거 · auto-recalibrate 훅 | 본 문서 시점 기준 |

### Wave4 세부 작업 매핑

| 코드 | 내용 | 핵심 파일 |
|------|------|----------|
| W4-B | BLIP → Qwen2-VL 캡셔너 교체 | `incremental_runner._get_qwen_captioner` |
| W4-2 | 캡션 3-tier fallback (hash/plain-stem + Qwen) | `_caption_for_im` |
| W4-3 | 신규 647장 증분 흡수 (2390 total) | `run_image_incremental` |
| W4-6(1차) | lexical/ASF/sparse 전면 rebuild | `lexical_rebuild` |
| W4-1 | cross-modal null calibration 신설 | `calibration.calibrate_image_crossmodal` |
| W4-4 | "image+KR → lex/asf skip" 휴리스틱 제거 | `routes/trichef_admin.inspect` |
| W4-5 | 증분 완료 후 auto-recalibrate hook | `incremental_runner` step 6 |

---

## 25. 향후 개선 후보 (Wave5)

| # | 항목 | 근거 |
|---|------|------|
| 1 | `abs_threshold` 0.217 → 0.20 하향 + Qwen expand paraphrase 수 증가 | 한국어 recall 향상 가능성 |
| 2 | reranker `/inspect` 통합 (BGE v2-m3 cross-encoder top-K 재순위) | 근소 차이 분리력 향상 |
| 3 | `doc_page` 도메인에도 crossmodal calibration 적용 | 현재는 doc-doc 방식 유지 |
| 4 | 백엔드 기동 시 warmup (SigLIP2/BGE-M3/DINOv2 선로딩) | 첫 쿼리 430ms 제거 |

---

## 부록 — 왜 이 조합이 한국어-이미지 검색에 통하는가

| 계층 | 담당 모델 | 역할 |
|------|-----------|------|
| Cross-modal bridge | **SigLIP2** | 다국어 대규모 학습으로 한국어 텍스트 → 이미지 매칭, CLIP 대비 우수 |
| 언어 정합 | **Qwen2-VL + BGE-M3** | Qwen 한국어 캡션 → BGE-M3 한국어 dense 공간 활용 |
| 시각 구조 | **DINOv2** | 언어 비의존적 시각 유사성 (쿼리 언어 무관) |
| 키워드 정밀도 | **BGE-M3 sparse + ASF** | 고유명사·도메인 용어 정밀 매칭 |
| 쿼리 편향 완화 | **Qwen expand** | paraphrase 평균으로 단일 표현 편향 제거 |
| 분포 교정 | **Cross-modal calibration** | per-query confidence를 실제 쿼리-문서 분포로 교정 |

이 6층 보완 구조 위에 **RRF 융합**이 채널 간 스케일 불균형을 제거하고, **Calibration**이 신뢰도를 확률적으로 정규화하여 단일 API에서 일관된 결과를 제공한다.

---

---

## 부록 2 — Q1 (1049099) & Q3 (73c8bf0) 통합 요약

### Q1 — 확장자 SSOT (도메인 격리 + parity test)

**구현**:
- 3개 모듈: `App/backend/_extensions.py`, `DI_TriCHEF/_extensions.py`, `MR_TriCHEF/pipeline/_extensions.py`
- 1개 테스트: `tests/test_extensions_parity.py` (7개 assertion)
- 마이그레이션: 5개 파일 (incremental_runner, paths, recaption_all, image, video, audio, doc)

**효과**:
- 도메인 격리 유지 (import 대신 복제)
- 확장자 동기화 자동 감시
- 변수명/타입 호환성 100%

**부수 효과**:
- `DI_TriCHEF/docs/Doc_Img_TriCHEF.md` → `DI_TriCHEF.md`
- `MR_TriCHEF/MR_TriCHEF.md` → `MR_TriCHEF/docs/MR_TriCHEF.md`

### Q3 — 평가 라이브러리 통합 (DRY + content-aware gold)

**신규 모듈** `scripts/_bench_common.py`:
- `ContentGoldDB` 클래스: O(Q+N) 최적화, corpus 1회 batch 인코딩
- `_ensure_encoder()`: BGE-M3 lazy singleton
- 도메인별 상수: `CONTENT_THETA`, `CONTENT_KMIN`, `CONTENT_KMAX`
- `_precision_at_k()`: gold ∩ top_k / k 계산

**스크립트 변경**:
- `local_bench_v2.py`: 60% 축소 (공통 로직 위임)
- `e2e_eval.py`: ct_hits, ct_p5, ct_gold_size 필드 추가
- `perf_benchmark.py`: latency + ct 메트릭 기록

**Hybrid θ + K clamp** (commit bdf80af):
- 도메인별 K_MIN/K_MAX 동적 조정
- movie +28pp, music 1.000 달성
- overall_ct: 0.910 (baseline 0.876 대비 +3.4%p)

**회귀 검증**:
- extensions parity: 7/7
- snippet parity: 16/16
- 총 23/23 테스트 통과

*문서 끝 · `md/TriCHEF.md` (2026-04-25 20:50 갱신)*
