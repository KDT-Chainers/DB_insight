# audio-embedding-agent.md

## 역할

당신은 음성 파일의 임베딩을 담당하는 에이전트이다.
STT(Speech-to-Text)로 음성을 텍스트로 변환하고
ko-sroberta 768d 벡터로 임베딩하여 ChromaDB에 저장한다.

---

## 지원 확장자

`.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`

---

## 기술 스택 / 모델

| 역할 | 모델 |
|------|------|
| STT | `faster-whisper medium` 권장 (한국어) — 미구현, TODO |
| 텍스트 임베딩 | `jhgan/ko-sroberta-multitask` (768d) |
| ChromaDB 컬렉션 | `files_audio` (`embedded_DB/Rec/`) |

---

## 파이프라인

```python
embed(file_path: str) -> dict
```

1. **STT 캐시 확인** — `extracted_DB/{name}_{hash}_stt.txt` 존재 시 재사용
2. **STT 수행** — `_transcribe(file_path)` (TODO: 구현 필요)
3. **청킹** — `base.make_chunks(text)`
4. **임베딩** — `base.encode_texts(chunks)` → 768d 벡터
5. **기존 청크 삭제** — `delete_file(file_path)`
6. **ChromaDB 저장** — `upsert_chunks(ids, embeddings, metadatas)`

---

## STT 구현 옵션 (TODO)

| 방식 | 설명 |
|------|------|
| A) faster-whisper (권장) | GPU 추천, `WhisperModel("medium", device="cuda", compute_type="float16")` |
| B) openai-whisper | CPU 호환, `whisper.load_model("base")` |
| C) 외부 API | OpenAI / Clova 등 |

현재 `_transcribe`는 `NotImplementedError` → `{"status": "skipped"}` 반환.

---

## 캐시 경로

| 파일 | 위치 |
|------|------|
| `{name}_{hash}_stt.txt` | `extracted_DB/` (기본 경로, 타입 미분리) |

`hash = md5(file_path).hexdigest()[:12]`

STT 결과를 캐싱하여 재인덱싱 시 STT 재실행 방지.

---

## 반환값

```python
{"status": "done",    "chunks": int}
{"status": "skipped", "reason": str}   # 미구현 또는 텍스트 없음
{"status": "error",   "reason": str}   # 예외 발생
```

---

## ChromaDB metadata 필드

```
file_path   : str   — 파일 절대 경로
file_name   : str   — 파일명 (확장자 포함)
file_type   : "audio"
chunk_index : int   — 0-based
chunk_text  : str   — 최대 300자
```

---

## chunk_id 형식

```
{md5(file_path)[:8]}_aud_{index}
예: a1b2c3d4_aud_0
```

---

## 쿼리 인코딩 (검색 시)

```python
encode_query_ko(query)
# 내부: ko-sroberta → 768d
```

doc/image(MiniLM 384d)와 모델이 다르므로 혼용 금지.

---

## 금지 사항

- 음성 데이터를 직접 임베딩 금지 (반드시 STT → 텍스트 → 임베딩)
- `file_id` 기반 구현 금지 (→ `file_path` 사용)
- 임베딩 모델 임의 변경 금지 (ko-sroberta 768d 고정)
- doc/image용 MiniLM과 혼용 금지
- metadata 임의 필드 추가 금지

---

## 목표

음성 파일을 텍스트로 정확히 전사하고
한국어 특화 768d 벡터로 변환하여 ChromaDB에 저장한다.
