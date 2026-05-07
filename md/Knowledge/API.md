# API Spec

## 기본 규칙

- 모든 요청/응답은 JSON
- 성공: HTTP 200, 실패: 적절한 4xx/5xx
- 에러 응답 형식: `{ "error": "메시지" }`

---

## 검색

### GET /api/search

자연어 검색 — 쿼리를 인덱싱된 타입의 검색기에 동시에 전달하여 통합 결과를 반환한다.

**Query Params**
- `q` (필수): 검색어
- `top_k` (선택, 기본 10): 최대 결과 수
- `type` (선택): `doc` | `video` | `image` | `audio` — 지정 시 해당 타입만 검색

**Response**
```json
{
  "query": "검색어",
  "results": [
    {
      "file_path":  "C:/Users/.../보고서.pdf",
      "file_name":  "보고서.pdf",
      "file_type":  "doc",
      "similarity": 0.91,
      "snippet":    "...검색어 주변 텍스트..."
    }
  ]
}
```

- `results`는 similarity 내림차순 정렬 (모든 타입 통합)
- 인덱싱된 파일이 없으면 `results: []` 반환

**Error**
```json
{ "error": "q is required" }
```

---

## 파일 열기

### POST /api/files/open

OS 기본 앱으로 파일 직접 열기

**Request Body**
```json
{ "file_path": "C:/Users/.../보고서.pdf" }
```

**Response**
```json
{ "success": true }
```

**Error**
```json
{ "error": "File not found" }
```

---

### POST /api/files/open-folder

파일 탐색기로 해당 파일이 있는 폴더 열기 (파일 선택 상태)

**Request Body**
```json
{ "file_path": "C:/Users/.../보고서.pdf" }
```

**Response**
```json
{ "success": true }
```

---

## 파일 정보

### GET /api/files/indexed

인덱싱된 모든 파일 목록 (파일별 청크 수 포함)

**Response**
```json
{
  "files": [
    {
      "file_path":   "C:/Users/.../보고서.pdf",
      "file_name":   "보고서.pdf",
      "file_type":   "doc",
      "chunk_count": 12,
      "size":        102400,
      "exists":      true
    }
  ],
  "total": 1
}
```

- `size`: 파일이 존재하면 바이트 크기, 없으면 `null`
- `exists`: 파일이 실제로 존재하는지 여부

---

### GET /api/files/stats

타입별 파일 수·청크 수 통계

**Response**
```json
{
  "by_type": {
    "doc":   { "file_count": 5, "chunk_count": 48 },
    "video": { "file_count": 2, "chunk_count": 30 },
    "image": { "file_count": 0, "chunk_count": 0  },
    "audio": { "file_count": 1, "chunk_count": 8  }
  },
  "total_files":  8,
  "total_chunks": 86
}
```

---

### GET /api/files/detail

특정 파일의 전체 청크 텍스트 조회

**Query Params**
- `path` (필수): 파일 절대 경로

**Response**
```json
{
  "file_path": "C:/Users/.../보고서.pdf",
  "file_type": "doc",
  "chunks": [
    {
      "chunk_index":  0,
      "chunk_text":   "청크 텍스트...",
      "chunk_source": ""
    }
  ],
  "full_text": "전체 청크 텍스트를 이어붙인 문자열"
}
```

- `chunk_source`: video 타입의 경우 `"blip"` (프레임 캡션) 또는 `""` (STT)
- video 타입의 `full_text`는 `[프레임 캡션]\n...` + `[음성 텍스트]\n...` 형식

---

## 인덱싱

### POST /api/index/scan

폴더 경로를 1단계 스캔하여 파일/폴더 목록 반환.
프론트의 리소스 탐색기에 표시할 데이터를 제공한다.

**Request**
```json
{ "path": "C:/Users/foo/Documents" }
```

**Response**
```json
{
  "path": "C:/Users/foo/Documents",
  "items": [
    { "name": "하위폴더",   "path": "C:/Users/foo/Documents/하위폴더",   "kind": "folder", "type": null,    "size": null   },
    { "name": "보고서.pdf", "path": "C:/Users/foo/Documents/보고서.pdf", "kind": "file",   "type": "doc",   "size": 102400 },
    { "name": "회의.mp4",   "path": "C:/Users/foo/Documents/회의.mp4",   "kind": "file",   "type": "video", "size": 524288 },
    { "name": "unknown.xyz","path": "C:/Users/foo/Documents/unknown.xyz","kind": "file",   "type": null,    "size": 1024   }
  ]
}
```

- `kind`: `"folder"` | `"file"`
- `type`: `"doc"` / `"video"` / `"image"` / `"audio"` / `null` (지원 안 되는 확장자 또는 폴더)
- 폴더 먼저, 파일 나중 (이름 오름차순)

**Error**
```json
{ "error": "Path not found" }
```

---

### POST /api/index/start

선택한 파일들의 임베딩을 시작한다.
백엔드가 확장자를 보고 적합한 embedder를 자동 선택한다.

**Request**
```json
{
  "files": [
    "C:/Users/foo/Documents/보고서.pdf",
    "C:/Users/foo/Documents/회의.mp4"
  ]
}
```

**Response**
```json
{ "job_id": "abc123", "total": 2 }
```

**Error**
```json
{ "error": "No valid files provided" }
```

---

### GET /api/index/status/{job_id}

인덱싱 진행 상태 조회. 프론트에서 폴링하여 진행 상황을 표시한다.

**Response**
```json
{
  "job_id":   "abc123",
  "status":   "running",
  "total":    2,
  "done":     1,
  "skipped":  0,
  "errors":   0,
  "stopping": false,
  "results": [
    { "path": "C:/…/보고서.pdf", "status": "done" },
    {
      "path":        "C:/…/회의.mp4",
      "status":      "running",
      "step":        2,
      "step_total":  4,
      "step_detail": "음성 텍스트 변환 중..."
    }
  ]
}
```

- `status`: `"running"` / `"done"` / `"error"` / `"stopped"`
- `stopping`: `true`이면 중단 요청됨 (아직 진행 중)
- `step` / `step_total` / `step_detail`: video 파일 처리 중에만 포함 (4단계 진행)

---

### POST /api/index/stop/{job_id}

진행 중인 인덱싱 작업을 중단 요청한다.
현재 처리 중인 파일은 완료 후 다음 파일부터 중단.
video 임베더는 현재 단계 완료 후 중단.

**Response**
```json
{ "ok": true }
```

**Error**
```json
{ "error": "Job not found" }
```

---

## 인증 (비밀번호)

### GET /api/auth/status

비밀번호 초기 설정 여부 확인

**Response**
```json
{ "initialized": true }
```

---

### POST /api/auth/setup

최초 비밀번호 설정 (미설정 상태에서만 허용)

**Request**
```json
{ "password": "string" }
```

**Response**
```json
{ "success": true }
```

**Error** (이미 설정된 경우)
```json
{ "error": "Already initialized" }
```

---

### POST /api/auth/verify

비밀번호 검증

**Request**
```json
{ "password": "string" }
```

**Response**
```json
{ "success": true }
```

**Error** (불일치)
```json
{ "error": "Invalid password" }
```

---

### POST /api/auth/reset

마스터 비밀번호 변경

**Request**
```json
{
  "current_password": "string",
  "new_password": "string"
}
```

**Response**
```json
{ "success": true }
```

**Error**
```json
{ "error": "Invalid current password" }
```

---

## 검색 기록

### GET /api/history

검색 기록 조회 (최신순)

**Query Params**
- `limit` (선택, 기본 50): 최대 반환 수

**Response**
```json
{
  "history": [
    {
      "id": 1,
      "query": "string",
      "method": "string",
      "result_count": 5,
      "searched_at": "ISO 8601"
    }
  ]
}
```

---

### POST /api/history

검색 기록 저장 (검색 수행 시 백엔드에서 자동 호출, 프론트 직접 호출 금지)

**Request**
```json
{ "query": "string", "method": "string", "result_count": 5 }
```

**Response**
```json
{ "id": 1 }
```

---

### DELETE /api/history

전체 검색 기록 삭제

**Response**
```json
{ "success": true }
```

---

### DELETE /api/history/{id}

특정 검색 기록 삭제

**Response**
```json
{ "success": true }
```
