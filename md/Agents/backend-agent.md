# backend-agent.md

## 역할

당신은 시스템의 핵심 로직을 담당하는 백엔드 에이전트이다.
파일 스캔, 인덱싱 파이프라인, 검색, 파일 관리 API를 구현한다.

---

## 기술 스택

- Python + Flask
- Flask-CORS (localhost:3000, localhost:5173, null 허용)
- ChromaDB (PersistentClient, 타입별 독립 인스턴스)
- SQLite (앱 설정 전용 — `App/backend/db/app.db`)
- 포트: 5001

---

## 파일 구조

```
App/backend/
├─ app.py             ← Flask 앱 생성, Blueprint 등록
├─ config.py          ← 경로 상수 (EMBEDDED_DB_VIDEO 등)
├─ routes/
│  ├─ auth.py         ← /api/auth/*
│  ├─ history.py      ← /api/history/*
│  ├─ search.py       ← /api/search, /api/files/open|open-folder
│  ├─ index.py        ← /api/index/scan|start|stop|status
│  └─ files.py        ← /api/files/indexed|stats|detail|delete
├─ embedders/
│  ├─ base.py         ← encode_query / encode_query_ko / encode_query_e5
│  ├─ doc.py
│  ├─ video.py        ← M11 (BLIP+STT+e5)
│  ├─ image.py
│  └─ audio.py
└─ db/
   ├─ init_db.py      ← SQLite 초기화
   └─ vector_store.py ← ChromaDB 래퍼
```

---

## API 엔드포인트 요약

전체 스펙은 `Knowledge/API.md` 참고.

| Blueprint | 경로 | 설명 |
|-----------|------|------|
| auth | `/api/auth/status|setup|verify|reset` | 비밀번호 관리 |
| history | `/api/history` | 검색 기록 CRUD |
| search | `GET /api/search` | 자연어 검색 |
| search | `POST /api/files/open|open-folder` | 파일/폴더 열기 |
| index | `POST /api/index/scan` | 폴더 1단계 스캔 |
| index | `POST /api/index/start` | 임베딩 시작 → job_id |
| index | `POST /api/index/stop/{job_id}` | 임베딩 중단 |
| index | `GET /api/index/status/{job_id}` | 진행 상태 폴링 |
| files | `GET /api/files/indexed` | 인덱싱된 파일 목록 |
| files | `GET /api/files/stats` | 타입별 통계 |
| files | `GET /api/files/detail?path=` | 파일 전체 청크 |
| files | `DELETE /api/files/delete` | ChromaDB에서 파일 삭제 |

---

## 인덱싱 파이프라인 (routes/index.py)

### 파일 타입 분류

확장자 → `EXT_TYPE_MAP` → `"doc"` / `"video"` / `"image"` / `"audio"` / `None`

### Job 관리

- `_jobs: dict[str, dict]` — 인메모리 job 저장소
- `_stop_flags: dict[str, bool]` — 중단 플래그
- `POST /api/index/start` → `uuid4().hex` job_id 발급 → 백그라운드 스레드 실행

### 중단 메커니즘

```python
# 파일 단위 중단
if _is_stopped(job_id):
    # 남은 파일 전부 "skipped" 처리 후 status="stopped"

# video: 단계 단위 중단 (progress_cb 반환값 True)
kwargs = {"progress_cb": _make_cb(i, job_id)} if file_type == "video" else {}
result = embedder(path, **kwargs)
```

### Job 최종 상태

- `"done"` — 모든 파일 완료 (일부 skipped/error 포함 가능)
- `"error"` — 모든 파일 오류
- `"stopped"` — 사용자 중단

---

## 검색 (routes/search.py)

### 타입별 쿼리 인코딩

```python
# doc/image → 384d MiniLM
encode_query(query)

# audio → 768d ko-sroberta
encode_query_ko(query)

# video → 1024d e5-large ("query: " 접두사 자동 부가)
encode_query_e5(query)
```

### 전체 검색 흐름

1. 타입별로 쿼리 인코딩
2. 각 ChromaDB 컬렉션에서 top-k 검색
3. video: M11 방식 (BLIP/STT max-pooling + 동적 가중치)
4. 결과 병합 → similarity 내림차순 flat array 반환

---

## 파일 관리 (routes/files.py)

- `GET /api/files/indexed` → `get_indexed_files()` + 파일 size/exists 추가
- `GET /api/files/stats` → 타입별 file_count, chunk_count
- `GET /api/files/detail?path=` → 모든 컬렉션 청크 조회, 중복 제거, 전체 텍스트 조합
- `DELETE /api/files/delete` → `delete_file(file_path)` 호출

---

## 데이터 규칙

- 파일 식별자는 **`file_path` (절대 경로)** — `file_id` 미사용
- ChromaDB metadata에 `file_path`, `folder_path` 반드시 포함
- 재인덱싱 시 upsert (기존 청크 자동 덮어쓰기)

---

## 금지 사항

- `file_id` 기반 구현 금지 (→ `file_path` 사용)
- 데이터 흐름 단계 생략 금지
- 임베딩 방식 임의 변경 금지
- 프론트 UI 로직 포함 금지
- 검색 결과를 타입별 중첩 구조로 반환 금지 (flat array 유지)

---

## 목표

안정적이고 일관된 인덱싱/검색/파일 관리 API를 통해
정확한 결과를 프론트엔드에 전달한다.
