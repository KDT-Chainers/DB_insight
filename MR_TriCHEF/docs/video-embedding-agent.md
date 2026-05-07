# video-embedding-agent.md

## 역할

당신은 동영상 파일의 임베딩을 담당하는 에이전트이다.
M11 파이프라인(BLIP 캡셔닝 + Whisper STT + e5-large)으로
영상 콘텐츠를 벡터로 변환하고 ChromaDB에 저장한다.

---

## 지원 확장자

`.mp4`, `.avi`, `.mov`, `.mkv`, `.wmv`

---

## 기술 스택 / 모델

| 역할 | 모델 |
|------|------|
| 프레임 캡셔닝 | `Salesforce/blip-image-captioning-base` |
| STT | `faster-whisper medium` (한국어) |
| 임베딩 | `intfloat/multilingual-e5-large` (1024d) |

---

## M11 파이프라인 (4단계)

```python
embed(file_path, progress_cb=None) -> dict
```

### Step 1 — BLIP 캡셔닝

- 매 30프레임마다 영어 캡션 1개 생성
- 이미지 파일 저장 없음 (메모리에서 처리 후 소멸)
- 캐시: `extracted_DB/Movie/{stem}_captions.json`

### Step 2 — Whisper STT

- `faster-whisper medium`, 언어=한국어, VAD 필터 적용
- STT 결과 없으면 `"(음성 없음)"` 처리
- 캐시: `extracted_DB/Movie/{stem}_stt.txt`

### Step 3 — 동적 가중치 + 양방향 청킹 + e5 임베딩

**동적 가중치**
```
ratio = n_frames / (n_frames + stt_len)
→ 0~8 구간 버킷 매핑 → (blip_weight, stt_weight)
```
9개 버킷: `(0.1, 0.9)` ~ `(0.9, 0.1)`

**청킹 방식**
- BLIP: 캡션 10개씩 묶음 (순방향 + 역방향)
- STT: 400자 슬라이딩, 100자 오버랩 (순방향 + 역방향)

**임베딩**
- `"passage: {텍스트}"` 접두사 필수
- e5-large 1024d 벡터 출력
- 임베딩 캐시: `embedded_DB/Movie/{stem}_blip_embs.npy`, `{stem}_stt_embs.npy`
- 청크 텍스트 캐시: `extracted_DB/Movie/{stem}_blip_chunks.json`, `{stem}_stt_chunks.json`

### Step 4 — ChromaDB 저장

- 기존 청크 먼저 삭제 (`delete_file(file_path, file_type="video")`)
- BLIP 청크: `chunk_source="blip"`, STT 청크: `chunk_source="stt"`
- ID 형식: `{file_hash}_blip_{i}` / `{file_hash}_stt_{i}`

---

## progress_cb 인터페이스

```python
progress_cb(step: int, total: int, detail: str) -> bool
# True 반환 = 중단 신호
```

| step | 내용 |
|------|------|
| 1/4 | 프레임 캡셔닝 중 |
| 2/4 | 음성 텍스트 변환 중 |
| 3/4 | 임베딩 생성 중 |
| 4/4 | 벡터DB 저장 중 |

각 단계 진입 전 `progress_cb` 반환값이 `True`이면 즉시 `"skipped"` 반환.

---

## 반환값

```python
{"status": "done",    "chunks": int, "blip": int, "stt": int}
{"status": "skipped", "reason": str}   # 사용자 중단 또는 데이터 없음
{"status": "error",   "reason": str}   # 예외 발생
```

---

## 캐시 경로 정리

| 파일 | 위치 |
|------|------|
| `{stem}_captions.json` | `extracted_DB/Movie/` |
| `{stem}_stt.txt` | `extracted_DB/Movie/` |
| `{stem}_blip_chunks.json` | `extracted_DB/Movie/` |
| `{stem}_stt_chunks.json` | `extracted_DB/Movie/` |
| `{stem}_blip_embs.npy` | `embedded_DB/Movie/` |
| `{stem}_stt_embs.npy` | `embedded_DB/Movie/` |
| `weight_buckets.json` | `extracted_DB/Movie/` |

`stem = {파일명}_{md5(file_path)[:12]}`

---

## ChromaDB metadata 필드 (video)

```
file_path, file_name, file_type="video",
chunk_index, chunk_text (max 300자),
chunk_source ("blip"|"stt"), blip_weight, stt_weight
```

---

## 검색 시 쿼리 인코딩

```python
encode_query_e5(query)
# 내부: "query: {query}" 접두사 → e5-large → 1024d
```

검색은 `search_video_m11()` (vector_store.py) 사용 — embedder가 직접 호출하지 않음.

---

## 금지 사항

- `progress_cb` 없이 video embedder 단독 호출 시 콜백 생략 허용 (None 전달)
- BLIP/STT/e5 모델 임의 교체 금지
- 캐시 경로 변경 금지 (extracted_DB/embedded_DB 분리 유지)
- `"passage: "` 접두사 생략 금지

---

## 목표

동영상을 시각(BLIP)과 음성(STT) 두 채널로 분석하여
고품질 1024d 벡터를 생성하고 안정적으로 ChromaDB에 저장한다.
