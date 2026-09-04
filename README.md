# KDT Project (2026)

- Team : Chainers
- Korea IT Academy (KDT, Ministry of Employment and Labor)
- Independent Researchers, Republic of Korea

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20034370.svg)](https://doi.org/10.5281/zenodo.20034370)
[![License: CC BY 4.0](https://img.shields.io/badge/Paper%20License-CC%20BY%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)
[![Preprint: Zenodo](https://img.shields.io/badge/Preprint-Zenodo-blue.svg)](https://zenodo.org/records/20046344)
[![ORCID](https://img.shields.io/badge/ORCID-0009--0001--4636--9896-A6CE39.svg?logo=orcid&logoColor=white)](https://orcid.org/0009-0001-4636-9896)

---

## Publication / 논문

본 프로젝트의 핵심 알고리즘은 다음 논문으로 공개되어 있다 (Zenodo, CC BY 4.0).

- 제목 : **Tri-CHEF: Complex-Hermitian Embedding Fusion for Korean Multimodal Retrieval**
- 저자 : Young-Sang Song\*, Hwon Lee, Ju Yeon Jang, Young Jin Hwang, Tae Yoon Lee, Jeong Hye Gim.
- 소속 : Team Chainers, Korea IT Academy (KDT, Ministry of Employment and Labor), Independent Researchers.
- 저널 : Zenodo, May 2026. https://doi.org/10.5281/zenodo.20034370

| 항목                                        | 값                                                                   |
| ------------------------------------------- | -------------------------------------------------------------------- |
| **Concept DOI** (인용 권장, 항상 최신 버전) | [`10.5281/zenodo.20034370`](https://doi.org/10.5281/zenodo.20034370) |
| **Latest Record URL**                       | https://zenodo.org/records/20046344                                  |
| **현재 라이선스**                           | CC BY 4.0 (논문)                                                     |

### Versions

| 항목            | **v1.1** (latest)                                                    | v1.0                                                                 |
| --------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------- |
| **Version DOI** | [`10.5281/zenodo.20046344`](https://doi.org/10.5281/zenodo.20046344) | [`10.5281/zenodo.20034371`](https://doi.org/10.5281/zenodo.20034371) |
| **Record URL**  | https://zenodo.org/records/20046344                                  | https://zenodo.org/records/20034371                                  |
| **PDF (영문)**  | `Tri-CHEF_paper_v1.1.pdf` (12 pp)                                    | `Tri-CHEF_paper.pdf` (12 pp)                                         |
| **PDF (국문)**  | `Tri-CHEF_paper_Korean_v1.1.pdf` (13 pp)                             | `Tri-CHEF_paper_Korean.pdf` (13 pp)                                  |
| **게재일**      | 2026-05-06                                                           | 2026-05-06                                                           |
| **비고**        | 모든 페이지 푸터에 DOI/라이선스 표시                                 | 최초 게재                                                            |

> 본문 콘텐츠와 그림/표 레이아웃, 페이지 분할은 v1.0 = v1.1 바이트 단위로 동일하다 (v1.1은 v1.0 PDF에 페이지 푸터만 오버레이).

### Citation (BibTeX)

```bibtex
@misc{trichef2026,
  title         = {Tri-CHEF: Complex-Hermitian Embedding Fusion for Korean Multimodal Retrieval},
  author        = {Song, Young-Sang and Lee, Hwon and Jang, Ju Yeon and Hwang, Young Jin and Lee, Tae Yoon and Gim, Jeong Hye},
  year          = {2026},
  month         = may,
  publisher     = {Zenodo},
  version       = {1.1},
  doi           = {10.5281/zenodo.20034370},
  url           = {https://zenodo.org/records/20046344},
  note          = {Preprint, CC BY 4.0. Concept DOI resolves to the latest version.}
}
```

### Citation (APA)

> Song, Y.-S., Lee, H., Jang, J. Y., Hwang, Y. J., Lee, T. Y., & Gim, J. H. (2026). _Tri-CHEF: Complex-Hermitian Embedding Fusion for Korean Multimodal Retrieval_ (Version 1.1) [Preprint]. Zenodo. https://doi.org/10.5281/zenodo.20034370

> 인용 권장: 위 BibTeX/APA 모두 **Concept DOI** (`10.5281/zenodo.20034370`)를 사용한다. 이 DOI는 항상 최신 버전으로 자동 리졸브되므로 향후 추가 게재 시에도 별도 수정이 필요 없다. 특정 버전을 고정할 경우에만 Version DOI를 사용하라.

GitHub은 저장소 루트의 `CITATION.cff`를 자동 인식하여 우측 상단에 **"Cite this repository"** 버튼을 표시한다.

---

# DB_insight

> 로컬 파일을 내용으로 검색하는 멀티모달 AI 데스크탑 검색 시스템

---

## 1. 프로젝트 개요

DB_insight는 PC에 저장된 문서·이미지·동영상·음원·배경음을 **자연어 의미 검색**으로 탐색하고, 로컬 LLM을 통해 파일 내용을 요약·분석하는 멀티모달 정보 검색 시스템이다. 파일명이나 저장 경로를 알지 못하더라도 파일 내용에 관한 자연어 설명만으로 원하는 파일을 검색할 수 있으며, 모든 처리는 외부 서버 전송 없이 로컬에서 수행된다.

### 1-1. 기존 파일 탐색기의 한계

| 한계               | 설명                                                              |
| ------------------ | ----------------------------------------------------------------- |
| **파일명 의존**    | 정확한 파일명을 알아야 검색 가능                                  |
| **내용 검색 불가** | 문서 내부 텍스트 일부만 지원; 이미지·동영상·음악은 내용 검색 불가 |
| **의미 이해 없음** | 자연어 의미 기반 검색 불가                                        |
| **비정형 파일**    | 스캔 PDF 및 이미지 내 텍스트 검색 불가                            |

### 1-2. 본 시스템의 특징

| 특징                       | 설명                                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------- |
| **5개 도메인 통합 검색**   | 문서(Doc) / 이미지(Img) / 동영상(Mov) / 음원(Rec) / 배경음(BGM)을 단일 검색창에서 처리 |
| **자연어 의미 검색**       | 파일명·경로 불필요; 내용에 관한 자연어 설명만으로 검색                                 |
| **TRI-CHEF 멀티모달 퓨전** | SigLIP2·BGE-M3·DINOv2를 복소 허미션 공간에서 결합하여 단일 모델의 실패 모드 방지       |
| **완전 로컬 동작**         | 인터넷 연결 불필요; 파일이 외부 서버로 전송되지 않음                                   |
| **AI 요약**                | 검색 결과 파일을 로컬 LLM(Ollama)으로 요약·분석                                        |
| **단일 EXE 배포**          | 설치 없이 포터블 실행 파일 하나로 동작                                                 |

---

## 2. 지원 도메인 및 임베딩 파이프라인

각 도메인은 파일 유형에 따라 전용 파이프라인을 통해 전처리·임베딩·인덱싱된다.

| 도메인           | 지원 포맷                                      | 텍스트 추출 방식                                                  | 임베딩 채널                                                                       |
| ---------------- | ---------------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **Doc** (문서)   | PDF, DOCX, PPTX, XLSX, TXT, HTML               | pdfplumber / LibreOffice / BeautifulSoup / PyMuPDF (OCR)          | SigLIP2 Re + BGE-M3 Im (캡션 20% + 본문 80%) + BGE-M3 Sparse                      |
| **Img** (이미지) | JPG, PNG, WebP, HEIC                           | Qwen2-VL-2B 5단계 캡셔닝 (title/tagline/synopsis/tags_kr/tags_en) | SigLIP2 Re (이미지) + BGE-M3 Im (L1×0.15 + L2×0.25 + L3×0.60) + DINOv2 Z (이미지) |
| **Mov** (동영상) | MP4, MOV, AVI, MKV, WebM                       | 0.5fps 프레임 추출 + Whisper large-v3 STT                         | SigLIP2 Re (프레임) + BGE-M3 Im (STT) + DINOv2 Z (프레임)                         |
| **Rec** (음원)   | MP3, M4A, WAV, FLAC, OGG                       | 30초 슬라이딩 윈도우 + Whisper large-v3 STT                       | SigLIP2 Re (STT 텍스트) + BGE-M3 Im (STT); Z = 0벡터                              |
| **BGM** (배경음) | 위 Rec과 동일 포맷 (RMS 기반 음성 미검출 분기) | 파일명 (STT 미적용)                                               | 파일명 임베딩; 검색 품질 낮음                                                     |

인덱싱 결과는 `.npy` / `.npz` 벡터 캐시와 ChromaDB 메타데이터에 저장되며, 파일 추가·삭제 시 해당 항목만 원자적으로 갱신된다.

---

## 3. TRI-CHEF 알고리즘

**TRI-CHEF (Triple-Channel Complex-Hermitian Embedding Fusion)**은 본 시스템의 핵심 검색 알고리즘으로, Zenodo 프리프린트로 공개되어 있다 (상단 Publication 참조).

### 3-1. 3축 구조

세 개의 독립적인 임베딩 모델을 복소 벡터 공간의 세 축에 배정한다.

| 축              | 모델           | 차원  | 역할                          | 학습 방식                  |
| --------------- | -------------- | ----- | ----------------------------- | -------------------------- |
| **Re** (실수축) | SigLIP2-SO400M | 1152d | 이미지↔텍스트 크로스모달 정렬 | Sigmoid Loss 대조 학습     |
| **Im** (허수축) | BGE-M3 dense   | 1024d | 한국어·영어 다국어 시맨틱     | 다국어 대조 학습           |
| **Z** (직교축)  | DINOv2-Large   | 1024d | 언어 독립적 시각 구조         | 자기 지도 학습 (iBOT+DINO) |

단일 모델 방식의 실패 모드(시각 구조 무시, 언어 편향, 채널 간 중복 신호 증폭)를 방지하기 위해, 세 채널을 L2 정규화 후 허미션 내적으로 결합한다.

### 3-2. 허미션 스코어

```
s(q, d) = sqrt( A^2 + (alpha * B)^2 + (beta * C)^2 )

A = Re_q · Re_d    (SigLIP2 크로스모달 코사인 유사도)
B = Im_q · Im_d    (BGE-M3 시맨틱 코사인 유사도)
C = Z_q  · Z_d     (DINOv2 시각 구조 코사인 유사도)
```

도메인별 Im 감쇠 계수 (alpha) 기본값:

| 도메인       | alpha | 설계 근거                  |
| ------------ | ----- | -------------------------- |
| 이미지 (Img) | 0.45  | 시각(Re)과 시맨틱(Im) 균형 |
| 동영상 (Mov) | 0.40  | 시각 채널(Re) 우선         |
| 음원 (Rec)   | 0.60  | STT 텍스트 의존도 높음     |
| 문서 (Doc)   | 0.80  | 텍스트 전용 도메인         |

### 3-3. 검색 파이프라인

```
① 쿼리 확장       — 동의어 파라프레이즈 x3 + 한영 번역
② 다변형 임베딩   — Re / Im 평균 정규화
③ 허미션 스코어   — Dense 채널 유사도 계산
④ Sparse 채널     — BGE-M3 서브워드 어휘 가중치 (250,002-dim CSR 행렬)
⑤ ASF             — IDF 가중 어휘 정밀 매칭 부스트
⑥ RRF             — Dense + Sparse + ASF 채널 순위 융합 (k = 60)
⑦ 캘리브레이션    — Null 분포 기반 절대 임계값 필터링
⑧ 신뢰도 산출     — confidence = Phi((score - mu_null) / sigma_null)
```

---

## 4. AI 요약 모드

`/ai` 페이지에서 로컬 LLM(Ollama)과 대화하듯 파일을 탐색·요약·분석할 수 있다.

**처리 흐름 (LangGraph 파이프라인):**

```
① Intent 분석    — 질문 의도 파악, 파일명·내용 키워드 추출
② 후보 검색      — ChromaDB에서 관련 파일 후보 Top-K 추출
③ 파일 스캔      — 각 파일 내용 직접 읽기 + 키워드 매칭 확인
④ 소스 선택      — 관련 파일만 필터링
⑤ 답변 생성      — 파일 내용을 컨텍스트로 Ollama LLM 스트리밍 응답
```

| 항목            | 내용                                                 |
| --------------- | ---------------------------------------------------- |
| **요약 LLM**    | gemma3:4b (우선), qwen2.5:3b (폴백)                  |
| **멀티턴 대화** | LangGraph MemorySaver + thread_id 기반 컨텍스트 유지 |
| **출력 방식**   | SSE (Server-Sent Events) 토큰 단위 스트리밍          |
| **동작 환경**   | 완전 로컬 (인터넷 불필요)                            |

---

## 5. 시스템 아키텍처

```
+---------------------------------------------------------------+
|                    DB_insight Desktop App                     |
|                                                               |
|  +---------------------+      +----------------------------+  |
|  |   Electron (Node)   |      |   Flask Backend (Python)   |  |
|  |                     | HTTP |                            |  |
|  |  React + Vite UI    |<---->|  /api/search               |  |
|  |  |- MainSearch      |      |  /api/aimode/chat  (SSE)   |  |
|  |  |- MainAI          |      |  /api/index/*              |  |
|  |  |- DataIndexing    |      |  /api/files/*              |  |
|  |  +- Settings        |      |  /api/auth/*               |  |
|  |                     |      |                            |  |
|  |  Three.js AnimatedOrb      |  +----------------------+  |  |
|  |  Web Speech API     |      |  |   TRI-CHEF Engine    |  |  |
|  +---------------------+      |  |  SigLIP2 + BGE-M3    |  |  |
|                               |  |  + DINOv2 (Hermitian)|  |  |
|                               |  +----------------------+  |  |
|                               |                            |  |
|                               |  +----------------------+  |  |
|                               |  |  LangGraph AI Mode   |  |  |
|                               |  |  Intent > Search >   |  |  |
|                               |  |  Scan > Generate     |  |  |
|                               |  |  (Ollama)            |  |  |
|                               |  +----------------------+  |  |
|                               |                            |  |
|                               |  SQLite <-> ChromaDB       |  |
|                               +----------------------------+  |
+---------------------------------------------------------------+
              로컬 파일 시스템 (인터넷 연결 불필요)
```

### 기술 스택

| 레이어              | 기술                                |
| ------------------- | ----------------------------------- |
| **프론트엔드**      | React, Vite, Electron, Tailwind CSS |
| **백엔드**          | Flask, Python 3.12                  |
| **임베딩**          | PyTorch, HuggingFace Transformers   |
| **벡터 저장**       | .npy / .npz 파일 캐시 + ChromaDB    |
| **이미지 캡셔닝**   | Qwen2-VL-2B-Instruct                |
| **음성 인식 (STT)** | OpenAI Whisper large-v3             |
| **요약 LLM**        | Ollama (gemma3:4b / qwen2.5:3b)     |
| **문서 파싱**       | pdfplumber, PyMuPDF, LibreOffice    |
| **오디오 분석**     | librosa, FFmpeg                     |

---

## 6. 빌드 방법

### 6-1. 사전 조건

| 항목        | 버전        | 비고                                      |
| ----------- | ----------- | ----------------------------------------- |
| **Node.js** | 18+         | https://nodejs.org                        |
| **Python**  | 3.12        | PATH 등록 필수                            |
| **Git**     | 최신        | https://git-scm.com                       |
| **Ollama**  | 최신        | https://ollama.com — AI 요약 사용 시 필요 |
| **CUDA**    | 12.4 (선택) | GPU 가속 (RTX 30/40 계열 권장)            |

**Ollama 모델 설치 (AI 요약 사용 시):**

```bash
ollama pull gemma3:4b
```

**Python 패키지 설치:**

```bash
# GPU (NVIDIA CUDA 12.4)
pip install torch==2.6.0+cu124 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# CPU only
pip install torch torchvision torchaudio

# 나머지 패키지
pip install -r App/backend/requirements.txt
```

### 6-2. 앱 빌드

> **빌드 전 DB_insight 앱이 실행 중이라면 반드시 종료할 것.** 앱이 켜진 채로 빌드하면 `out/` 폴더가 잠겨 빌드가 실패한다.

```bash
git clone <repo-url>
cd DB_insight/App/frontend
npm install
npm run dist
```

빌드 결과물: `App/frontend/out/DB_insight 0.1.0.exe`

| 오류                                              | 원인                                  | 해결                                                               |
| ------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------ |
| `EBUSY: resource busy or locked`                  | 앱 실행 중 / Windows Defender 스캔 중 | 앱 종료 후 재시도; 반복 시 `out/` 폴더를 Defender 제외 목록에 추가 |
| `클라이언트가 필요한 권한을 가지고 있지 않습니다` | Windows 개발자 모드 비활성화          | 설정 → 개인 정보 및 보안 → 개발자용 → 개발자 모드 ON               |

### 6-3. 앱 실행

`App/frontend/out/DB_insight 0.1.0.exe` 더블클릭

- Flask 백엔드 자동 시작 (포트 5001)
- React UI 자동 로드
- 별도 터미널 실행 불필요

**개발 모드 실행 (소스 수정 시):**

```bash
# 터미널 1 — Flask 백엔드
cd App/backend
python app.py
# -> http://127.0.0.1:5001

# 터미널 2 — React + Electron
cd App/frontend
npm run electron:dev
```

---

## 7. 파일 구조

```
DB_insight/
+-- App/
|   +-- frontend/                  <- React + Vite + Electron 앱
|   |   +-- electron/
|   |   |   +-- main.cjs           <- Electron 메인 프로세스 (백엔드 자동 실행 포함)
|   |   |   +-- preload.cjs        <- contextBridge API 노출
|   |   +-- src/
|   |   |   +-- pages/
|   |   |   |   +-- LandingLogin.jsx     <- 로그인 화면
|   |   |   |   +-- InitialSetup.jsx     <- 최초 비밀번호 설정
|   |   |   |   +-- MainSearch.jsx       <- 메인 검색 페이지
|   |   |   |   +-- MainAI.jsx           <- AI 요약 모드
|   |   |   |   +-- DataIndexing.jsx     <- 파일 인덱싱 관리
|   |   |   |   +-- Settings.jsx         <- 설정 페이지
|   |   |   +-- components/
|   |   |   |   +-- AnimatedOrb.jsx      <- WebGL 파티클 오브 (Three.js)
|   |   |   |   +-- search/
|   |   |   |       +-- DomainFilter.jsx     <- 도메인 필터 UI
|   |   |   |       +-- ScoreBreakdown.jsx   <- 채널별 점수 상세 표시
|   |   |   |       +-- LocationBadge.jsx    <- 파일 위치 표시
|   |   +-- out/                   <- 빌드 결과물 (DB_insight 0.1.0.exe)
|   |
|   +-- backend/                   <- Flask 백엔드 (Python 3.12)
|       +-- app.py                 <- Flask 앱 진입점
|       +-- config.py              <- 포트·경로·모델·TRI-CHEF 파라미터
|       +-- routes/
|       |   +-- search.py          <- GET /api/search
|       |   +-- aimode.py          <- POST /api/aimode/chat (LangGraph, SSE)
|       |   +-- index.py           <- POST /api/index/scan, start, stop
|       |   +-- files.py           <- GET /api/files/indexed, detail, open
|       |   +-- auth.py            <- POST /api/auth/setup, verify, reset
|       +-- embedders/
|       |   +-- trichef/
|       |       +-- siglip2_re.py          <- SigLIP2 Re축 (1152d)
|       |       +-- bgem3_caption_im.py    <- BGE-M3 Im축 (1024d)
|       |       +-- bgem3_sparse.py        <- BGE-M3 Sparse (250K-dim CSR)
|       |       +-- dinov2_z.py            <- DINOv2 Z축 (1024d)
|       |       +-- incremental_runner.py  <- 이미지 캡셔닝 + 증분 인덱싱
|       |       +-- av_embed.py            <- 동영상·음원 임베딩
|       |       +-- doc_ingest.py          <- 문서 청킹 + 임베딩
|       +-- services/
|       |   +-- trichef/
|       |       +-- unified_engine.py  <- TRI-CHEF 통합 검색 엔진
|       |       +-- calibration.py     <- Null 분포 기반 임계값 캘리브레이션
|       |       +-- tri_gs.py          <- 허미션 스코어 + 채널 정규화
|       |       +-- asf_filter.py      <- ASF 적응형 체 필터
|       +-- requirements.txt
|
+-- Data/
    +-- extracted_DB/              <- 텍스트 캐시 (STT 전사, OCR, 캡션)
    +-- embedded_DB/               <- 벡터 캐시 (.npy/.npz) + ChromaDB + 캘리브레이션
```

---

## 저작권 / Copyright

본 저장소에 포함된 코드 및 모든 출력·이미지 결과물은 저작권법에 의해 보호된다.
저작권자(Team Chainers)의 명시적 허가 없이 본 자료의 전부 또는 일부를 복제, 배포, 수정, 상업적으로 이용하는 행위를 금한다.

**© 2026. All rights reserved.**

Please contact team leader, e-mail : sjowun@gmail.com.

| 역할            | 이름                     | 담당                         |
| --------------- | ------------------------ | ---------------------------- |
| **Team Leader** | 송영상 (Young-Sang SONG) | Project Manager              |
| Team Member     | 이훤 (Hwon LEE)          | Technical Master             |
| Team Member     | 장주연 (Ju Yeon JANG)    | Technical Support & Security |
| Team Member     | 황영진 (Young Jin HWANG) | Technical Support            |
| Team Member     | 이태윤 (Tae Yoon LEE)    | Technical Support            |
| Team Member     | 김정혜 (Jeong Hye GIM)   | Technical Support            |
