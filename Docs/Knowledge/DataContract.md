# Data Contract

## 공통 키

- `file_id`: 파일 식별자 (raw_DB에서 생성, 모든 계층에서 동일)
- `chunk_id`: 청크 식별자 (반드시 file_id 포함, 예: `file_001_chunk_001`)

---

## 파일 데이터 (3단 구조)

### raw_DB
| 필드 | 타입 | 설명 |
|------|------|------|
| file_id | string | 파일 고유 식별자 |
| path | string | 절대 경로 |
| type | string | Docs / Movie / Rec / Img |
| size | integer | 바이트 |
| hash | string | SHA256 |
| indexing_status | string | pending / processing / done / failed |
| created_at | string | ISO 8601 |
| modified_at | string | ISO 8601 |

### extracted_DB
| 필드 | 타입 | 설명 |
|------|------|------|
| file_id | string | raw_DB와 동일 |
| text | string | 추출된 전체 텍스트 |
| ocr_text | string | OCR 결과 (이미지/PDF) |
| stt_text | string | STT 결과 (영상/음성) |
| chunks | array | chunk 텍스트 배열 |
| preview | string | 미리보기용 요약 텍스트 |

### embedded_DB
| 필드 | 타입 | 설명 |
|------|------|------|
| chunk_id | string | 청크 식별자 |
| file_id | string | raw_DB와 동일 |
| embedding | array | float 벡터 |
| metadata | object | 검색 결과 연결용 부가 정보 |

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

- 해당 row가 없으면 비밀번호 미설정 상태(`initialized: false`)
- 비밀번호는 반드시 해시로 저장, 평문 저장 금지

```sql
CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

---

### search_history 테이블
검색 기록 저장

| 필드 | 타입 | 설명 |
|------|------|------|
| id | INTEGER (PK, AUTOINCREMENT) | 기록 식별자 |
| query | TEXT | 검색어 |
| method | TEXT | 임베딩 방법 (M7 등) |
| result_count | INTEGER | 반환된 결과 수 |
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

- 임의 필드 추가/삭제 금지
- 모든 시각 필드는 ISO 8601 문자열 (UTC)
- SQLite DB 파일 위치: `App/backend/db/app.db`
- SQLite는 앱 설정 전용 — 파일 임베딩 데이터는 기존 3단 구조 유지
