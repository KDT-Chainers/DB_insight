# Data Contract

## 공통 키

- `file_path`: 파일 식별자 (절대 경로, 모든 계층에서 동일)
- `chunk_id`: 청크 식별자 (ChromaDB document ID, `{file_path}::{chunk_index}` 형식 권장)

---

## 파일 데이터 (3단 구조)

### raw_DB
현재 미사용 (ChromaDB metadata로 통합). 향후 SQLite 기반 파일 레지스트리로 확장 가능.

### extracted_DB

파일에서 추출된 중간 결과물 (텍스트 캐시). 재인덱싱 시 재사용.

**경로 규칙**
| 파일 유형 | 경로 |
|-----------|------|
| video 캡션 | `Data/extracted_DB/Movie/{stem}_captions.json` |
| video STT  | `Data/extracted_DB/Movie/{stem}_stt.txt` |
| video 청크 | `Data/extracted_DB/Movie/{stem}_blip_chunks.json` / `_stt_chunks.json` |
| video 가중치 | `Data/extracted_DB/Movie/weight_buckets.json` |

### embedded_DB (ChromaDB)

임베딩 벡터 + 메타데이터 저장. 유형별 PersistentClient 인스턴스 분리.

**경로 규칙**
| 파일 유형 | ChromaDB 경로 | .npy 캐시 경로 |
|-----------|--------------|----------------|
| doc   | `Data/embedded_DB/Docs/`  | — |
| video | `Data/embedded_DB/Movie/` | `Data/embedded_DB/Movie/{stem}_blip_embs.npy` |
| image | `Data/embedded_DB/Img/`   | — |
| audio | `Data/embedded_DB/Rec/`   | — |

---

## ChromaDB metadata 스키마

모든 유형 공통 필수 필드:

| 필드 | 타입 | 설명 |
|------|------|------|
| file_path    | string | 파일 절대 경로 (검색 결과 연결, 파일 열기에 사용) |
| file_name    | string | 파일명 (확장자 포함) |
| file_type    | string | doc / video / image / audio |
| folder_path  | string | 파일이 속한 폴더 절대 경로 |
| chunk_index  | int    | 청크 순번 (0부터 시작) |
| chunk_text   | string | 청크 텍스트 (검색 결과 snippet 및 detail에 사용) |

video 전용 추가 필드:

| 필드 | 타입 | 설명 |
|------|------|------|
| chunk_source | string | `"blip"` (프레임 캡션) 또는 `""` (STT) |
| blip_weight  | float  | 해당 영상의 BLIP 가중치 |
| stt_weight   | float  | 해당 영상의 STT 가중치 |

---

## API 응답 구조

### ScanItem (POST /api/index/scan 응답 items 요소)
```json
{
  "name": "보고서.pdf",
  "path": "C:/Users/.../보고서.pdf",
  "kind": "file",
  "type": "doc",
  "size": 102400
}
```
- `kind`: `"file"` | `"folder"`
- `type`: `"doc"` / `"video"` / `"image"` / `"audio"` / `null`

### IndexResult (GET /api/index/status 응답 results 요소)
```json
{
  "path":        "C:/Users/.../회의.mp4",
  "status":      "running",
  "step":        2,
  "step_total":  4,
  "step_detail": "음성 텍스트 변환 중..."
}
```
- `status`: `"pending"` / `"running"` / `"done"` / `"skipped"` / `"error"`
- `step` / `step_total` / `step_detail`: video 처리 중에만 포함

### SearchResult (GET /api/search 응답 results 요소)
```json
{
  "file_path":  "C:/Users/.../보고서.pdf",
  "file_name":  "보고서.pdf",
  "file_type":  "doc",
  "similarity": 0.91,
  "snippet":    "...검색어 주변 텍스트..."
}
```

### FileDetail (GET /api/files/detail 응답)
```json
{
  "file_path": "C:/Users/.../보고서.pdf",
  "file_type": "doc",
  "chunks": [
    { "chunk_index": 0, "chunk_text": "텍스트...", "chunk_source": "" }
  ],
  "full_text": "전체 텍스트..."
}
```

---

## 앱 데이터 (SQLite: App/backend/db/app.db)

### settings 테이블
비밀번호 등 앱 설정 저장

| 필드 | 타입 | 설명 |
|------|------|------|
| key | TEXT (PK) | 설정 키 |
| value | TEXT | 설정 값 |
| updated_at | TEXT | ISO 8601 |

**사전 정의된 key 목록**

| key | value 형식 | 설명 |
|-----|-----------|------|
| `master_password_hash` | `{salt}:{SHA256(salt+password)}` | 마스터 비밀번호 해시 |

```sql
CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

---

### search_history 테이블

| 필드 | 타입 | 설명 |
|------|------|------|
| id | INTEGER (PK, AUTOINCREMENT) | 기록 식별자 |
| query | TEXT | 검색어 |
| method | TEXT | 검색 유형 (doc/video/image/audio) |
| result_count | INTEGER | 반환된 전체 결과 수 |
| searched_at | TEXT | ISO 8601 |

```sql
CREATE TABLE search_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT NOT NULL,
    method       TEXT,
    result_count INTEGER,
    searched_at  TEXT NOT NULL
);
```

---

## 규칙

- `file_path` (절대 경로)가 파일의 기본 식별자 — `file_id` 미사용
- 임의 필드 추가/삭제 금지
- 모든 시각 필드는 ISO 8601 문자열 (UTC)
- SQLite DB 파일 위치: `App/backend/db/app.db` — 앱 설정 전용
- 파일 임베딩 데이터는 ChromaDB (유형별 컬렉션 분리)
- ChromaDB metadata에 `file_path` / `folder_path` 반드시 포함 (파일 열기 기능 필수)
- 텍스트 캐시(captions/STT)는 `extracted_DB/`, 임베딩 벡터(.npy)는 `embedded_DB/`에 저장
