# Retrieval Spec

## 검색 기본

- 임베딩 유사도 기반 top-k 검색 (ChromaDB)
- 유형별(doc / video / image / audio) 검색기 독립 운영
- 결과는 similarity 내림차순 정렬
- 유형당 기본 top_k = 10

---

## 모듈화 규칙

- 각 유형 검색기는 `routes/search.py`의 `SEARCHERS` 딕셔너리에 등록
- 검색기 미연결 시 `available: false` 반환 — 오류 아님
- 검색기는 `(query: str, top_k: int) → list[SearchResult] | None` 시그니처를 따른다
  - `None` 반환 = 검색기 없음
  - `list` 반환 = 검색 결과 (비어있어도 가능)

---

## 검색 결과 구조

SearchResult 구조는 DataContract.md 참고

필수 포함 필드: `file_id`, `file_name`, `similarity`, `snippet`

---

## 파일 열기 규칙

- ChromaDB metadata에 `file_path`, `folder_path` 반드시 저장
- `file_path`가 없으면 파일 열기 / 폴더 열기 불가
- 백엔드가 `os.startfile` / `subprocess explorer` 로 OS에 위임
