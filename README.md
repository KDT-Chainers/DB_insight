## Architecture

본 프로젝트는 로컬 파일을 의미 기반으로 검색하기 위한 AI 시스템으로,  
**실행(App) / 데이터(Data) / 지식(Docs)**을 명확히 분리한 구조를 가진다.

데이터는 다음의 3단계로 처리된다:

- **raw_DB**: 파일 메타데이터 저장
- **extracted_DB**: 텍스트/OCR/STT 등 추출된 콘텐츠
- **embedded_DB**: 임베딩 벡터 (ChromaDB)

이를 통해 검색 정확도와 유지보수 효율을 동시에 확보한다.

또한 AI 협업을 위해 **3계층 구조**를 적용한다:

- **Constitution (1계층)**: 전체 시스템의 공통 규칙
- **Agents (2계층)**: 역할별 전문 코딩 에이전트
- **Knowledge (3계층)**: 에이전트 간 충돌 방지를 위한 최소 스펙

---

### Project Structure

```
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
```

이 구조는 각 영역의 책임을 분리하면서도,  
AI 에이전트 기반 개발에서 일관성과 확장성을 유지하도록 설계되었다.

---

## 백엔드 실행 방법

### 기술 스택

- **Python** + **Flask**
- **SQLite** (앱 설정 및 검색 기록 저장)

### 실행

```bash
# 최초 1회: 의존성 설치
pip install -r App/backend/requirements.txt

# 서버 실행 (포트 5001)
python App/backend/app.py
```

`Running on http://127.0.0.1:5001` 이 출력되면 정상 실행된 것이다.

### 엔드포인트

| 경로 | 설명 |
|------|------|
| `GET /api/auth/status` | 비밀번호 설정 여부 확인 |
| `POST /api/auth/setup` | 최초 비밀번호 설정 |
| `POST /api/auth/verify` | 비밀번호 검증 |
| `POST /api/auth/reset` | 마스터 비밀번호 변경 |
| `GET /api/history` | 검색 기록 조회 |
| `DELETE /api/history` | 전체 검색 기록 삭제 |
| `DELETE /api/history/<id>` | 특정 검색 기록 삭제 |

전체 API 스펙은 `Docs/Knowledge/API.md` 참고.

---

## 프론트엔드 실행 방법

### 기술 스택

- **React 18** + **Vite**
- **React Router v6** (페이지 라우팅)
- **Tailwind CSS** (스타일링)

### 실행

```bash
cd App/frontend
npm install
npm run dev
```

브라우저에서 `http://localhost:3000` 접속

빌드 결과물은 `App/frontend/dist/` 에 생성된다.

### 페이지 구조

| 경로                  | 설명                      |
| --------------------- | ------------------------- |
| `/`                   | 로그인                    |
| `/setup`              | 초기 설정 (마스터키 생성) |
| `/search`             | 검색 모드 메인            |
| `/search/results`     | 검색 결과 목록            |
| `/search/results/:id` | 파일 상세 보기            |
| `/ai`                 | AI 모드 메인              |
| `/ai/results`         | AI 검색 결과              |
| `/ai/results/:id`     | AI 파일 상세 보기         |
| `/settings`           | 설정                      |
| `/data`               | 데이터 인덱싱             |
