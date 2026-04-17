# API Spec

## 기본 규칙

- 모든 요청/응답은 JSON
- 성공: HTTP 200, 실패: 적절한 4xx/5xx
- 에러 응답 형식: `{ "error": "메시지" }`

---

## 검색

### GET /api/search

자연어 검색 — 쿼리를 doc/video/image/audio 검색기에 동시에 전달하여 유형별 결과를 반환한다.

**Query Params**
- `q` (필수): 검색어
- `top_k` (선택, 기본 10): 유형별 최대 결과 수

**Response**
```json
{
  "query": "검색어",
  "results": {
    "doc":   { "available": true,  "items": [ SearchResult, "..." ] },
    "video": { "available": false, "items": [] },
    "image": { "available": true,  "items": [ SearchResult, "..." ] },
    "audio": { "available": false, "items": [] }
  }
}
```

- `available: false` → 해당 유형 검색기 미구현/미연결 상태
- `items`는 similarity 내림차순 정렬

**SearchResult**
```json
{
  "file_id":    "string",
  "file_name":  "보고서.pdf",
  "similarity": 0.91,
  "snippet":    "...검색어 주변 텍스트..."
}
```

**Error**
```json
{ "error": "q is required" }
```

---

## 파일 상세

### GET /api/files/{file_id}

파일 상세 조회 (검색 결과 클릭 시 호출)

**Response**
```json
{
  "file_id":         "string",
  "file_name":       "보고서.pdf",
  "file_type":       "doc",
  "file_path":       "C:/Users/.../보고서.pdf",
  "folder_path":     "C:/Users/...",
  "content_preview": "...파일 내용 미리보기..."
}
```

---

## 파일/폴더 열기

### POST /api/files/{file_id}/open

OS 기본 앱으로 파일 직접 열기

**Response**
```json
{ "success": true }
```

**Error**
```json
{ "error": "File not found" }
```

---

### POST /api/files/{file_id}/open-folder

파일 탐색기로 해당 파일이 있는 폴더 열기

**Response**
```json
{ "success": true }
```

**Error**
```json
{ "error": "File not found" }
```

---

## 인덱싱

### POST /api/index/scan

폴더 경로를 스캔하여 파일 목록 반환.
프론트의 리소스 탐색기에 표시할 데이터를 제공한다.

**Request**
```json
{ "path": "C:/Users/foo/Documents" }
```

**Response**
```json
{
  "path": "C:/Users/foo/Documents",
  "files": [
    { "name": "보고서.pdf", "path": "C:/Users/foo/Documents/보고서.pdf", "type": "doc",   "size": 102400 },
    { "name": "회의.mp4",   "path": "C:/Users/foo/Documents/회의.mp4",   "type": "video", "size": 524288 },
    { "name": "사진.jpg",   "path": "C:/Users/foo/Documents/사진.jpg",   "type": "image", "size": 20480  },
    { "name": "unknown.xyz","path": "C:/Users/foo/Documents/unknown.xyz","type": null,    "size": 1024   }
  ]
}
```

- `type`: `"doc"` / `"video"` / `"image"` / `"audio"` / `null` (지원 안 되는 확장자)
- 하위 폴더는 재귀 스캔

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
  "job_id":  "abc123",
  "status":  "running",
  "total":   2,
  "done":    1,
  "errors":  0,
  "results": [
    { "path": "C:/…/보고서.pdf", "status": "done"    },
    { "path": "C:/…/회의.mp4",   "status": "running" }
  ]
}
```

- `status`: `"running"` / `"done"` / `"error"`

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
