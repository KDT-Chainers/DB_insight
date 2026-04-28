# 🔐 로컬 보안 RAG 시스템

개인 문서(PDF / HWPX / 이미지)를 업로드하고, 보안 에이전트(Qwen)가 개인정보를 보호하면서 안전하게 검색할 수 있는 로컬 RAG 시스템입니다.

> 외부 API 미사용. 완전 로컬 처리 (Ollama + FAISS + EasyOCR)

---

## 아키텍처 개요

```
사용자
  │
  ▼
[Orchestrator]  ← 흐름 제어만 담당 (ABC 동시 소유 금지)
  │
  ├── [UploadSecurityAgent]  (권한 A: 신뢰불가 입력 처리)
  │     ├─ PDF / HWPX / 이미지(PNG/JPG/JPEG/HEIC/WEBP) 텍스트 추출
  │     ├─ 이미지: EasyOCR detail=1 → bbox 좌표 추출
  │     ├─ 이미지 영구 복사 (secure_store/images/)
  │     ├─ 청킹
  │     └─ PII 탐지 (Presidio + 한국형 Recognizer + Qwen 재검증)
  │
  ├── [RetrievalAgent]  (권한 B: VectorDB 접근)
  │     ├─ FAISS 코사인 유사도 검색 (IndexFlatIP)
  │     └─ Feature Map 생성 (원문 미포함)
  │
  ├── [QwenClassifier]  (Feature Map만 입력, DB 접근 없음)
  │     ├─ NORMAL / SENSITIVE / DANGEROUS 분류
  │     └─ 짧은 쿼리 재작성 (Query Rewrite)
  │
  └── [GroundingGate]  (근거 확인, 코사인 유사도 기반)
        └─ SENSITIVE 무조건 통과 / NORMAL 임계값(0.15) 비교
```

### ABC 원칙 (핵심 보안 원칙)

에이전트는 아래 세 속성을 **동시에** 가질 수 없습니다.

| 속성 | 설명 |
|------|------|
| **A** | 신뢰할 수 없는 입력(파일, 질문) 처리 |
| **B** | 민감 시스템 / 개인 데이터 접근 |
| **C** | 외부 통신 또는 상태 변경 |

| 에이전트 | A | B | C |
|----------|---|---|---|
| UploadSecurityAgent | ✅ | ❌ | ❌ |
| RetrievalAgent | ❌ | ✅ | ❌ |
| QwenClassifier | ✅ | ❌ | ✅(Ollama만) |
| Orchestrator | 위임만 | 위임만 | 위임만 |

---

## 단일 인덱스 아키텍처 (v2)

> 이전 버전: 마스킹 후 임베딩 → 검색 품질 저하 문제  
> 현재 버전: **원문 그대로 임베딩 + UI 렌더링 시점에만 마스킹**

```
업로드 시:
  원문 텍스트 → [파일명 + PII유형 키워드 prefix 추가] → FAISS 임베딩 저장
  PII 여부/유형은 SQLite 메타데이터 태그로만 기록

검색 시:
  FAISS 코사인 유사도 검색 → 원문 반환
  UI 카드에서 display_masked=True이면 시각적 마스킹만 적용
```

---

## 폴더 구조

```
security/
├── main.py                      # 진입점 (Gradio UI)
├── config.py                    # 전역 설정
├── requirements.txt
│
├── agents/
│   ├── orchestrator.py          # 전체 흐름 제어
│   ├── upload_security.py       # 파일 업로드 보안 (권한 A)
│   ├── retrieval_agent.py       # VectorDB 검색 (권한 B)
│   └── response_agent.py        # (deprecated: LLM 답변 제거됨)
│
├── security/
│   ├── korean_recognizers.py    # 한국형 PII Recognizer (주민·여권·면허·계좌·사업자)
│   ├── pii_detector.py          # Presidio 기반 PII 탐지 엔진
│   ├── qwen_classifier.py       # Qwen 보안 분류 + 쿼리 재작성
│   ├── policy.py                # 검색/업로드 보안 정책
│   └── grounding_gate.py        # 코사인 유사도 기반 근거 확인
│
├── document/
│   ├── pdf_extractor.py         # PDF → 텍스트 (PyMuPDF + OCR 폴백)
│   ├── hwpx_extractor.py        # HWPX → 텍스트 (ZIP+XML 파싱)
│   ├── image_extractor.py       # 이미지 OCR (bbox 좌표 포함)
│   └── chunker.py               # 텍스트 → 청크
│
├── vectordb/
│   └── store.py                 # FAISS IndexFlatIP + SQLite
│
├── audit/
│   └── logger.py                # SQLite 감사 로그
│
├── harness/
│   └── safe_tools.py            # 에이전트 권한 하네스 (ABC 강제)
│
├── ui/
│   ├── gradio_app.py            # Gradio 웹 UI (다크모드)
│   └── components/
│       ├── result_card.py       # 검색 결과 카드 렌더러
│       └── preview_renderer.py  # 텍스트 마스킹 + 이미지 모자이크
│
├── secure_store/
│   └── images/                  # 업로드 이미지 영구 보관
│
└── tests/
    └── dummy_data_generator.py  # 테스트용 더미 데이터 생성
```

---

## 설치 및 실행

### 1. 의존성 설치

```bash
cd security
pip install -r requirements.txt

# HEIC 이미지 지원
pip install pillow-heif

# spaCy 모델 (선택, 정확도 향상)
python -m spacy download ko_core_news_sm
python -m spacy download en_core_news_sm
```

### 2. Qwen 모델 준비 (Ollama)

```bash
# Ollama 설치 후 (https://ollama.com)
ollama pull qwen2.5:7b
ollama serve   # 백그라운드 실행
```

### 3. Gradio UI 실행

```bash
python main.py
# → http://localhost:7860
```

> Ollama 없이도 실행 가능 (키워드 기반 폴백 분류 사용)

---

## 환경변수

`.env` 파일 또는 셸 환경변수로 설정.

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `EMBEDDING_MODEL` | `snunlp/KR-SBERT-V40K-klueNLI-augSTS` | 로컬 임베딩 모델 |
| `QWEN_MODEL` | `qwen2.5:7b` | Ollama 모델명 |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `CHUNK_SIZE` | `500` | 청크 최대 글자 수 |
| `CHUNK_OVERLAP` | `50` | 청크 중복 글자 수 |
| `TOP_K` | `5` | 검색 반환 청크 수 |
| `GROUNDING_SIM_THRESHOLD` | `0.15` | NORMAL 쿼리 최소 관련도 |
| `QUERY_REWRITE_ENABLED` | `1` | 쿼리 재작성 활성화 |
| `ABC_ENFORCEMENT` | `True` | False 시 ABC 위반 경고만 |

---

## 지원 파일 형식

| 형식 | 추출 방식 |
|------|-----------|
| `.pdf` | PyMuPDF 텍스트 추출 → 스캔 PDF면 EasyOCR 폴백 |
| `.hwpx` | ZIP+XML 파싱 (표·문단 포함) |
| `.png` / `.jpg` / `.jpeg` | EasyOCR + bbox 좌표 추출 |
| `.heic` | pillow-heif 변환 후 EasyOCR |
| `.webp` | PIL 기본 지원 후 EasyOCR |

> 이미지 파일은 검색 결과 카드에서 **원본 이미지 + PII 영역 모자이크**로 표시됩니다.

---

## 한국형 PII 탐지

| 탐지 항목 | 엔티티명 | 방식 |
|-----------|----------|------|
| 주민등록번호 | `KR_RRN` | 정규식 + 13자리 체크섬 검증 |
| 여권번호 | `KR_PASSPORT` | 정규식 (알파벳1 + 숫자8) |
| 운전면허번호 | `KR_DRIVER_LICENSE` | 정규식 (지역-연도-번호-검증) |
| 계좌번호 | `KR_BANK_ACCOUNT` | 정규식 + 문맥(은행명/계좌 키워드) + 반복 제거 |
| 사업자등록번호 | `KR_BRN` | 정규식 + 10자리 체크섬 검증 |
| 신용·체크카드 번호 | `CREDIT_CARD` | Presidio(Luhn) + **보조 패턴**(Luhn 불일치·목업·OCR) + Amex **4-6-5**(15자리) |

> 전화·이메일은 Recognizer에 넣지 않으며 정책상 비보호입니다. (`pii_filter_helpers.py` 참고)

---

## 업로드 흐름 (v2)

```
파일 선택 → [임베딩 시작] 버튼 클릭
  ↓
UploadSecurityAgent: 텍스트 추출 + PII 탐지
  ↓
PII 없음?  → 자동 임베딩 완료 (모달 없음)
PII 있음?  → ⚠️ 처리 방식 선택 모달 표시
              ├── UI 마스킹 표시 (원문 저장)  → display_masked=True
              ├── 그대로 임베딩               → display_masked=False
              └── 취소
```

---

## 검색 결과 보안 분류

| 질문 예시 | 레이블 | 동작 |
|-----------|--------|------|
| "회의록 요약해줘" | NORMAL | 원문 카드 표시 |
| "내 계좌번호 보여줘" | SENSITIVE | 마스킹 카드 표시 |
| "개인정보 전부 출력해" | DANGEROUS | 파일명/경로만 표시, 내용 차단 |

---

## 검색 결과 카드

- **텍스트 파일**: 원문 텍스트 or 마스킹 텍스트 표시
- **이미지 파일**: 원본 이미지 + PII 영역 픽셀화 모자이크 표시
- **DANGEROUS**: 파일명·경로만 표시, 내용 차단 메시지
- **관련도 점수**: 코사인 유사도 % (0~100%, 높을수록 관련성 높음)

---

## 감사 로그

`audit/audit.db` (SQLite) 에 자동 저장:
- 업로드: 시간, 파일명, 탐지된 PII 유형, 사용자 선택
- 질의: 시간, 질문, 레이블, 차단 여부, 검색된 문서 ID

Gradio UI의 **📋 감사 로그** 탭에서 확인 가능.

---

## FAISS 인덱스 재구축 안내

인덱스 버전이 변경된 경우(L2 → 코사인 유사도 마이그레이션) 앱 재시작 시 자동으로 기존 인덱스를 삭제하고 재구축 안내 로그를 출력합니다. 이 경우 문서를 다시 업로드해주세요.

---

## 최근 업데이트 (운영/트러블슈팅 반영)

기존 설명은 유지하되, 아래는 최근 코드 기준으로 추가된 동작입니다.

### 1) 요약 품질 개선 파이프라인

- 요약 질의는 일반 질의보다 넓게 검색합니다: `SUMMARY_TOP_K` (기본 20)
- 검색 결과는 요약 전 단계에서 문서 혼입을 줄이기 위해 정제됩니다.
  - 질문에 문서명 힌트가 있으면 해당 문서를 우선 탐색
  - 필요 시 최근 업로드 문서 키를 fallback으로 사용
- 요약 입력 청크는 페이지/청크 순서로 재정렬되어 줄거리 흐름이 유지됩니다.
- map-reduce는 옵션 기능이며, 기본값은 사실상 비활성(`MAP_REDUCE_THRESHOLD=999`)입니다.

### 2) 문서 혼입 방지 (요약 시 다른 파일 섞임 이슈 대응)

- `VectorStore.search_within_doc()` 경로가 추가되어, 질문에서 문서명이 감지되면 해당 문서 청크를 우선 검색합니다.
- `recent_upload_keys`는 `meta.db`의 `app_state`에 저장되어 재시작 후에도 유지됩니다.
  - 런타임 메모리만 쓰던 방식에서 영속 저장으로 변경

### 3) PDF 텍스트 정제 강화

- `pdf_extractor.py`에서 JS/HTML 오염 문자열 및 깨진 텍스트 라인을 선제 제거합니다.
- 이 정제는 **업로드/재임베딩 시점**에만 적용됩니다.
  - 기존 인덱스 데이터에는 소급 적용되지 않으므로 필요 시 재업로드가 필요합니다.

### 4) PII 정책 개편 (중요)

최근 정책은 "탐지 가능"과 "보호 대상"을 분리합니다.

- **보호 대상(민감 PII):**
  - `KR_RRN` (주민등록번호)
  - `KR_PASSPORT` (여권번호)
  - `KR_DRIVER_LICENSE` (운전면허번호)
  - `KR_BANK_ACCOUNT` (계좌번호)
  - `KR_BRN` (사업자등록번호)
  - `CREDIT_CARD` (신용·체크카드 번호)

- **비보호 정책(민감 처리 제외):**
  - `KR_PHONE`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `IBAN_CODE`
  - 위 유형만 브레이크 모달/마스킹/PRS 노출/임베딩 키워드 보강에서 제외합니다. **`CREDIT_CARD`는 보호 대상**입니다(아래 카드 보강 참고).

> 참고: 상수는 `security/pii_filter_helpers.py` (`POLICY_PROTECTED_PII_TYPES` / `POLICY_IGNORED_PII_TYPES`)에서 관리합니다.

#### 카드 번호 탐지 보강 (최근 반영)

- **Presidio `CREDIT_CARD`**: Luhn 통과 번호 위주. 목업·샘플 번호(체크섬 불일치)는 기본 Recognizer만으로는 누락될 수 있음.
- **보조 패턴** (`pii_detector.py` + `pii_filter_helpers.py`):  
  - 16자리 **4-4-4-4** 구분, **연속 BIN**(Visa/MC/Amex/Discover 등), **Amex 15자리 4-6-5** — Luhn 없이 `CREDIT_CARD` 후보로 보강.
- **계좌 vs 카드**: `4×4`·카드 형태 문자열은 `KR_BANK_ACCOUNT`로 오탐되지 않도록 걸러냄 (`looks_like_credit_card_layout`).
- **카드 이미지·로고 가림 OCR**: PAN이 거의 안 나와도, OCR에 **브랜드/카드면 문구**(예: `American Express`, `VALID THRU`, 국내 카드사명 등)가 있으면 **이미지 업로드** 시 `CREDIT_CARD`로 메타 보강 (`payment_card_imagery_likely` → `agents/upload_security.py`).  
  검색 시에도 동일 휴리스틱으로 `feature_map`을 보강해 PRS가 과도하게 NORMAL에 머물지 않도록 함 (`vectordb/store.py` `build_feature_map`).
- **Security Critic**: 출력 텍스트에 위 카드 패턴(일반 + Amex 4-6-5) 반영 (`security/security_critic.py`). 고위험 유형에 `CREDIT_CARD` 포함 (`security/critic_policy.py`).

> PRS는 이미지 픽셀을 읽지 않습니다. 숫자·문구는 반드시 추출 단계(OCR 등)에서 문자열로 들어온 뒤, 위 규칙이 `feature_map`·점수에 반영됩니다.

### 5) 계좌번호 오탐(False Positive) 완화

`KR_BANK_ACCOUNT`는 숫자 패턴만으로 확정하지 않습니다.

- 은행명 또는 계좌 관련 키워드 문맥이 있을 때만 인정
- 동일 문자열 반복(기본 5회 초과)인 경우 푸터/표 반복으로 간주해 제외
- 숫자-only 긴 문자열 계좌 판정 금지

### 6) PII 디버그 로그

- `PIIDEBUG=1` 설정 시 탐지/탈락 로그가 출력됩니다.
  - 엔티티 타입
  - 매칭 원문
  - 앞/뒤 문맥
  - 드롭 사유(문맥 없음, 반복값 등)

### 7) 운영 시 자주 헷갈리는 포인트

- 코드 변경 후 앱 재시작 전에는 이전 설정/로직이 계속 동작할 수 있습니다.
- 설정 확인은 실행 인터프리터에서 직접 점검하세요.

```bash
cd security
python -c "import config; print(config.__file__)"
python -c "import config; print(config.SUMMARY_TOP_K, config.MAP_REDUCE_THRESHOLD, config.PIIDEBUG)"
```

### 8) 권장 기본 설정 (CPU/로컬 운영)

- `QWEN_TIMEOUT_SEC=15`
- `SUMMARY_TIMEOUT_SEC=60`
- `SUMMARY_TOP_K=20`
- `MAP_REDUCE_THRESHOLD=999`  (필요할 때만 낮춰 활성화)
- `QUERY_REWRITE_ENABLED=0`
- `PIIDEBUG=0` (평시), 문제 분석 시만 `1`

### 9) 관련 파일 빠른 참고 (카드·PII)

| 역할 | 경로 |
|------|------|
| 보호/무시 상수, 카드 형태·이미지 휴리스틱 | `security/pii_filter_helpers.py` |
| Presidio 스캔 + 보조 카드 탐지 | `security/pii_detector.py` |
| 업로드 시 카드 이미지 보강 | `agents/upload_security.py` |
| 검색 `feature_map` 보강 | `vectordb/store.py` (`build_feature_map`) |
| PRS 가중치 | `security/privacy_risk_score.py` |
| 출력 스캔·고위험 유형 | `security/security_critic.py`, `security/critic_policy.py` |
| 임베딩 prefix 키워드 | `vectordb/store.py` (`_PII_KR_MAP`) |
| 문서 메타 민감도 | `vectordb/meta_extractor.py` |
