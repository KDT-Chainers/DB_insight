# API Spec

## 기본 규칙

- 모든 요청/응답은 JSON
- 성공: HTTP 200, 실패: 적절한 4xx/5xx
- 에러 응답 형식: `{ "error": "메시지" }`

---

## 인덱싱

### POST /api/index
경로 인덱싱 시작

**Request**
```json
{ "path": "/Users/foo/Documents" }
```

**Response**
```json
{ "job_id": "string", "status": "started" }
```

---

## 검색

### GET /api/search
자연어 검색

**Query Params**
- `q` (필수): 검색어
- `method` (선택, 기본 M7): 임베딩 방법
- `top_k` (선택, 기본 10): 결과 수

**Response**
```json
{
  "results": [
    {
      "file_id": "string",
      "score": 0.95,
      "path": "string",
      "type": "string",
      "preview": "string"
    }
  ]
}
```

---

## 파일 상세

### GET /api/files/{file_id}
파일 상세 조회

**Response**
```json
{
  "file_id": "string",
  "path": "string",
  "type": "string",
  "size": 1024,
  "preview": "string",
  "indexed_at": "ISO 8601"
}
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
마스터 비밀번호 변경 (settings > 코어 초기화)

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
      "method": "M7",
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
{
  "query": "string",
  "method": "M7",
  "result_count": 5
}
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
