# Security Agent Rebuild Guide (Disaster Recovery)

이 문서는 `secure_rag`의 보안 에이전트 기능이 일부/전체 유실되었을 때, **이 문서만 보고 동일 기능을 재구현**할 수 있도록 작성된 복구 기준서다.

---

## 1) 복구 목표

재구현 시 반드시 아래를 충족해야 한다.

1. 업로드 파일(`PDF/HWPX/이미지`)에서 텍스트 추출
2. 청킹 후 한국형 PII 탐지
3. 브레이크 모달로 사용자 선택(마스킹/제외/원문/취소)
4. 선택 결과에 따라 벡터 DB 저장
5. 질의 시 Qwen으로 `NORMAL/SENSITIVE/DANGEROUS` 분류
6. 정책 분기(`allow/confirm/block`)
7. 감사 로그(SQLite) 기록
8. ABC 보안 원칙 강제

---

## 2) 핵심 보안 원칙 (ABC)

한 에이전트가 아래 3개를 동시에 가지면 안 된다.

- A: 비신뢰 입력 처리
- B: 민감 데이터 접근
- C: 외부 통신/상태 변경

### 현재 역할 분리

- `UploadSecurityAgent`: A만
- `RetrievalAgent`: B만
- `ResponseAgent`: C만
- `Orchestrator`: 흐름 제어만 (실권한 위임)

### 강제 코드

`harness/safe_tools.py`의 `enforce_abc(agent_name, capabilities)`에서
`{A,B,C}` 동시 포함 시 `RuntimeError` 발생.

---

## 3) 파일별 책임 (복구 우선순위)

아래 순서대로 복구하면 의존성 충돌이 적다.

1. `config.py`
2. `harness/safe_tools.py`
3. `document/*.py`
4. `security/*.py`
5. `vectordb/store.py`
6. `audit/logger.py`
7. `agents/*.py`
8. `ui/gradio_app.py`
9. `main.py`, `README.md`, `requirements.txt`

---

## 4) 설정값 복구 (`config.py`)

필수 키:

- 경로
  - `BASE_DIR`
  - `DATA_DIR`
  - `VECTOR_DIR`
  - `AUDIT_DB`
- 모델
  - `EMBEDDING_MODEL` (기본: `snunlp/KR-SBERT-V40K-klueNLI-augSTS`)
  - `QWEN_MODEL` (기본: `qwen2.5:7b`)
  - `OLLAMA_URL` (기본: `http://localhost:11434`)
- 파이프라인
  - `CHUNK_SIZE`, `CHUNK_OVERLAP`, `TOP_K`
- 보안
  - `ABC_ENFORCEMENT=True`

주의:
- 디렉토리는 모듈 로드시 `mkdir`로 자동 생성되게 유지.

---

## 5) 업로드 보안 하네스 복구 (`harness/safe_tools.py`)

### 필수 기능

1. 확장자 화이트리스트
   - 허용: `.pdf`, `.hwpx`, `.png`, `.jpg`, `.jpeg`
2. 파일 크기 제한 (100MB)
3. 금지 경로 차단 (`/etc`, `/proc`, `/sys` 등)
4. `top_k` 검색 상한(50)
5. 외부 HTTP 차단 (localhost만 허용)
6. OS 명령 실행 차단 함수

### 필수 상수

- `CAP_A`, `CAP_B`, `CAP_C`
- `ALLOWED_EXTENSIONS`
- `ALLOWED_HOSTS={"localhost","127.0.0.1"}`

---

## 6) 문서 추출 레이어 복구 (`document/`)

### 6.1 PDF (`pdf_extractor.py`)

순서:
1. PyMuPDF(`fitz`) 텍스트 추출
2. 평균 텍스트 길이 낮으면 EasyOCR 폴백

출력 형식:
- `List[Tuple[int, str]]` (page_num, text)

### 6.2 HWPX (`hwpx_extractor.py`)

전략:
- HWPX = ZIP 내부 XML 파싱
- `Contents/section*.xml` 순회
- `hp:t`, `hp:para`, `cellTr/cellTd` 반영

출력 형식:
- `List[Tuple[int, str]]` (section_num, text)

### 6.3 이미지 OCR (`image_extractor.py`)

지원 확장자:
- `.png/.jpg/.jpeg`

전처리:
- 업스케일(작은 이미지)
- 대비 강화

OCR:
- EasyOCR `["ko","en"]`

출력:
- 항상 `[(1, text)]`

### 6.4 청킹 (`chunker.py`)

`Chunk` dataclass 필드:
- `index, text, source_page, start_char, end_char, doc_name`

함수:
- `chunk_pages(pages, doc_name, chunk_size, overlap)`
- `chunks_to_texts(chunks)`

---

## 7) PII 탐지 레이어 복구 (`security/`)

## 7.1 한국형 Recognizer (`korean_recognizers.py`)

필수 엔티티:
- `KR_RRN` 주민번호
- `KR_PASSPORT` 여권번호
- `KR_DRIVER_LICENSE` 운전면허
- `KR_BANK_ACCOUNT` 계좌번호
- `KR_BRN` 사업자등록번호

핵심 구현 포인트:
- 정규식 + 체크섬 검증(주민번호, 사업자번호)
- **모든 Recognizer에 `supported_language="ko"` 필수**
  - 이 값 누락 시 `language='ko'` 분석에서 매칭 0건 발생 가능

내보내기:
- `ALL_KOREAN_RECOGNIZERS`

## 7.2 PII Detector (`pii_detector.py`)

### 데이터 구조

- `PIIFinding`
  - `entity_type, text, start, end, score, chunk_index, validated_by_llm`
- `ChunkScanResult`
  - `chunk_index, text, findings`
  - `has_pii`, `pii_types` property

### 엔진 구성

- `AnalyzerEngine` 생성
- `ALL_KOREAN_RECOGNIZERS` registry 등록
- `scan_chunks(chunks, language='ko')`

### 2차 검증

- score 낮은 건 Qwen으로 재검증 (`ask_pii_verification`)
- Qwen이 아니라고 하면 제외

### 마스킹

- `mask_text(text, findings)`
- 역순 치환으로 오프셋 깨짐 방지

## 7.3 Qwen 분류기 (`qwen_classifier.py`)

필수 메서드:

- `classify_query(user_query, feature_map) -> ClassificationResult`
- `ask_pii_verification(candidate_text, entity_type, context) -> bool`
- `is_available() -> bool`

출력 JSON 스키마:

```json
{
  "label": "NORMAL | SENSITIVE | DANGEROUS",
  "reason": "판단 이유",
  "action": "allow | confirm | block"
}
```

중요:
- 보안 분류에는 원문 chunk를 넘기지 않고 **feature_map만** 전달

## 7.4 정책 (`policy.py`)

### Query 정책

- NORMAL: allow
- SENSITIVE: masked preview + confirm
- DANGEROUS: block

### Upload 정책

선택값:
- `mask_and_embed`
- `skip_pii_chunks`
- `embed_all`
- `cancel`

`resolve(choice)`가 `proceed/mask/exclude_pii_chunks` 반환.

---

## 8) 저장소/로그 레이어 복구

## 8.1 Vector DB (`vectordb/store.py`)

구성:
- FAISS `IndexFlatL2`
- SQLite `meta.db`

필수 기능:
- `embed_texts()`
- `add_chunks(chunks, masked_indices)`
- `search(query, top_k)`
- `build_feature_map(results, user_query)`

Feature Map 최소 필드:
- `matched_docs`
- `contains_pii`
- `pii_types`
- `bulk_request`
- `owner_match`
- `sensitivity_score`

## 8.2 감사 로그 (`audit/logger.py`)

DB:
- `upload_events`
- `query_events`

필수 기록:
- 업로드 시간/파일/PII 유형/선택
- 질문/label/action/blocked/retrieved_ids/full_view_requested

---

## 9) 에이전트 레이어 복구 (`agents/`)

## 9.1 `UploadSecurityAgent`

흐름:
1. `validate_upload_file()`
2. 확장자별 추출기 호출
3. 청킹
4. PII 스캔
5. 요약(`affected_chunks`, `pii_type_counts`) 생성

반환:
- `UploadScanResult`

## 9.2 `RetrievalAgent`

역할:
- `safe_vector_search()`로 검색
- `feature_map` 생성 후 반환

## 9.3 `ResponseAgent`

역할:
- 허용된 chunk로만 답변 생성
- `generate()`, `generate_masked_preview()`

오류 처리:
- Ollama 연결 실패 시 사용자에게 안내 문구 반환

## 9.4 `Orchestrator`

### 업로드 단계

- `handle_upload(file_path)` -> 스캔만 수행
- `commit_upload(scan_result, user_choice)` -> 실제 저장
  - 마스킹/제외/원문/취소 처리
  - 감사 로그 기록

### 질의 단계

1. Retrieval (`chunks`, `feature_map`)
2. Qwen 분류 (`label/action/reason`)
3. Policy evaluate
4. 차단/마스킹 프리뷰/일반응답 분기
5. 감사 로그 기록

---

## 10) UI 복구 (`ui/gradio_app.py`)

탭 3개:

1. 파일 업로드
   - 허용 타입: `.pdf/.hwpx/.png/.jpg/.jpeg`
   - 스캔 버튼
   - 브레이크 모달 라디오 + 커밋
2. 질문/답변
   - 질문 입력
   - 전체보기 체크
3. 감사 로그
   - 업로드/질문 테이블

주의:
- 감사로그의 `차단` 컬럼은 `blocked=False`일 때 `✅`, `True`일 때 `⛔`.

---

## 11) 실행/설치 복구

## 11.1 requirements 최소셋

- `gradio`
- `pymupdf`
- `pdfminer.six`
- `Pillow`
- `easyocr`
- `lxml`
- `presidio-analyzer`
- `presidio-anonymizer`
- `spacy`
- `faiss-cpu`
- `sentence-transformers`
- `httpx`
- `python-dotenv`

## 11.2 Qwen/Ollama

```bash
ollama pull qwen2.5:7b
ollama serve
curl http://localhost:11434/api/tags
```

연결 실패 대표 원인:
- `ollama` 미설치
- 서버 미실행
- 포트 충돌

---

## 12) 회귀 테스트 체크리스트 (복구 후 필수)

### 업로드 스캔

1. `pii_profile.pdf` 업로드 시 `has_pii=True`
2. `pii_profile.hwpx` 업로드 시 `has_pii=True`
3. 이미지(`png/jpg`) 업로드 시 OCR 경유 후 탐지

### 정책 분기

1. NORMAL 질문 -> 즉시 답변
2. SENSITIVE 질문 -> 마스킹 프리뷰
3. DANGEROUS 질문 -> 차단 메시지

### 감사 로그

1. `upload_events` row 증가
2. `query_events` row 증가
3. blocked 값이 정책과 일치

### ABC 원칙

`enforce_abc("Test", {A,B,C})` 실행 시 예외 발생해야 정상.

---

## 13) 자주 발생한 장애와 원인

1. **PII 0건**
   - 원인: Recognizer에 `supported_language="ko"` 누락
2. **답변 생성 실패**
   - 원인: Ollama 미실행/미설치 (`Connection refused`)
3. **SENSITIVE인데 차단 칼럼 ✅**
   - 의미: 차단 아님(허용/확인 흐름 정상)
4. **계좌번호 과탐지**
   - 원인: 패턴이 넓어 BRN과 충돌 가능

---

## 14) 빠른 재구현 절차 (1시간 복구 플랜)

1. 디렉토리/`__init__.py` 생성
2. `config.py`, `safe_tools.py` 작성
3. `document` 4개 작성 (`pdf/hwpx/image/chunker`)
4. `security` 4개 작성
5. `store.py`, `logger.py` 작성
6. `agents` 4개 작성
7. `gradio_app.py`, `main.py`, `README.md`
8. 더미 데이터 생성 후 업로드/질의 E2E 테스트

---

## 15) 완료 판정 기준

아래 5개를 만족하면 복구 성공:

1. PDF/HWPX/PNG 업로드 모두 스캔 가능
2. PII 탐지 결과가 감사 로그에 반영
3. 업로드 선택지(마스킹/제외/원문/취소) 동작
4. Qwen 분류 + 정책 분기 정상
5. ABC 위반 시 런타임 차단

---

## 16) 운영 메모

- 본 프로젝트는 MVP 단일 사용자 기준이다.
- 기업용 멀티테넌시/고급 암호화/DP/Poisoning 방어는 범위 외.
- 기능 유실 시 이 문서의 순서대로 복구하고, 마지막에 회귀 테스트를 반드시 수행한다.

