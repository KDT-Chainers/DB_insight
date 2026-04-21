## 1. 프로젝트 개요

본 프로젝트는 사용자의 로컬 컴퓨터에 존재하는 문서, 이미지, 영상, 음성 파일을 자연어로 검색할 수 있도록 지원하는 AI 기반 로컬 파일 탐색 서비스이다.

사용자는 검색 대상이 될 로컬 경로를 지정할 수 있으며, 시스템은 해당 경로 내 파일들을 분석하여 텍스트를 추출하고, 이를 임베딩하여 벡터 데이터베이스에 저장한다. 이후 사용자가 자연어로 검색어를 입력하면, 시스템은 의미 기반 검색을 통해 관련 파일을 찾아 미리보기와 상세 정보를 제공한다.

본 프로젝트는 AI 협업 개발을 위해 다음의 3계층 구조를 채택한다.

- 1계층: 헌법 (Constitution) → 모든 작업의 공통 규칙
- 2계층: Agents → 역할별 전문 코딩 에이전트
- 3계층: Knowledge → 에이전트 간 충돌을 방지하는 최소 스펙

---

## 2. 전체 디렉토리 구조

```
DB_insight
├─ constitution.md
│
├─ App
│  ├─ frontend
│  │  ├─ electron/
│  │  │  ├─ main.cjs       ← Electron main (Flask 자동 실행, IPC)
│  │  │  └─ preload.cjs    ← contextBridge
│  │  ├─ src/
│  │  │  ├─ pages/
│  │  │  │  ├─ Login.jsx
│  │  │  │  ├─ Setup.jsx
│  │  │  │  ├─ MainSearch.jsx    ← 검색 메인 (파일 상세 포함)
│  │  │  │  ├─ DataIndexing.jsx  ← 데이터 관리 (3탭)
│  │  │  │  ├─ AIMode.jsx
│  │  │  │  └─ Settings.jsx
│  │  │  ├─ App.jsx
│  │  │  └─ main.jsx
│  │  └─ package.json
│  │
│  └─ backend
│     ├─ app.py             ← Flask 앱 생성 및 Blueprint 등록
│     ├─ config.py          ← 경로 상수 (EXTRACTED_DB_VIDEO, EMBEDDED_DB_VIDEO 등)
│     ├─ routes/
│     │  ├─ auth.py         ← /api/auth/*
│     │  ├─ history.py      ← /api/history/*
│     │  ├─ search.py       ← /api/search, /api/files/open, /api/files/open-folder
│     │  ├─ index.py        ← /api/index/scan|start|stop|status
│     │  └─ files.py        ← /api/files/indexed|stats|detail
│     ├─ embedders/
│     │  ├─ base.py         ← 공통 인코딩 함수 (encode_query, encode_query_ko, encode_query_e5)
│     │  ├─ doc.py          ← 문서 임베더 (MiniLM 384d)
│     │  ├─ video.py        ← M11 동영상 임베더 (BLIP+STT+e5, 4단계 progress_cb)
│     │  ├─ image.py        ← 이미지 임베더 (OCR+MiniLM 384d)
│     │  └─ audio.py        ← 음성 임베더 (STT+ko-sroberta 768d)
│     └─ db/
│        ├─ init_db.py      ← SQLite 초기화 (settings, search_history)
│        └─ vector_store.py ← ChromaDB 인터페이스 (유형별 컬렉션 관리)
│
├─ Data
│  ├─ raw_DB
│  │  ├─ Docs
│  │  ├─ Movie
│  │  ├─ Rec
│  │  └─ Img
│  │
│  ├─ extracted_DB          ← 텍스트 캐시 (captions.json, stt.txt, chunks.json)
│  │  ├─ Docs
│  │  ├─ Movie
│  │  ├─ Rec
│  │  └─ Img
│  │
│  └─ embedded_DB           ← 벡터 캐시 (.npy) + ChromaDB (chroma.sqlite3)
│     ├─ Docs
│     ├─ Movie
│     ├─ Rec
│     └─ Img
│
└─ Docs
   ├─ Agents/
   │  ├─ frontend-agent.md
   │  ├─ backend-agent.md
   │  ├─ database-agent.md
   │  ├─ doc-embedding-agent.md
   │  ├─ video-embedding-agent.md
   │  ├─ image-embedding-agent.md
   │  └─ audio-embedding-agent.md
   │
   └─ Knowledge/
      ├─ API.md
      ├─ DataContract.md
      ├─ RetrievalSpec.md
      ├─ IndexingSpec.md
      └─ spec_video.md
```

---

## 3. 최상위 구성 요소 설명

### 3.1 constitution.md (1계층)

프로젝트의 최상위 규칙 문서이다.
모든 에이전트와 개발자는 이 문서를 기준으로 작업해야 하며, 코드 작성 규칙, 폴더 구조 규칙, 데이터 흐름 기준, 네이밍 규칙, 시스템 전체 동작 원칙을 포함한다.

---

### 3.2 App

실제 서비스가 실행되는 코드 영역이다.

#### frontend

사용자 인터페이스 담당. React + Vite + Electron.

**페이지 목록**

| 페이지 | 경로 | 설명 |
|--------|------|------|
| Login | `/` | 마스터 비밀번호 입력 |
| Setup | `/setup` | 최초 비밀번호 설정 |
| MainSearch | `/search` | 자연어 검색, 결과 목록, 파일 상세 (전체 청크 텍스트) |
| DataIndexing | `/data` | 데이터 관리 (3탭) |
| AIMode | `/ai` | AI 모드 |
| Settings | `/settings` | 비밀번호 변경 등 |

**DataIndexing 탭 구조**

| 탭 | 설명 |
|----|------|
| 인덱싱 | 폴더 선택 → 파일 트리 → 체크박스 선택 → 임베딩 시작/중단 (RingProgress 모달) |
| 데이터 소스 | 인덱싱된 파일 목록 (타입별 요약 카드 + 전체 파일 리스트) |
| 벡터 저장소 | ChromaDB 현황 (총 파일/청크 수, 컬렉션별 상세) |

#### backend

서비스 로직 담당. Flask REST API (포트 5001).

**routes 목록**

| 파일 | Blueprint | 엔드포인트 |
|------|-----------|-----------|
| auth.py    | `/api/auth`  | status, setup, verify, reset |
| history.py | `/api`       | GET/POST/DELETE /history |
| search.py  | `/api`       | GET /search, POST /files/open, POST /files/open-folder |
| index.py   | `/api/index` | POST /scan, POST /start, POST /stop/{id}, GET /status/{id} |
| files.py   | `/api/files` | GET /indexed, GET /stats, GET /detail |

---

### 3.3 Data

데이터 저장 영역. 3단계 분리.

- **extracted_DB**: 텍스트 캐시 (BLIP 캡션 JSON, Whisper STT txt, 청크 JSON, 가중치 JSON)
- **embedded_DB**: 임베딩 벡터 (.npy 캐시) + ChromaDB (chroma.sqlite3)

파일 유형별 서브폴더: `Movie` (video), `Docs` (doc), `Img` (image), `Rec` (audio)

---

### 3.4 Docs

AI 협업을 위한 문서 영역

- Agents (2계층) → 역할 정의
- Knowledge (3계층) → 최소 스펙 정의 (API, DataContract, RetrievalSpec, IndexingSpec, spec_video)

---

## 4. 임베딩 모델 요약

| 타입 | 모델 | 차원 | 캐시 위치 |
|------|------|------|-----------|
| doc   | paraphrase-multilingual-MiniLM-L12-v2 | 384d | embedded_DB/Docs/ |
| image | paraphrase-multilingual-MiniLM-L12-v2 | 384d | embedded_DB/Img/ |
| audio | jhgan/ko-sroberta-multitask            | 768d | embedded_DB/Rec/ |
| video | intfloat/multilingual-e5-large (M11)  | 1024d | embedded_DB/Movie/ |

---

## 5. 데이터 흐름

1. 사용자 폴더 지정 (DataIndexing → 인덱싱 탭)
2. 파일 스캔 (`POST /api/index/scan`)
3. 체크박스로 파일 선택
4. 임베딩 시작 (`POST /api/index/start`) → job_id 발급
5. 프론트 폴링 (`GET /api/index/status/{job_id}`) → RingProgress 모달 표시
   - video: 4단계 진행 (캡셔닝→STT→임베딩→저장)
   - 중단 가능 (`POST /api/index/stop/{job_id}`)
6. 임베딩 결과 → ChromaDB upsert + 텍스트 캐시 저장
7. 자연어 검색 (`GET /api/search?q=...`)
8. 결과 목록 → 파일 클릭 → 상세 조회 (`GET /api/files/detail?path=...`)

---

## 6. 설계 핵심 원칙

- 실행(App) / 데이터(Data) / 문서(Docs) 분리
- raw → extracted → embedded 3단 구조 유지
- 파일 식별자: `file_path` (절대 경로) — `file_id` 미사용
- 텍스트 캐시(`extracted_DB`) vs 벡터 캐시(`embedded_DB`) 분리
- 각 파일 유형별 독립 ChromaDB 컬렉션 + 독립 임베딩 모델
- progress_cb 패턴으로 video 임베딩 4단계 실시간 진행 표시
- 중단 flag 기반 stop 메커니즘 (파일 단위 + 단계 단위)
