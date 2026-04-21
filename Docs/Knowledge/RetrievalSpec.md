# Retrieval Spec

## 검색 기본

- 임베딩 유사도 기반 top-k 검색 (ChromaDB)
- 유형별(doc / video / image / audio) 검색기 독립 운영
- 결과는 similarity 내림차순 정렬 (모든 타입 통합)
- 기본 top_k = 10

---

## 타입별 임베딩 모델

| 타입 | 임베딩 모델 | 차원 | 비고 |
|------|------------|------|------|
| doc   | `paraphrase-multilingual-MiniLM-L12-v2` | 384d | 다국어, 문서 텍스트 |
| image | `paraphrase-multilingual-MiniLM-L12-v2` | 384d | OCR 텍스트 임베딩 |
| audio | `jhgan/ko-sroberta-multitask`            | 768d | 한국어 특화, STT 텍스트 |
| video | `intfloat/multilingual-e5-large`         | 1024d | M11, "query: " 접두사 필수 |

쿼리 인코딩은 타입에 맞는 모델로 수행:
- doc/image → `encode_query(query)` (MiniLM 384d)
- audio → `encode_query_ko(query)` (ko-sroberta 768d)
- video → `encode_query_e5(query)` (e5-large 1024d, "query: " 접두사 자동 부가)

---

## 모듈화 규칙

- 각 타입 검색기는 `routes/search.py`의 `SEARCHERS` 로직에 통합
- 검색기는 `(query_vec: list[float], top_k: int) → list[SearchResult]` 시그니처를 따른다
- 해당 타입에 인덱싱된 청크가 없으면 결과에서 제외 (오류 아님)
- 전체 검색 시 타입별로 따로 인코딩 후 결과를 합산·정렬

---

## 검색 결과 구조

SearchResult 구조는 DataContract.md 참고.

필수 포함 필드: `file_path`, `file_name`, `file_type`, `similarity`, `snippet`

---

## 동영상(M11) 검색 상세

video 타입 검색은 M11 파이프라인을 사용한다.

1. 쿼리를 `"query: {query}"` 형태로 e5-large 임베딩 (1024d, L2 정규화)
2. ChromaDB에서 해당 파일의 BLIP 청크 / STT 청크를 조회
3. 청크별 cosine 유사도(내적) 계산 → max-pooling
   - blip_score = BLIP 청크 중 최대 유사도
   - stt_score  = STT 청크 중 최대 유사도
4. 최종 점수 = `blip_weight × blip_score + stt_weight × stt_score`
   - 동적 가중치: 영상별 프레임수/STT량 비율로 자동 배정 (9분위 버킷)
5. 결과 snippet은 유사도가 가장 높은 청크 텍스트

---

## 파일 열기 규칙

- ChromaDB metadata에 `file_path`, `folder_path` 반드시 저장
- `file_path`가 없으면 파일 열기 / 폴더 열기 불가
- 백엔드가 `os.startfile` / `subprocess explorer` 로 OS에 위임
- API: `POST /api/files/open`, `POST /api/files/open-folder`
