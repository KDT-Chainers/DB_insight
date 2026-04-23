# constitution.md

## 1. 역할 정의

당신은 이 프로젝트에서 작업을 수행하는 코딩 에이전트이다.
이 문서는 모든 작업에서 반드시 따라야 하는 최상위 규칙이다.
모든 판단과 구현은 이 문서를 기준으로 이루어져야 한다.

이 문서는 항상 로드되는 1계층이며, 어떤 Knowledge 문서보다 우선한다.

**어떤 작업 지시를 받더라도, 반드시 이 문서(constitution.md)를 먼저 읽고 모든 규칙을 확인한 뒤 작업을 시작한다. 이 절차를 생략하는 것은 금지된다.**

---

## 2. 시스템 구조 이해

이 프로젝트는 다음 3계층 구조를 따른다.

- Constitution (1계층): 모든 작업의 기준 규칙
- Agents (2계층): 역할별 전문 작업 수행 주체
- Knowledge (3계층): 최소한의 공통 스펙

당신은 항상 이 구조를 전제로 작업해야 한다.

### 시스템 개요

DB_insight는 로컬 파일(문서/영상/이미지/음성)을 자연어로 검색하는 Electron 데스크탑 앱이다.

- **App/frontend**: React + Vite + Electron (UI, 페이지 전환 포함)
- **App/backend**: Flask REST API (포트 5001) — 인덱싱/검색/인증/파일 관리
- **Data/extracted_DB**: 텍스트 캐시 (video 전용 — captions.json, stt.txt 등)
- **Data/embedded_DB**: ChromaDB 벡터 저장소 (타입별 독립 컬렉션)

---

## 3. 작업 원칙

### 3.1 역할 기반 수행

당신은 자신의 역할(agent.md)에 정의된 범위 내에서만 작업해야 한다.

- frontend-agent → UI/UX, 페이지, 컴포넌트, 애니메이션
- backend-agent → Flask API, 라우팅, 비즈니스 로직
- database-agent → ChromaDB, SQLite, 벡터 저장소
- video-embedding-agent → BLIP + Whisper + e5-large 파이프라인
- doc-embedding-agent → 문서 텍스트 추출 + MiniLM 임베딩
- image-embedding-agent → OCR + MiniLM 임베딩
- audio-embedding-agent → Whisper STT + ko-sroberta 임베딩

다른 영역의 작업이 필요할 경우, 해당 영역의 규칙을 따른다.

### 3.2 지식 사용 우선순위

1. constitution.md (항상 우선)
2. 자신의 agent.md (전문 지식)
3. Knowledge 문서 (필요 시만 참조)

### 3.3 중복 구현 금지

- 동일한 로직을 여러 위치에 중복 구현하지 않는다
- 데이터 구조, API, 검색 방식은 항상 하나의 기준만 따른다
- 기준이 필요할 경우 Knowledge 문서를 참고한다

---

## 4. 파일 식별자 규칙

### file_path가 유일한 식별자

- 모든 파일은 **절대 경로(file_path)** 로 식별한다
- `file_id` 개념은 사용하지 않는다
- ChromaDB metadata, API 응답, 검색 결과 모두 `file_path` 기준

### chunk_id

- ChromaDB document ID는 `{file_path}::{chunk_index}` 형식을 권장한다
- 동일 파일 재인덱싱 시 upsert로 덮어쓴다

---

## 5. 데이터 저장 규칙

### 실제 데이터 흐름

```
[파일] → [Embedder] → [extracted_DB 텍스트 캐시] → [embedded_DB ChromaDB]
```

- **raw_DB**: 현재 미사용 (향후 확장 예약)
- **extracted_DB**: video 타입 전용 텍스트 캐시 (captions.json, stt.txt, chunks.json 등)
- **embedded_DB**: ChromaDB (타입별 독립 PersistentClient) + video .npy 벡터 캐시

### 경로 분리 규칙

| 저장 내용 | 경로 |
|----------|------|
| video 텍스트 캐시 | `Data/extracted_DB/Movie/` |
| video 벡터 캐시 (.npy) | `Data/embedded_DB/Movie/` |
| ChromaDB (전 타입) | `Data/embedded_DB/{Movie|Docs|Img|Rec}/` |
| SQLite 앱 DB | `App/backend/db/app.db` |

### 타입별 임베딩 모델

| 타입 | 모델 | 차원 |
|------|------|------|
| doc   | paraphrase-multilingual-MiniLM-L12-v2 | 384d |
| image | paraphrase-multilingual-MiniLM-L12-v2 | 384d |
| audio | jhgan/ko-sroberta-multitask | 768d |
| video | intfloat/multilingual-e5-large (M11) | 1024d |

---

## 6. ChromaDB metadata 규칙

모든 청크에 반드시 포함해야 하는 필드:

| 필드 | 설명 |
|------|------|
| file_path | 파일 절대 경로 (검색 결과 연결, 파일 열기 필수) |
| file_name | 파일명 (확장자 포함) |
| file_type | doc / video / image / audio |
| folder_path | 상위 폴더 경로 |
| chunk_index | 청크 순번 (0-based) |
| chunk_text | 청크 텍스트 (snippet, detail에 사용) |

임의 필드 추가/삭제 금지. video 전용 추가 필드: `chunk_source`, `blip_weight`, `stt_weight`.

---

## 7. Embedder 인터페이스 규칙

모든 embedder는 다음 시그니처를 따른다:

```python
embed(file_path: str, progress_cb=None) -> dict
# 반환: {"status": "done"} | {"status": "skipped", "reason": str} | {"status": "error", "reason": str}
```

- `progress_cb`는 video embedder만 사용: `(step, total, detail) -> bool`
- callback 반환값 `True` = 중단 신호

---

## 8. API 및 데이터 계약

- 프론트와 백엔드는 **API.md** 기준으로 통신한다
- 데이터 구조는 **DataContract.md** 기준으로 통일한다
- 임의의 필드 추가/변경은 금지된다
- 검색 결과는 flat array 형식 (타입별 중첩 구조 금지)

---

## 9. 인덱싱 및 검색 규칙

### 인덱싱

- 파일 유형별 embedder를 사용한다 (`embedders/{type}.py`)
- 재인덱싱 시 ChromaDB upsert (기존 청크 덮어쓰기)
- video는 4단계 progress_cb로 진행 상황을 실시간 보고한다

### 검색

- 검색은 반드시 embedded_DB (ChromaDB) 기준으로 수행한다
- 타입별 모델로 쿼리를 인코딩한 뒤 각 컬렉션에서 검색한다
- 결과는 similarity 내림차순 flat array로 반환한다

### 삭제

- `DELETE /api/files/delete` 호출 시 해당 file_path의 모든 청크를 ChromaDB에서 제거한다
- 원본 파일은 건드리지 않는다

---

## 10. 프론트엔드 규칙

- React Router v6 (HashRouter)
- 페이지 이동 시 입장 애니메이션 적용 (`.page-enter`, `.page-enter-right`)
- 로그인 성공 시 플래시 이펙트 (`.login-flash`) 후 navigate
- 모든 API 호출은 `API_BASE` 상수 사용

### 페이지 목록

| 경로 | 컴포넌트 |
|------|---------|
| `/` | LandingLogin |
| `/setup` | InitialSetup |
| `/search` | MainSearch |
| `/ai` | MainAI |
| `/settings` | Settings |
| `/data` | DataIndexing (인덱싱 / 데이터 소스 / 벡터 저장소 3탭) |

---

## 11. 오류 처리 원칙

- 모든 오류는 무시하지 않고 처리한다
- 실패 시 원인을 추적할 수 있어야 한다
- 데이터 손실이 발생하는 처리는 금지된다
- embedder 예외 발생 시 `{"status": "error", "reason": str}` 반환

---

## 12. 파일 인코딩 규칙

- 모든 파일은 **UTF-8 (BOM 없음)** 으로 저장한다
- 한글 문자열을 `\uXXXX` 유니코드 이스케이프로 작성하지 않는다
  - 금지: `'\uBE44\uBC00\uBC88\uD638'`
  - 허용: `'비밀번호'`
- JSX 및 모든 소스 파일 내 한글 텍스트는 직접 작성한다

---

## 13. 금지 사항

- `file_id` 기반 식별 구현 (→ `file_path` 사용)
- Knowledge 없이 임의 구조 생성
- 역할 범위를 벗어난 구현
- 동일 기능 중복 구현
- ChromaDB metadata 임의 필드 추가/삭제
- 타입별 모델 불일치 임베딩

---

## 14. 최종 목표

- 일관된 구조 유지
- 재현 가능한 데이터 처리
- 안정적인 검색 결과 제공

모든 구현은 "작동"이 아니라 "일관되고 유지 가능한 구조"를 목표로 해야 한다.
