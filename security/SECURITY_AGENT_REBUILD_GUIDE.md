# Security Agent Rebuild Guide (Disaster Recovery)

이 문서는 `security/` 보안 에이전트 기능이 일부/전체 유실되었을 때, **이 문서만 보고 동일 기능을 재구현**할 수 있도록 작성된 복구 기준서다.

---

## 1) 복구 목표

재구현 시 반드시 아래를 충족해야 한다.

1. 업로드 파일(`PDF/HWPX/PNG/JPG/JPEG/HEIC/WEBP`)에서 텍스트 추출
2. 이미지: EasyOCR `detail=1`로 텍스트 + bbox 좌표 동시 추출
3. 이미지 파일 `secure_store/images/`에 SHA-256 기반 영구 복사
4. 청킹 후 한국형 PII 탐지 (6종 + 체크섬)
5. PII 없으면 자동 임베딩, PII 있으면 처리 방식 선택 모달 표시
6. **원문 그대로** FAISS에 임베딩 저장 (마스킹 저장 금지)
7. PII 메타데이터(has_pii, pii_types, display_masked, pii_regions)만 SQLite 태그
8. 검색: `IndexFlatIP` + 정규화 벡터 = 코사인 유사도 (0~1)
9. 질의 시 Qwen으로 `NORMAL/SENSITIVE/DANGEROUS` 분류
10. 정책 분기(`allow/confirm/block`) + GroundingGate 통과 여부 확인
11. 검색 결과 카드: 텍스트는 마스킹 렌더링, 이미지는 bbox 모자이크
12. 감사 로그(SQLite) 기록
13. ABC 보안 원칙 강제

---

## 2) 핵심 보안 원칙 (ABC)

한 에이전트가 아래 3개를 동시에 가지면 안 된다.

- A: 비신뢰 입력 처리
- B: 민감 데이터 접근
- C: 외부 통신/상태 변경

### 현재 역할 분리

- `UploadSecurityAgent`: A만
- `RetrievalAgent`: B만
- `Orchestrator`: 흐름 제어만 (실권한 위임)
- `QwenClassifier`: A + C(Ollama만)

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
8. `ui/components/*.py`
9. `ui/gradio_app.py`
10. `main.py`, `README.md`, `requirements.txt`

---

## 4) 설정값 복구 (`config.py`)

필수 키:

- 경로
  - `BASE_DIR`, `DATA_DIR`, `VECTOR_DIR`, `AUDIT_DB`
  - `SECURE_STORE_DIR = BASE_DIR / "secure_store"`
  - `IMAGE_STORE_DIR = SECURE_STORE_DIR / "images"`  ← 이미지 영구 보관
- 모델
  - `EMBEDDING_MODEL` (기본: `snunlp/KR-SBERT-V40K-klueNLI-augSTS`)
  - `QWEN_MODEL` (기본: `qwen2.5:7b`)
  - `OLLAMA_URL` (기본: `http://localhost:11434`)
- 파이프라인
  - `CHUNK_SIZE=500`, `CHUNK_OVERLAP=50`, `TOP_K=5`
- 보안
  - `ABC_ENFORCEMENT=True`
  - `GROUNDING_SIM_THRESHOLD=0.15`  ← NORMAL 쿼리 최소 관련도
  - `QUERY_REWRITE_ENABLED=True`
  - `QUERY_REWRITE_MAX_CHARS=160`

주의: 모든 디렉토리는 `mkdir(parents=True, exist_ok=True)`로 자동 생성.

---

## 5) 업로드 보안 하네스 복구 (`harness/safe_tools.py`)

### 필수 기능

1. 확장자 화이트리스트
   - **허용: `.pdf`, `.hwpx`, `.png`, `.jpg`, `.jpeg`, `.heic`, `.webp`**
2. 파일 크기 제한 (100MB)
3. 금지 경로 차단 (`/etc`, `/proc`, `/sys` 등)
4. `top_k` 검색 상한 (50)
5. 외부 HTTP 차단 (localhost만 허용)
6. OS 명령 실행 차단

### 필수 상수

- `CAP_A`, `CAP_B`, `CAP_C`
- `ALLOWED_EXTENSIONS = {".pdf", ".hwpx", ".png", ".jpg", ".jpeg", ".heic", ".webp"}`
- `ALLOWED_HOSTS = {"localhost", "127.0.0.1"}`

---

## 6) 문서 추출 레이어 복구 (`document/`)

### 6.1 PDF (`pdf_extractor.py`)

순서:
1. PyMuPDF(`fitz`) 텍스트 추출
2. 평균 텍스트 길이 낮으면 EasyOCR 폴백

출력: `List[Dict]` with `{page_number, text, bbox, source_path}`

### 6.2 HWPX (`hwpx_extractor.py`)

전략:
- HWPX = ZIP 내부 XML 파싱
- `Contents/section*.xml` 순회

출력: `List[Dict]` with `{page_number, text, bbox=None, source_path}`

### 6.3 이미지 OCR (`image_extractor.py`) ← v2 변경

지원 확장자: `.png/.jpg/.jpeg/.heic/.webp`

전처리:
- HEIC: `pillow_heif.register_heif_opener()` 등록
- 업스케일 (최소 1200px)
- 대비 강화 (2.5)
- **그레이스케일 변환** (빨간 도장 등 색상 간섭 제거)

OCR:
- EasyOCR `["en", "ko"]`, `detail=1`, `paragraph=False`
- `detail=1` → `[(bbox, text, conf), ...]` 형식으로 bbox 좌표 포함

공개 함수:
- `extract_image_with_regions(path)` → `{text, ocr_results, source_path, page_number}`
- `extract_image(path)` → `[(1, text)]` (하위 호환 래퍼)
- `map_pii_to_image_regions(ocr_results, pii_findings)` → `List[bbox]`

이미지 영구 저장:
- `UploadSecurityAgent._persist_image(src)`: SHA-256 해시로 중복 제거 후 `IMAGE_STORE_DIR`에 복사

### 6.4 청킹 (`chunker.py`)

`Chunk` dataclass 필드:
- `index, text, source_page, start_char, end_char, doc_name, source_path, bbox`

함수:
- `chunk_pages(pages, doc_name, source_path, chunk_size, overlap)`
- `chunks_to_texts(chunks)`

---

## 7) PII 탐지 레이어 복구 (`security/`)

### 7.1 한국형 Recognizer (`korean_recognizers.py`)

필수 엔티티 6종:

| 엔티티 | 패턴 | 검증 |
|--------|------|------|
| `KR_RRN` | `\d{6}-[1-4]\d{6}` | 13자리 체크섬 |
| `KR_PASSPORT` | `[A-Z][0-9]{8}` | 없음 |
| `KR_DRIVER_LICENSE` | `\d{2}-\d{2}-\d{6}-\d{2}` | 없음 |
| `KR_BANK_ACCOUNT` | `\d{3,4}-\d{2,6}-\d{4,7}(-\d{1,3})?` | 문맥(통장/계좌) |
| `KR_BRN` | `\d{3}-\d{2}-\d{5}` | 10자리 체크섬 |
| `KR_PHONE` | `01[0-9]-\d{3,4}-\d{4}` 외 3종 | 없음 |

핵심:
- **모든 Recognizer에 `supported_language="ko"` 필수** (누락 시 탐지 0건)
- `ALL_KOREAN_RECOGNIZERS` 리스트로 내보내기

`KR_PHONE` 패턴:
```python
# 휴대폰: 010/011/016 등
r"\b01[0-9]-\d{3,4}-\d{4}\b"
# 서울: 02
r"\b02-\d{3,4}-\d{4}\b"
# 지역: 031~099
r"\b0[3-9]\d-\d{3,4}-\d{4}\b"
# 대표: 1588/1544 등
r"\b1[5-9]\d{2}-\d{4}\b"
```

### 7.2 PII Detector (`pii_detector.py`)

데이터 구조:
- `PIIFinding`: `entity_type, text, start, end, score, chunk_index`
- `ChunkScanResult`: `chunk_index, text, findings` → `has_pii`, `pii_types` property

DEFAULT_ENTITIES:
```python
["PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD", "IBAN_CODE",
 "KR_RRN", "KR_PASSPORT", "KR_DRIVER_LICENSE",
 "KR_BANK_ACCOUNT", "KR_BRN", "KR_PHONE"]
```

2차 검증: score < 0.5이면 Qwen `ask_pii_verification()` 호출

### 7.3 Qwen 분류기 (`qwen_classifier.py`)

필수 메서드:
- `classify_query(user_query, feature_map)` → `ClassificationResult`
- `rewrite_query(user_query, max_chars)` → `str` (쿼리 재작성)
- `ask_pii_verification(candidate_text, entity_type, context)` → `bool`
- `is_available()` → `bool`

출력 JSON 스키마:
```json
{
  "label": "NORMAL | SENSITIVE | DANGEROUS",
  "reason": "판단 이유 (한국어만)",
  "action": "allow | confirm | block"
}
```

중요:
- `reason`은 **한국어만** 출력 (일본어/영어 문장 방지)
- `_normalize_reason_korean()` 후처리로 비한국어 reason 자동 교체
- 보안 분류에는 원문 chunk를 넘기지 않고 **feature_map만** 전달

### 7.4 정책 (`policy.py`)

Query 정책:
- NORMAL: allow
- SENSITIVE: confirm (마스킹 미리보기)
- DANGEROUS: block

Upload 정책 선택값:
- `mask_and_embed` → `display_masked=True`, 원문 저장
- `embed_all` → `display_masked=False`, 원문 저장
- `cancel` → 저장 안 함

`resolve(choice)`가 `{proceed, mask, exclude_pii_chunks}` 반환.

### 7.5 GroundingGate (`security/grounding_gate.py`)

역할: 검색 결과가 질문과 실질적으로 연결되는지 코사인 유사도로 확인.

로직:
```python
if label == "SENSITIVE":
    return True  # 무조건 통과

sim = cosine_similarity(user_query, context)
threshold = max(GROUNDING_SIM_THRESHOLD - discount, 0.05)
return sim >= threshold
```

키워드별 임계값 할인:
- 여권 관련: -0.10
- 주민번호/신분증 관련: -0.08
- 계좌/사업자 관련: -0.06

---

## 8) 저장소/로그 레이어 복구

### 8.1 Vector DB (`vectordb/store.py`) ← v2 대규모 변경

#### FAISS 인덱스: `IndexFlatIP` + 정규화 벡터

```python
# 임베딩 시 normalize_embeddings=True 필수
embeddings = model.encode(texts, normalize_embeddings=True)

# 인덱스 생성
self._index = faiss.IndexFlatIP(dim)  # L2 아님!
```

이유: SBERT는 코사인 유사도 기반 학습 → `IndexFlatL2` 사용 시 랭킹 오류 발생

#### SQLite 스키마 (`chunks` 테이블)

```sql
CREATE TABLE chunks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_name          TEXT,
    source_page       INTEGER,
    chunk_index       INTEGER,
    start_char        INTEGER,
    end_char          INTEGER,
    text              TEXT,           -- 원문 (마스킹 저장 금지)
    source_path       TEXT,
    file_name         TEXT,
    bbox              TEXT,
    has_pii           INTEGER,        -- 0 or 1
    pii_types         TEXT,           -- JSON array
    sensitivity_score REAL,
    display_masked    INTEGER,        -- UI 마스킹 여부
    is_image          INTEGER,        -- 이미지 파일 여부
    image_path        TEXT,           -- 영구 이미지 경로
    pii_regions       TEXT            -- JSON array of bbox [[x1,y1],...] 목록
)
```

#### 임베딩 텍스트 보강

원문은 DB에 저장, 임베딩에는 prefix 추가:
```
[파일: 여권.jpg] [문서유형: 여권 여권번호 passport]
<원문 텍스트>
```
→ 파일명이 의미없어도 PII 유형으로 검색 가능

#### 인덱스 버전 관리

- `_index_version.txt` 파일로 버전 추적
- 버전 불일치 시 기존 faiss.index 자동 삭제 (재임베딩 필요)

#### numpy 직렬화 주의

EasyOCR bbox는 `numpy.int32` → `json.dumps` 실패  
→ `_to_python(obj)` 헬퍼로 모든 numpy 타입을 순수 파이썬으로 변환 후 저장

### 8.2 감사 로그 (`audit/logger.py`)

테이블:
- `upload_events`: 시간/파일/PII유형/선택
- `query_events`: 시간/질문/label/action/blocked/retrieved_ids

---

## 9) 에이전트 레이어 복구 (`agents/`)

### 9.1 `UploadSecurityAgent`

흐름:
1. `validate_upload_file()` (확장자/크기 검증)
2. 확장자별 추출기 호출
3. 이미지면: `extract_image_with_regions()` → OCR + bbox
4. 이미지면: `_persist_image()` → `IMAGE_STORE_DIR`에 영구 복사
5. 청킹
6. PII 스캔
7. 이미지면: `map_pii_to_image_regions()` → PII bbox 목록 계산

반환: `UploadScanResult`
```python
@dataclass
class UploadScanResult:
    filename: str
    chunks: List[Chunk]
    scan_results: List[ChunkScanResult]
    has_pii: bool
    pii_summary: Dict
    error: Optional[str]
    is_image: bool = False
    image_path: str = ""
    image_pii_regions: List[List] = field(default_factory=list)
```

### 9.2 `RetrievalAgent`

역할:
- `safe_vector_search()`로 검색
- `feature_map` 생성 후 반환 (원문 미포함)

### 9.3 `Orchestrator`

업로드 단계:
- `handle_upload(file_path)` → 스캔만 수행
- `commit_upload(scan_result, user_choice)` → 실제 저장
  - `pii_metadata`에 `is_image`, `image_path`, `pii_regions` 포함

질의 단계:
1. Query Rewrite (Qwen)
2. Retrieval (chunks, feature_map)
3. Qwen 분류 (label/action/reason)
4. Policy evaluate
5. DANGEROUS면: 파일명/경로만 포함한 path_only_chunks 반환 (`_blocked=True`)
6. GroundingGate 확인
7. 감사 로그 기록

중요: **LLM 답변 생성 없음.** 검색 소스 카드만 반환.

---

## 10) UI 복구 (`ui/`)

### 10.1 `ui/components/result_card.py`

카드 렌더링 로직:
```
is_image=True → _render_image_preview() 호출
  → PIL로 이미지 로드
  → display_masked=True면 pii_regions에 모자이크 적용
  → base64 <img> 태그 반환

is_image=False → render_masked_text() 호출
  → display_masked=True면 PII 패턴 마스킹
  → ●●● 표시

_blocked=True → 차단 카드 (파일명/경로만 표시)
```

점수 표시: `"관련도 {score*100:.1f}%"` (코사인 유사도 %)

### 10.2 `ui/gradio_app.py`

탭 3개 (다크모드):

1. **파일 업로드**
   - 허용 타입: `.pdf/.hwpx/.png/.jpg/.jpeg/.heic/.webp`
   - `[임베딩 시작]` 버튼 클릭 → `on_file_change()` 실행
   - PII 없으면 자동 임베딩, PII 있으면 모달 표시
   - 모달 안에 처리 방식 라디오 + `[✅ 확인]` 버튼 함께 배치 (visibility 동기화)
   - `yield`로 실시간 진행 상태 표시

2. **질문 & 답변** (검색하기)
   - 질문 입력 + 전체보기 체크박스
   - 결과: 보안 레이블, 정책 정보, 소스 카드 HTML

3. **감사 로그**
   - 업로드/질의 테이블 (blocked: `✅`=정상, `⛔`=차단)

주의:
- `commit_btn`은 반드시 `modal_group` **안에** 배치할 것
  - 바깥에 두면 generator yield 타이밍에 따라 버튼 사라짐 버그 발생

---

## 11) 실행/설치 복구

### requirements 최소셋

```
gradio>=4.0.0
pymupdf>=1.23.0
pdfminer.six>=20221105
Pillow>=10.0.0
pillow-heif>=0.16.0     ← HEIC 지원 필수
easyocr>=1.7.0
lxml>=5.0.0
presidio-analyzer>=2.2.0
presidio-anonymizer>=2.2.0
spacy>=3.7.0
faiss-cpu>=1.7.4
sentence-transformers>=2.7.0
httpx>=0.27.0
python-dotenv>=1.0.0
numpy
```

### Qwen/Ollama

```bash
ollama pull qwen2.5:7b
ollama serve
curl http://localhost:11434/api/tags
```

---

## 12) 회귀 테스트 체크리스트

### 업로드 스캔

- [ ] `pii_profile.pdf` → `has_pii=True`
- [ ] 이미지(png/jpg/heic) 업로드 → OCR 후 PII 탐지
- [ ] 빨간 도장 있는 통장 사본 → `KR_BANK_ACCOUNT` 탐지
- [ ] 전화번호 포함 문서 → `KR_PHONE` 탐지
- [ ] PII 없는 파일 → 자동 임베딩 (모달 없음)

### 이미지 렌더링

- [ ] 이미지 검색 시 카드에 이미지 표시
- [ ] `display_masked=True`면 PII 영역 모자이크 처리
- [ ] 이미지 경로가 `secure_store/images/`에 영구 저장

### 검색 정확도

- [ ] "계좌번호 알려줘" → 계좌 문서가 1위
- [ ] "여권 찾아줘" → 여권 이미지가 1위
- [ ] 관련도 점수가 0~100% 범위 내

### 정책 분기

- [ ] NORMAL 질문 → 소스 카드 표시
- [ ] SENSITIVE 질문 → 마스킹 카드 표시
- [ ] DANGEROUS 질문 → 파일명/경로만 표시, 내용 차단

### ABC 원칙

- [ ] `enforce_abc("Test", {A,B,C})` → RuntimeError 발생

---

## 13) 자주 발생한 장애와 원인

| 장애 | 원인 | 해결 |
|------|------|------|
| PII 0건 탐지 | Recognizer에 `supported_language="ko"` 누락 | 모든 Recognizer에 추가 |
| 유사도 점수 400대 | `IndexFlatL2` 사용 (L2 거리) | `IndexFlatIP` + 정규화로 전환 |
| 계좌 물어봤는데 여권이 1위 | L2 거리 기반 랭킹 오류 | 위와 동일 |
| 빨간 도장 이미지 OCR 실패 | 색상 채널 간섭 | 그레이스케일 변환 후 OCR |
| 전화번호 미감지 | Presidio 기본 PHONE_NUMBER가 한국 지역번호 미지원 | `KR_PHONE` 커스텀 추가 |
| 확인 버튼 사라짐 | `commit_btn`이 `modal_group` 바깥에 있어 visibility 미동기화 | 버튼을 modal_group 안으로 이동 |
| JSON 직렬화 오류 (int32) | EasyOCR bbox가 `numpy.int32` 반환 | `_to_python()` 헬퍼로 변환 |
| SENSITIVE인데 차단 칼럼 ✅ | 의미 오해: ✅=차단 아님(정상 허용/확인 흐름) | 감사 로그 `blocked=False` 정상 |
| Qwen reason 일본어 출력 | Qwen 모델이 간혹 일본어로 응답 | `_normalize_reason_korean()` 후처리 |

---

## 14) 빠른 재구현 절차 (1시간 복구 플랜)

1. 디렉토리/`__init__.py` 생성
2. `config.py`, `safe_tools.py` 작성 (IMAGE_STORE_DIR 포함)
3. `document` 4개 작성 (image_extractor는 `detail=1` + 그레이스케일 필수)
4. `security` 5개 작성 (KR_PHONE 포함)
5. `store.py` 작성 (IndexFlatIP + is_image/image_path/pii_regions 컬럼)
6. `logger.py` 작성
7. `agents` 3개 작성 (orchestrator: pii_regions 전달 경로 포함)
8. `ui/components/` 2개 작성 (이미지 모자이크 포함)
9. `gradio_app.py` 작성 (commit_btn modal 안에 배치)
10. `main.py`, `README.md`, `requirements.txt`
11. 더미 데이터 생성 후 E2E 테스트

---

## 15) 완료 판정 기준

아래를 모두 만족하면 복구 성공:

1. PDF/HWPX/PNG/HEIC/WEBP 업로드 모두 스캔 가능
2. 이미지 카드에 원본 이미지 + PII 모자이크 표시
3. 검색 관련도 점수 0~100% 범위 (코사인 유사도)
4. "계좌번호" 쿼리 → 계좌 문서가 1위 (여권 아님)
5. PII 탐지 결과가 감사 로그에 반영
6. Qwen 분류 + 정책 분기 정상
7. ABC 위반 시 런타임 차단

---

## 16) 운영 메모

- 본 프로젝트는 MVP 단일 사용자 기준이다.
- 기업용 멀티테넌시/고급 암호화/차분 프라이버시는 범위 외.
- FAISS 인덱스 버전 변경 시 기존 데이터 재임베딩 필요 (`_index_version.txt` 확인).
- 기능 유실 시 이 문서의 순서대로 복구하고, 마지막에 회귀 테스트를 반드시 수행한다.
