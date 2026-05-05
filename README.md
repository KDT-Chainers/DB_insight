# KDT Project (2026)
- Team : Chainers
- Korea IT Academy (KDT, Ministry of Employment and Labor)
- Independent Researchers, Republic of Korea

---

# DB_insight

> 로컬 파일을 **내용**으로 찾는 AI 데스크탑 검색 앱

---

## 1. 타이틀 & 소개

### 1-1. 이 프로젝트의 목적

**DB_insight**는 PC에 저장된 문서·이미지·영상·음성·음악 파일을 **자연어 의미 검색**으로 찾아주는 로컬 AI 데스크탑 앱입니다.

파일을 저장할 당시 이름이나 위치를 정확히 기억하지 못해도, 파일 *내용*에 대한 설명만으로 원하는 파일을 찾을 수 있도록 하는 것이 목표입니다.

---

### 1-2. 기존 시스템의 한계 — 파일 탐색기 검색

| 한계                | 설명                                                             |
| ------------------- | ---------------------------------------------------------------- |
| **파일명 의존**     | "계약서*최종*진짜최종.docx" 같은 이름을 정확히 알아야 검색 가능  |
| **내용 검색 불가**  | 문서 내부 텍스트만 일부 지원, 이미지·영상·음악은 전혀 검색 안 됨 |
| **의미 이해 없음**  | "작년 여름 워크샵 발표자료" 같은 문장으로 검색 불가              |
| **멀티미디어 한계** | 영상·오디오는 파일 이름이나 메타데이터로만 구분 가능             |
| **비정형 파일**     | 스캔 PDF, 이미지 속 텍스트는 완전히 사각지대                     |

---

### 1-3. 우리 시스템의 장점과 기대 효과

| 장점                       | 설명                                                                                                           |
| -------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **5개 도메인 통합 검색**   | 문서(Doc) / 이미지(Img) / 영상(Movie) / 녹음(Rec) / 음악(BGM) 을 하나의 검색창에서                             |
| **의미 기반 검색**         | "파란 하늘 사진", "회의에서 예산 얘기 나온 영상" 같은 자연어로 검색                                            |
| **Tri-CHEF 멀티모달 퓨전** | SigLIP2(시각) + BGE-M3(텍스트) + DINOv2(구조)를 복소 공간에서 결합, 어느 한 모델이 점수를 독점하지 않도록 설계 |
| **완전 로컬 동작**         | 인터넷 연결 불필요. 파일이 외부 서버로 전송되지 않음                                                           |
| **Obsidian AI 모드**       | 파일 내용을 기반으로 로컬 LLM(Ollama)과 대화하며 질문·요약·분석 가능                                           |
| **단일 EXE 배포**          | 설치 없이 포터블 exe 하나로 실행                                                                               |

**기대 효과:**

- 파일 정리를 안 해도 → 내용으로 찾을 수 있음
- 회의록·계약서·발표자료를 메모 없이 → 기억나는 내용만으로 검색
- 대용량 로컬 파일 아카이브를 → AI와 대화하며 탐색

---

### 1-4. 쉬운 설명

```
"작년 3분기 매출 보고서 어디 있더라?"
"파란 하늘 나온 사진 있었는데..."
"회의 녹음에서 예산 얘기 나온 부분 찾아줘"
```

위처럼 **기억나는 내용만 입력하면**, DB_insight가 PC에 저장된 파일 중 가장 관련 있는 것들을 찾아줍니다.

파일 이름? 몰라도 됩니다. 저장 위치? 몰라도 됩니다.

---

## 2. 기능 설명

### 2-1. 임베딩 (파일 인덱싱)

**임베딩**이란 파일의 내용을 AI가 이해할 수 있는 숫자 벡터로 변환하는 과정입니다. 한 번만 인덱싱하면 이후 검색은 즉시 처리됩니다.

#### 도메인별 임베딩 방식

| 도메인    | 파일 형식                | 처리 방식                                                  |
| --------- | ------------------------ | ---------------------------------------------------------- |
| **Doc**   | PDF, DOCX, TXT, HWP 등   | 텍스트 청크 분할 → BGE-M3 임베딩 + 스파스 인덱스           |
| **Img**   | JPG, PNG, WEBP 등        | SigLIP2 비주얼 임베딩 + BLIP/Qwen 캡션 생성 → BGE-M3       |
| **Movie** | MP4, MKV, AVI 등         | 장면 분할 프레임 → SigLIP2 + Whisper STT → BGE-M3          |
| **Rec**   | MP3, WAV, M4A 등 (음성)  | Whisper STT → BGE-M3 텍스트 임베딩                         |
| **BGM**   | MP3, FLAC, WAV 등 (음악) | Chromaprint 핑거프린트 + CLAP 오디오 임베딩 + librosa 특징 |

#### Tri-CHEF 퓨전

세 인코더(SigLIP2 · BGE-M3 · DINOv2)를 **복소(Complex) 임베딩**의 직교 축에 배정하고, 에르미트(Hermitian) 절대값으로 결합합니다. 이를 통해 어느 한 인코더가 결과를 독점하는 문제를 방지합니다.

```
Query ──► SigLIP2 (시각축)  ─┐
      ──► BGE-M3  (언어축)  ─┼─► Complex Hermitian Fusion ──► 유사도 점수
      ──► DINOv2  (구조축)  ─┘
```

---

### 2-2. 메인 검색창

`/search` 페이지에서 자연어 쿼리를 입력하면 5개 도메인을 동시에 검색합니다.

**주요 기능:**

- **도메인 필터**: Doc / Img / Movie / Rec / BGM 선택 검색
- **점수 상세 보기**: 시각·언어·구조 축별 기여도 확인 (`ScoreBreakdown`)
- **위치 정보**: 파일 경로 및 저장 위치 표시
- **파일 미리보기**: 이미지 썸네일, 문서 청크 텍스트, 영상 구간 정보
- **검색 기록**: 최근 검색어 자동 저장
- **음성 입력**: 마이크로 말하면 검색어 자동 입력 (Web Speech API)

---

### 2-3. AIMODE — Obsidian AI

`/ai` 페이지. 로컬 LLM(Ollama)과 대화하듯 파일을 탐색·분석합니다.

**동작 흐름 (LangGraph 파이프라인):**

```
사용자 질문
    │
    ▼
① Intent 분석     — 질문 의도 파악, 파일명 키워드 / 내용 키워드 추출
    │
    ▼
② Candidate 검색  — ChromaDB에서 관련 파일 후보 Top-K 추출
    │
    ▼
③ 파일 스캔       — 각 파일 내용을 실제로 읽어 키워드 매칭 확인
    │
    ▼
④ 소스 선택       — 실제로 관련 있는 파일만 필터링
    │
    ▼
⑤ 답변 생성       — 파일 전체 내용을 컨텍스트로 Ollama LLM 스트리밍 응답
```

**주요 특징:**

- **멀티턴 대화**: 이전 대화 내용을 기억하며 추가 질문 가능 (LangGraph MemorySaver + thread_id)
- **실시간 스트리밍**: 답변이 토큰 단위로 실시간 출력
- **파일 카드**: 우측 패널에 후보 파일과 스캔 상태를 카드 형태로 표시
- **출처 표시**: 답변에 사용된 파일 명시 (`[출처1]`, `[출처2]` 형식)
- **완전 로컬**: Ollama 기반, 인터넷 불필요

---

## 3. 빌드 방법

### 3-1. 사전 조건

| 항목        | 버전        | 비고                                      |
| ----------- | ----------- | ----------------------------------------- |
| **Node.js** | 18+         | https://nodejs.org                        |
| **Python**  | 3.10+       | PATH 등록 필수                            |
| **Git**     | 최신        | https://git-scm.com                       |
| **Ollama**  | 최신        | https://ollama.com — AI 모드 사용 시 필요 |
| **CUDA**    | 12.4 (선택) | GPU 가속 (RTX 30/40 권장)                 |

**Ollama 모델 설치 (AI 모드 사용 시):**

```bash
ollama pull gemma3:7b
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

---

### 3-2. 앱 빌드 방법

> **빌드 전 DB_insight 앱이 실행 중이라면 반드시 먼저 종료하세요.**  
> 앱이 켜진 채로 빌드하면 `out/` 폴더가 잠겨 실패합니다.

```bash
git clone <repo-url>
cd DB_insight/App/frontend

npm install
npm run dist
```

빌드 결과물: `App/frontend/out/DB_insight 0.1.0.exe`

#### 빌드 오류 대처

| 오류                                              | 원인                                  | 해결                                                               |
| ------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------ |
| `EBUSY: resource busy or locked`                  | 앱 실행 중 / Windows Defender 스캔 중 | 앱 종료 후 재시도. 반복 시 `out/` 폴더를 Defender 제외 목록에 추가 |
| `클라이언트가 필요한 권한을 가지고 있지 않습니다` | Windows 개발자 모드 비활성화          | 설정 → 개인 정보 및 보안 → 개발자용 → **개발자 모드 ON** 후 재시도 |

---

### 3-3. 앱 실행 방법

`App/frontend/out/DB_insight 0.1.0.exe` 더블클릭

- Flask 백엔드 자동 시작 (포트 5001)
- React UI 자동 로드
- **별도 터미널 실행 불필요**

**개발 모드 실행 (소스 수정 시):**

```bash
# 터미널 1 — Flask 백엔드
cd App/backend
python app.py
# → http://127.0.0.1:5001

# 터미널 2 — React + Electron
cd App/frontend
npm run electron:dev
```

---

## 4. 파일 구조

```
DB_insight/
├── App/
│   ├── frontend/                  ← React + Vite + Electron 앱
│   │   ├── electron/
│   │   │   ├── main.cjs           ← Electron 메인 프로세스 (백엔드 자동 실행 포함)
│   │   │   └── preload.cjs        ← contextBridge API 노출 (zoom, 폴더 선택 등)
│   │   ├── src/
│   │   │   ├── pages/
│   │   │   │   ├── LandingLogin.jsx     ← 로그인 화면
│   │   │   │   ├── InitialSetup.jsx     ← 최초 비밀번호 설정
│   │   │   │   ├── MainSearch.jsx       ← 메인 검색 페이지
│   │   │   │   ├── MainAI.jsx           ← AI 모드 (Obsidian AI)
│   │   │   │   ├── DataIndexing.jsx     ← 파일 인덱싱 관리
│   │   │   │   ├── Settings.jsx         ← 설정 페이지
│   │   │   │   └── TriChefSearch.jsx    ← Tri-CHEF 전용 검색
│   │   │   ├── components/
│   │   │   │   ├── AnimatedOrb.jsx      ← WebGL 파티클 오브 (Three.js)
│   │   │   │   ├── SearchSidebar.jsx    ← 좌측 네비게이션 사이드바
│   │   │   │   ├── PageSidebar.jsx      ← 페이지별 보조 사이드바
│   │   │   │   └── search/
│   │   │   │       ├── DomainFilter.jsx     ← 도메인 필터 UI
│   │   │   │       ├── ScoreBreakdown.jsx   ← 점수 상세 표시
│   │   │   │       └── LocationBadge.jsx    ← 파일 위치 표시
│   │   │   ├── hooks/
│   │   │   │   ├── useSpeechRecognition.js  ← 음성 입력 훅
│   │   │   │   └── useMicLevelRef.js        ← 마이크 레벨 측정 훅
│   │   │   ├── context/
│   │   │   │   ├── SidebarContext.jsx    ← 사이드바 열림 상태 전역 관리
│   │   │   │   └── ScaleContext.jsx      ← UI 스케일(줌) 전역 관리
│   │   │   └── api.js                   ← API_BASE URL 설정
│   │   ├── package.json
│   │   └── out/                   ← 빌드 결과물 (DB_insight 0.1.0.exe)
│   │
│   └── backend/                   ← Flask 백엔드 (Python)
│       ├── app.py                 ← Flask 앱 진입점, 라우트 등록
│       ├── config.py              ← 포트·경로·모델 설정
│       ├── routes/
│       │   ├── search.py          ← GET /api/search (자연어 검색)
│       │   ├── aimode.py          ← POST /api/aimode/chat (LangGraph AI 모드)
│       │   ├── index.py           ← POST /api/index/scan, start, stop
│       │   ├── files.py           ← GET /api/files/indexed, detail, open
│       │   ├── auth.py            ← POST /api/auth/setup, verify, reset
│       │   ├── history.py         ← GET/DELETE /api/history
│       │   ├── trichef.py         ← Tri-CHEF 검색 API
│       │   ├── bgm.py             ← BGM 도메인 검색 API
│       │   └── registry.py        ← 파일 레지스트리 관리
│       ├── embedders/
│       │   ├── doc.py             ← 문서 임베딩 (PDF, DOCX 등)
│       │   ├── image.py           ← 이미지 임베딩
│       │   ├── video.py           ← 영상 임베딩 + STT
│       │   ├── audio.py           ← 음성 임베딩 + STT
│       │   └── trichef/           ← Tri-CHEF 멀티모달 임베딩 모듈
│       │       ├── siglip2_re.py      ← SigLIP2 시각 인코더
│       │       ├── bgem3_sparse.py    ← BGE-M3 언어 인코더 + 스파스
│       │       ├── dinov2_z.py        ← DINOv2 구조 인코더
│       │       ├── doc_ingest.py      ← 문서 청크 분할 및 인제스트
│       │       └── incremental_runner.py ← 증분 인덱싱 실행기
│       ├── services/
│       │   ├── trichef/
│       │   │   ├── unified_engine.py  ← Tri-CHEF 통합 검색 엔진
│       │   │   ├── calibration.py     ← 도메인별 임계값 캘리브레이션
│       │   │   └── asf_filter.py      ← 적응형 유사도 필터
│       │   ├── bgm/
│       │   │   ├── search_engine.py   ← BGM 하이브리드 검색
│       │   │   ├── clap_encoder.py    ← CLAP 오디오 임베딩
│       │   │   ├── chromaprint.py     ← 음악 핑거프린트
│       │   │   └── nlp_query.py       ← BGM 자연어 쿼리 처리
│       │   ├── query_expand.py        ← 쿼리 확장 (동의어·한영 변환)
│       │   └── job_control.py         ← 임베딩 작업 큐 관리
│       ├── db/
│       │   ├── init_db.py         ← SQLite 스키마 초기화
│       │   └── vector_store.py    ← ChromaDB 인터페이스
│       └── requirements.txt       ← Python 패키지 목록
│
└── Data/
    ├── extracted_DB/              ← 텍스트 캐시 (STT, OCR, 캡션)
    └── embedded_DB/               ← 벡터 캐시 (.npy) + ChromaDB + 캘리브레이션
```

---

## 5. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                     DB_insight Desktop App                      │
│                                                                 │
│  ┌─────────────────────┐      ┌──────────────────────────────┐ │
│  │   Electron (Node)   │      │     Flask Backend (Python)   │ │
│  │                     │ HTTP │                              │ │
│  │  React + Vite UI    │◄────►│  /api/search                 │ │
│  │  ├─ MainSearch      │      │  /api/aimode/chat  (SSE)     │ │
│  │  ├─ MainAI          │      │  /api/index/*                │ │
│  │  ├─ DataIndexing    │      │  /api/files/*                │ │
│  │  └─ Settings        │      │  /api/auth/*                 │ │
│  │                     │      │                              │ │
│  │  Three.js AnimatedOrb      │  ┌────────────────────────┐ │ │
│  │  Web Speech API     │      │  │   Tri-CHEF Engine      │ │ │
│  └─────────────────────┘      │  │  SigLIP2 + BGE-M3      │ │ │
│                               │  │  + DINOv2 → Hermitian  │ │ │
│                               │  └────────────────────────┘ │ │
│                               │                              │ │
│                               │  ┌────────────────────────┐ │ │
│                               │  │   LangGraph AI Mode    │ │ │
│                               │  │  Intent → Search →     │ │ │
│                               │  │  Scan → Select →       │ │ │
│                               │  │  Generate (Ollama)     │ │ │
│                               │  └────────────────────────┘ │ │
│                               │                              │ │
│                               │  ┌────────────────────────┐ │ │
│                               │  │   BGM Engine           │ │ │
│                               │  │  Chromaprint + CLAP    │ │ │
│                               │  │  + librosa             │ │ │
│                               │  └────────────────────────┘ │ │
│                               │                              │ │
│                               │  SQLite ◄─► ChromaDB        │ │
│                               └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘

로컬 파일 시스템 (인터넷 연결 불필요)
```

**데이터 흐름:**

```
파일 추가
  │
  ▼
[임베딩 파이프라인]
  ├─ Doc  → 텍스트 청크 → BGE-M3 → ChromaDB
  ├─ Img  → SigLIP2 + BLIP 캡션 → ChromaDB
  ├─ Movie→ 장면 프레임 + Whisper STT → ChromaDB
  ├─ Rec  → Whisper STT → BGE-M3 → ChromaDB
  └─ BGM  → Chromaprint + CLAP → BGM Index
       │
       ▼
  [검색 시]
  자연어 쿼리 → 쿼리 확장 → Tri-CHEF 유사도 계산
              → 캘리브레이션 필터링 → 결과 반환
```

---

---

## © 저작권

본 저장소에 포함된 코드 및 모든 출력·이미지 결과물은 저작권법에 의해 보호됩니다.  
저작권자(Team Chainers)의 명시적 허가 없이 본 자료의 전부 또는 일부를 복제, 배포, 수정, 상업적으로 이용하는 행위를 금합니다.

**© 2026. All rights reserved.**

Please contact team leader, e-mail : sjowun@gmail.com.

| 역할            | 이름                     | 연락처                                      |
| --------------- | ------------------------ | ------------------------------------------- |
| **Team Leader** | 송영상 (Young-Sang SONG) | Project Manager                              |
| Team Member     | 이훤 (Hwon LEE)          | Technical Master                            |
| Team Member     | 장주연 (Ju Yeon JANG)    | Technical Support & Security                |
| Team Member     | 황영진 (Young Jin HWANG) | Technical Support                           |
| Team Member     | 이태윤 (Tae Yoon LEE)    | Technical Support                           |
| Team Member     | 김정혜 (Jeong Hye GIM)   | Technical Support                           |
