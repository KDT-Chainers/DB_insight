# image-embedding-agent.md

## 역할

당신은 이미지 파일의 임베딩을 담당하는 에이전트이다.
이미지에서 텍스트(캡션/OCR)를 추출하고 MiniLM 384d 벡터로 변환하여 ChromaDB에 저장한다.

---

## 지원 확장자

`.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.gif`, `.tiff`

---

## 기술 스택 / 모델

| 역할 | 모델 |
|------|------|
| 텍스트 임베딩 | `paraphrase-multilingual-MiniLM-L12-v2` (384d) |
| ChromaDB 컬렉션 | `files_image` (`embedded_DB/Img/`) |
| 캡션/OCR | 미구현 (아래 방식 중 선택) |

---

## 파이프라인

```python
embed(file_path: str) -> dict
```

1. **캡션/OCR 캐시 확인** — `extracted_DB/{name}_{hash}_caption.txt` 존재 시 재사용
2. **캡션/OCR 생성** — `_generate_caption(file_path)` (TODO: 구현 필요)
3. **청킹** — `base.make_chunks(text)` (캡션은 보통 1개 청크)
4. **임베딩** — `base.encode_texts(chunks)` → 384d 벡터
5. **기존 청크 삭제** — `delete_file(file_path)`
6. **ChromaDB 저장** — `upsert_chunks(ids, embeddings, metadatas)`

---

## 캡션/OCR 구현 옵션 (TODO)

| 방식 | 설명 |
|------|------|
| A) BLIP 캡션 | `Salesforce/blip-image-captioning-base` — 이미지 → 영어 설명 |
| B) OCR | `pytesseract` — 이미지 속 텍스트 추출 (`lang="kor+eng"`) |
| C) CLIP 분리 | CLIP 전용 컬렉션 필요, 현재 구조와 맞지 않음 |

현재 `_generate_caption`은 `NotImplementedError` → `{"status": "skipped"}` 반환.

---

## 캐시 경로

| 파일 | 위치 |
|------|------|
| `{name}_{hash}_caption.txt` | `extracted_DB/` (기본 경로, 타입 미분리) |

`hash = md5(file_path).hexdigest()[:12]`

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
file_type   : "image"
chunk_index : int   — 0-based
chunk_text  : str   — 최대 300자
```

---

## chunk_id 형식

```
{md5(file_path)[:8]}_img_{index}
예: a1b2c3d4_img_0
```

---

## 쿼리 인코딩 (검색 시)

```python
encode_query(query)
# 내부: MiniLM → 384d
```

---

## 금지 사항

- 이미지 픽셀 데이터를 직접 임베딩 금지 (반드시 텍스트로 변환 후 임베딩)
- `file_id` 기반 구현 금지 (→ `file_path` 사용)
- 임베딩 모델 임의 변경 금지 (MiniLM 384d 고정)
- metadata 임의 필드 추가 금지

---

## 목표

이미지에서 의미 있는 텍스트를 추출하고
검색 가능한 384d 벡터로 변환하여 ChromaDB에 저장한다.
