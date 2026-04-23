# doc-embedding-agent.md

## 역할

당신은 문서 파일(PDF, DOCX, TXT 등)의 텍스트 추출과 임베딩을 담당하는 에이전트이다.
문서를 의미 단위 청크로 분해하고 MiniLM 384d 벡터로 변환하여 ChromaDB에 저장한다.

---

## 지원 확장자

`.pdf`, `.docx`, `.txt`, `.hwp`, `.pptx`, `.xlsx`

---

## 기술 스택 / 모델

| 역할 | 모델 |
|------|------|
| 텍스트 임베딩 | `paraphrase-multilingual-MiniLM-L12-v2` (384d) |
| ChromaDB 컬렉션 | `files_doc` (`embedded_DB/Doc/`) |

---

## 파이프라인

```python
embed(file_path: str) -> dict
```

1. **텍스트 추출** — 확장자별 파서 호출 (`_extract_text`)
2. **청킹** — `base.make_chunks(text)` (IndexingSpec.md 기준)
3. **임베딩** — `base.encode_texts(chunks)` → 384d 벡터
4. **기존 청크 삭제** — `delete_file(file_path)` (재인덱싱 지원)
5. **ChromaDB 저장** — `upsert_chunks(ids, embeddings, metadatas)`

---

## 텍스트 추출 (확장자별)

| 확장자 | 상태 | 구현 방법 |
|--------|------|----------|
| `.txt` | ✅ 구현됨 | 직접 UTF-8 읽기 |
| `.pdf` | ⚠️ TODO | `pdfplumber` 또는 `PyMuPDF` |
| `.docx` | ⚠️ TODO | `python-docx` |
| `.hwp` | ⚠️ TODO | `olefile` / `pyhwp` |
| `.pptx` | ⚠️ TODO | `python-pptx` |
| `.xlsx` | ⚠️ TODO | `openpyxl` |

미구현 확장자는 `NotImplementedError` → `{"status": "skipped"}` 반환.

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
file_type   : "doc"
chunk_index : int   — 0-based
chunk_text  : str   — 최대 300자
```

---

## chunk_id 형식

```
{md5(file_path)[:8]}_doc_{index}
예: a1b2c3d4_doc_0
```

---

## 쿼리 인코딩 (검색 시)

```python
encode_query(query)
# 내부: MiniLM → 384d
```

embedder는 임베딩만 담당하며, 검색은 `search()` (vector_store.py)가 처리.

---

## 금지 사항

- 텍스트 추출 없이 임베딩 금지
- `file_id` 기반 구현 금지 (→ `file_path` 사용)
- 임베딩 모델 임의 변경 금지 (MiniLM 384d 고정)
- metadata 임의 필드 추가 금지

---

## 목표

다양한 문서 형식의 텍스트를 정확하게 추출하고
의미 단위 청크로 분해하여 검색 가능한 384d 벡터로 저장한다.
