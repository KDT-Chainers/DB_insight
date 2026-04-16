## 1. 프로젝트 개요

본 프로젝트는 사용자의 로컬 컴퓨터에 존재하는 문서, 이미지, 영상, 음성 파일을 자연어로 검색할 수 있도록 지원하는 AI 기반 로컬 파일 탐색 서비스이다.

사용자는 검색 대상이 될 로컬 경로를 지정할 수 있으며, 시스템은 해당 경로 내 파일들을 분석하여 텍스트를 추출하고, 이를 임베딩하여 벡터 데이터베이스에 저장한다. 이후 사용자가 자연어로 검색어를 입력하면, 시스템은 의미 기반 검색을 통해 관련 파일을 찾아 미리보기와 상세 정보를 제공한다.

본 프로젝트는 AI 협업 개발을 위해 다음의 3계층 구조를 채택한다.

- 1계층: 헌법 (Constitution) → 모든 작업의 공통 규칙
- 2계층: Agents → 역할별 전문 코딩 에이전트
- 3계층: Knowledge → 에이전트 간 충돌을 방지하는 최소 스펙

---

## 2. 전체 디렉토리 구조

DBI  
├─ constitution.md  
│  
├─ App  
│ ├─ frontend  
│ └─ backend  
│  
├─ Data  
│ ├─ raw_DB  
│ │ ├─ Docs  
│ │ ├─ Movie  
│ │ ├─ Rec  
│ │ └─ Img  
│ │  
│ ├─ extracted_DB  
│ │ ├─ Docs  
│ │ ├─ Movie  
│ │ ├─ Rec  
│ │ └─ Img  
│ │  
│ └─ embedded_DB  
│ ├─ Docs  
│ ├─ Movie  
│ ├─ Rec  
│ └─ Img  
│  
└─ Docs  
 ├─ Agents  
 │ ├─ frontend-agent.md  
 │ ├─ backend-agent.md  
 │ ├─ database-agent.md  
 │ ├─ doc-embedding-agent.md  
 │ ├─ video-embedding-agent.md  
 │ ├─ image-embedding-agent.md  
 │ └─ audio-embedding-agent.md  
 │  
 └─ Knowledge  
 ├─ API.md  
 ├─ DataContract.md  
 ├─ RetrievalSpec.md  
 └─ IndexingSpec.md

---

## 3. 최상위 구성 요소 설명

### 3.1 constitution.md (1계층)

프로젝트의 최상위 규칙 문서이다.

모든 에이전트와 개발자는 이 문서를 기준으로 작업해야 하며, 다음과 같은 내용을 포함한다.

- 코드 작성 규칙
- 폴더 구조 규칙
- 데이터 흐름 기준
- 네이밍 규칙
- 시스템 전체 동작 원칙

즉, **프로젝트의 절대 기준**이다.

---

### 3.2 App

실제 서비스가 실행되는 코드 영역이다.

#### frontend

사용자 인터페이스 담당

- 검색 UI
- 결과 표시
- 미리보기
- 상세 페이지
- 사용자 인터랙션

#### backend

서비스 로직 담당

- 경로 스캔
- 파일 처리
- 임베딩 파이프라인 실행
- 검색 요청 처리
- DB 연동

---

### 3.3 Data

데이터 저장 영역

본 프로젝트는 데이터를 3단계로 분리한다.

- raw_DB → 원본 파일 메타데이터
- extracted_DB → 추출된 텍스트/콘텐츠
- embedded_DB → 임베딩 벡터

이 구조는 검색 품질과 디버깅을 위해 필수적이다.

---

### 3.4 Docs

AI 협업을 위한 문서 영역

- Agents (2계층) → 역할 정의
- Knowledge (3계층) → 최소 스펙 정의

---

## 4. Data 구조 설명

### 4.1 raw_DB

원본 파일의 메타데이터 저장

- file_id
- path
- type
- created / modified time
- size
- hash
- indexing status

---

### 4.2 extracted_DB

파일에서 추출된 콘텐츠 저장

- 텍스트
- OCR 결과
- STT 결과
- chunk 데이터
- preview 텍스트

---

### 4.3 embedded_DB

임베딩 벡터 저장

- chunk_id
- file_id
- embedding vector
- metadata

---

## 5. Docs 구조 설명

### 5.1 Agents (2계층)

전문 코딩 에이전트 정의

각 에이전트는 **해당 도메인의 지식을 내부에 포함**한다.

- frontend-agent.md → UI/UX
- backend-agent.md → 서버 및 로직
- database-agent.md → 데이터 구조
- doc-embedding-agent.md → 문서 처리
- video-embedding-agent.md → 영상 처리
- image-embedding-agent.md → 이미지 처리
- audio-embedding-agent.md → 음성 처리

즉, **실제 작업을 수행하는 주체**이다.

---

### 5.2 Knowledge (3계층)

에이전트 간 충돌을 방지하는 최소 스펙

#### API.md

프론트 ↔ 백엔드 통신 규약

#### DataContract.md

모든 데이터 구조 정의 (file_id, chunk_id, metadata 등)

#### RetrievalSpec.md

검색 방식 정의 (유사도, top-k, 정렬 기준 등)

#### IndexingSpec.md

임베딩 및 인덱싱 기준 (chunking, 업데이트 정책 등)

👉 중요한 점:
이 영역은 **설명 문서가 아니라 “규칙 문서”**이다.

---

## 6. 파일 유형 분류

- Docs → 문서 (pdf, docx 등)
- Movie → 영상
- Rec → 음성
- Img → 이미지

---

## 7. 데이터 흐름

1. 사용자 경로 지정
2. 파일 스캔
3. raw_DB 저장
4. 콘텐츠 추출
5. extracted_DB 저장
6. 임베딩 수행
7. embedded_DB 저장
8. 자연어 검색
9. 결과 반환
10. 상세 조회

---

## 8. 설계 핵심 원칙

- 실행(App) / 데이터(Data) / 문서(Docs) 분리
- raw → extracted → embedded 3단 구조 유지
- 2계층(Agents)에 최대한 지식 포함
- 3계층(Knowledge)은 최소 규칙만 유지
- 모든 컴포넌트는 file_id / chunk_id 기준으로 연결

---

## 9. 결론

본 구조는 단순 파일 검색이 아니라,  
로컬 데이터를 의미 기반으로 이해하는 AI 시스템을 목표로 한다.

특히 3계층 구조를 통해  
AI 에이전트가 일관되게 협업할 수 있는 환경을 제공한다.
