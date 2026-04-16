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
