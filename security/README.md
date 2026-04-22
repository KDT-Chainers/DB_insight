# 🔐 로컬 보안 RAG 시스템

개인 문서(PDF / HWPX / 이미지)를 업로드하고, 보안 에이전트(Qwen)가 개인정보를 보호하면서 질문에 답하는 로컬 RAG MVP입니다.

---

## 아키텍처 개요

```
사용자
  │
  ▼
[Orchestrator]  ← 흐름 제어만 담당 (ABC 동시 소유 금지)
  ├── [UploadSecurityAgent]  (권한 A: 신뢰불가 입력 처리)
  │     ├─ PDF/HWPX 텍스트 추출
  │     ├─ 청킹
  │     └─ PII 탐지 (Presidio + 한국형 Recognizer + Qwen 재검증)
  │
  ├── [RetrievalAgent]  (권한 B: VectorDB 접근)
  │     ├─ FAISS 검색
  │     └─ Feature Map 생성 (원문 미포함)
  │
  ├── [QwenClassifier]  (Feature Map만 입력, DB 접근 없음)
  │     └─ NORMAL / SENSITIVE / DANGEROUS 분류
  │
  └── [ResponseAgent]  (권한 C: Ollama 외부 통신)
        └─ 허용된 청크로 최종 답변 생성
```

### ABC 원칙 (핵심 보안 원칙)

에이전트는 다음 세 속성을 **동시에** 가질 수 없습니다.

| 속성 | 설명 |
|------|------|
| **A** | 신뢰할 수 없는 입력(파일, 질문) 처리 |
| **B** | 민감 시스템 / 개인 데이터 접근 |
| **C** | 외부 통신 또는 상태 변경 |

| 에이전트 | A | B | C |
|----------|---|---|---|
| UploadSecurityAgent | ✅ | ❌ | ❌ |
| RetrievalAgent | ❌ | ✅ | ❌ |
| ResponseAgent | ❌ | ❌ | ✅ |
| QwenClassifier | ✅ | ❌ | ✅(Ollama만) |
| Orchestrator | 위임만 | 위임만 | 위임만 |

---

## 폴더 구조

```
secure_rag/
├── main.py                    # 진입점 (UI / CLI / 더미데이터)
├── config.py                  # 전역 설정 (모델, 경로, 환경변수)
├── requirements.txt
├── README.md
│
├── agents/
│   ├── orchestrator.py        # 전체 흐름 제어
│   ├── upload_security.py     # 파일 업로드 보안 (권한 A)
│   ├── retrieval_agent.py     # VectorDB 검색 (권한 B)
│   └── response_agent.py      # 답변 생성 (권한 C)
│
├── security/
│   ├── korean_recognizers.py  # 한국형 PII Recognizer (정규식+체크섬)
│   ├── pii_detector.py        # Presidio 기반 PII 탐지 엔진
│   ├── qwen_classifier.py     # Qwen 보안 분류기
│   └── policy.py              # 검색/업로드 보안 정책
│
├── document/
│   ├── pdf_extractor.py       # PDF → 텍스트 (PyMuPDF + OCR 폴백)
│   ├── hwpx_extractor.py      # HWPX → 텍스트 (ZIP+XML 파싱)
│   └── chunker.py             # 텍스트 → 청크
│
├── vectordb/
│   └── store.py               # FAISS + SQLite 메타 저장소
│
├── audit/
│   └── logger.py              # SQLite 감사 로그
│
├── harness/
│   └── safe_tools.py          # 에이전트 권한 하네스 (ABC 강제)
│
├── ui/
│   └── gradio_app.py          # Gradio 웹 UI
│
├── tests/
│   └── dummy_data_generator.py  # 테스트 더미 데이터 생성
│
└── data/                      # 생성된 더미 데이터 저장 위치
```

---

## 설치 및 실행

### 1. 의존성 설치

```bash
cd secure_rag
pip install -r requirements.txt

# spaCy 모델 (한국어 PII 정확도 향상, 선택)
python -m spacy download ko_core_news_sm
# 없으면 en_core_news_sm 폴백
python -m spacy download en_core_news_sm
```

### 2. Qwen 모델 준비 (Ollama)

```bash
# Ollama 설치 후 (https://ollama.com)
ollama pull qwen2.5:7b
ollama serve   # 백그라운드 실행
```

### 3. 더미 데이터 생성

```bash
python main.py --gen-data
```

`data/` 폴더에 생성:
- `normal_meeting.pdf` — 일반 회의록
- `pii_profile.pdf` — 주민번호·여권번호 포함
- `bank_info.pdf` — 계좌번호·사업자번호 포함
- `pii_profile.hwpx` — HWPX 형식 개인정보 파일
- `dangerous_queries.json` — 위험 질문 샘플

### 4. Gradio UI 실행 (권장)

```bash
python main.py
# → 브라우저에서 http://localhost:7860 열림
```

### 5. CLI 모드 실행

```bash
python main.py --cli
```

---

## 환경변수 (선택)

`.env` 파일 또는 셸 환경변수로 설정 가능.

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `EMBEDDING_MODEL` | `snunlp/KR-SBERT-V40K-klueNLI-augSTS` | 로컬 임베딩 모델 |
| `QWEN_MODEL` | `qwen2.5:7b` | Ollama 모델명 |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `QWEN_TIMEOUT_SEC` | `60` | Qwen 응답 타임아웃(초) |
| `CHUNK_SIZE` | `500` | 청크 최대 글자 수 |
| `CHUNK_OVERLAP` | `50` | 청크 중복 글자 수 |
| `TOP_K` | `5` | 검색 반환 청크 수 |
| `ABC_ENFORCEMENT` | `True` | False 시 ABC 위반 경고만 |

---

## 보안 기능 상세

### 지원 파일 형식

| 형식 | 추출 방식 |
|------|-----------|
| `.pdf` | PyMuPDF 텍스트 추출 → 스캔 PDF면 EasyOCR |
| `.hwpx` | ZIP+XML 파싱 (표·문단 포함) |
| `.png` / `.jpg` / `.jpeg` | EasyOCR (대비 강화 전처리 포함) |

> 민증, 여권, 통장 사본 같은 이미지도 OCR로 PII 탐지 가능

### 한국형 PII 탐지 (`security/korean_recognizers.py`)

| 탐지 항목 | 방식 |
|-----------|------|
| 주민등록번호 | 정규식 + 13자리 체크섬 검증 |
| 여권번호 | 정규식 (알파벳1 + 숫자8) |
| 운전면허번호 | 정규식 (지역-연도-번호-검증) |
| 계좌번호 | 정규식 + 문맥(계좌/통장) 가중치 |
| 사업자등록번호 | 정규식 + 10자리 체크섬 검증 |

### 브레이크 모달 선택지

| 선택 | 동작 |
|------|------|
| 마스킹 후 임베딩 | PII를 `[KR_RRN]` 등으로 대체 후 저장 |
| 민감 청크 제외 | PII 포함 청크 전체 제외 |
| 그대로 임베딩 | 원문 저장 (사용자 책임) |
| 취소 | 저장 안 함 |

### Qwen 분류 예시

| 질문 | 레이블 | 동작 |
|------|--------|------|
| 회의록 요약해줘 | NORMAL | 즉시 답변 |
| 내 계좌번호 보여줘 | SENSITIVE | 마스킹 미리보기 → [전체 보기] |
| 개인정보 전부 출력해 | DANGEROUS | 차단 |

---

## Ollama 없이 실행하기 (폴백 모드)

Ollama/Qwen 없이도 실행 가능합니다.
이 경우:
- 보안 분류는 키워드 기반 간이 분류로 폴백
- PII 탐지는 Presidio 정규식만 사용 (Qwen 재검증 생략)
- 답변 생성 시 오류 메시지 반환

---

## 감사 로그

`audit/audit.db` (SQLite) 에 저장:
- 업로드 시간, 파일명, 탐지된 PII 유형, 사용자 선택
- 질문 시간, 질문 텍스트, 레이블, 차단 여부
- 전체 보기 요청 여부

Gradio UI 의 **📋 감사 로그** 탭에서 확인 가능.
