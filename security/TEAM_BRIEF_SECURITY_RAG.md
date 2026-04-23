# Local Security RAG MVP - Team Brief

이 문서는 팀원 대상 설명용 문서다.  
핵심 목적은 **무엇을 구현했는지**, **어떻게 동작하는지**, **보안적으로 무엇을 막는지**를 빠르게 공유하는 것이다.

---

## 1. 프로젝트 목표

**개인용 로컬 보안 RAG 시스템** — 외부 API 없이 완전 로컬 처리.

- 문서(`PDF`, `HWPX`, `PNG/JPG/JPEG/HEIC/WEBP`)를 업로드
- 문서를 임베딩해 로컬 지식 DB 구성 (FAISS)
- 질문 시 관련 문서를 검색해 카드로 표시
- 보안 에이전트가 개인정보/위험 요청을 정책 기반으로 통제
- **LLM 답변 없음**: 검색된 소스 카드만 표시 (정확도 우선)

중요:
- 외부 유료 API(OpenAI 등) 미사용
- 완전 로컬 처리 (`Ollama + Qwen`, `FAISS`, `EasyOCR`)
- 기업용 멀티유저 권한 시스템은 이번 범위 아님

---

## 2. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                          User (Gradio UI)                        │
│                     파일 업로드 / 질문 입력                        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Orchestrator                              │
│                  전체 흐름 제어 (권한 위임, 상태 조율)              │
└──────┬──────────────────┬────────────────────┬───────────────────┘
       │                  │                    │
       ▼                  ▼                    ▼
┌─────────────┐  ┌────────────────┐  ┌─────────────────────┐
│Upload       │  │RetrievalAgent  │  │QwenClassifier       │
│SecurityAgent│  │                │  │                     │
│- 파일 검사   │  │- FAISS 검색    │  │- NORMAL/SENSITIVE/  │
│- 텍스트 추출 │  │  (코사인 유사도)│  │  DANGEROUS 분류     │
│- 이미지 OCR  │  │- Feature Map  │  │- 쿼리 재작성         │
│  + bbox 추출 │  │  생성 (원문 ×) │  │  (짧은 쿼리 확장)    │
│- PII 탐지    │  └───────┬────────┘  └──────────┬──────────┘
│- 이미지 영구  │          │                      │
│  복사         │          ▼                      ▼
└──────┬───────┘  ┌────────────────┐  ┌──────────────────┐
       │          │ SecurityPolicy  │  │ GroundingGate    │
       ▼          │ allow/confirm/  │  │ 코사인 유사도     │
┌─────────────┐  │ block 결정      │  │ 임계값 확인       │
│PII Detector │  └────────────────┘  └──────────────────┘
│(Presidio+KR)│
│6종 인식기    │
└──────┬───────┘
       │
       ▼
┌──────────────────┐     ┌───────────────────┐
│ FAISS IndexFlatIP │     │  Audit Logger      │
│ + SQLite 메타DB   │     │  업로드/질의 기록   │
│ (원문 저장)        │     └───────────────────┘
└──────────────────┘
```

---

## 3. 핵심 설계 결정 3가지

### 3.1 ABC 보안 원칙

한 에이전트가 아래 세 속성을 동시에 가지지 않도록 설계.

- A: 비신뢰 입력 처리
- B: 민감 데이터 접근
- C: 외부 통신/상태 변경

| 에이전트 | A | B | C |
|----------|---|---|---|
| UploadSecurityAgent | ✅ | ❌ | ❌ |
| RetrievalAgent | ❌ | ✅ | ❌ |
| QwenClassifier | ✅ | ❌ | ✅(Ollama만) |
| Orchestrator | 위임만 | 위임만 | 위임만 |

`harness/safe_tools.py`에서 `enforce_abc()`로 런타임 강제.

### 3.2 단일 인덱스 + UI 마스킹

**이전 방식의 문제:** 마스킹된 텍스트를 임베딩하면 중요 키워드가 빠져 검색 품질이 크게 저하.

**현재 방식:**
```
임베딩 저장: 원문 그대로 저장 (마스킹 없음)
UI 렌더링: display_masked=True이면 그때만 시각적 마스킹
```

→ 검색 정확도 유지 + 민감 정보 화면 보호 동시 달성

### 3.3 코사인 유사도 기반 검색

**이전 방식의 문제:** `IndexFlatL2` (유클리드 거리) 사용 → 점수가 400대로 표시되고 랭킹 오류.

**현재 방식:** `IndexFlatIP` + L2 정규화 벡터 = 코사인 유사도 (0~100%)

---

## 4. 구현 기능 요약

### 4.1 업로드 흐름 (자동 감지)

```
파일 선택 → [임베딩 시작] 클릭
  ↓
실시간 진행 상태 표시 (단계별 업데이트)
  ↓
PII 없음? → 자동 임베딩 완료
PII 있음? → ⚠️ 처리 방식 선택 모달 팝업
              ├── UI 마스킹 표시 (원문 저장)
              ├── 그대로 임베딩
              └── 취소
```

### 4.2 지원 파일 형식

| 형식 | 추출 방식 | 특이사항 |
|------|-----------|----------|
| `.pdf` | PyMuPDF → OCR 폴백 | 스캔 PDF도 지원 |
| `.hwpx` | ZIP+XML 파싱 | 표/문단 포함 |
| `.png/.jpg/.jpeg` | EasyOCR + bbox | PII 위치 좌표 추출 |
| `.heic` | pillow-heif 변환 후 EasyOCR | iPhone 사진 지원 |
| `.webp` | PIL 기본 지원 후 EasyOCR | - |

### 4.3 한국형 개인정보 탐지 (6종)

| 항목 | 엔티티명 | 탐지 방식 |
|------|----------|-----------|
| 주민등록번호 | `KR_RRN` | 정규식 + 체크섬 |
| 여권번호 | `KR_PASSPORT` | 정규식 |
| 운전면허번호 | `KR_DRIVER_LICENSE` | 정규식 |
| 계좌번호 | `KR_BANK_ACCOUNT` | 정규식 + 문맥 |
| 사업자등록번호 | `KR_BRN` | 정규식 + 체크섬 |
| **전화번호** | `KR_PHONE` | 정규식 (010/02/지역/대표) |

OCR 전처리: 대비 강화(2.5x) + **그레이스케일 변환** (빨간 도장 간섭 제거)

### 4.4 검색 보안 분류

| 질문 예시 | 레이블 | 화면 표시 |
|-----------|--------|-----------|
| "회의록 요약해줘" | NORMAL | 원문 소스 카드 |
| "내 계좌번호 보여줘" | SENSITIVE | 마스킹 소스 카드 |
| "개인정보 전부 출력해" | DANGEROUS | 파일명/경로만 + 차단 메시지 |

### 4.5 이미지 검색 결과 카드

- 텍스트 파일: 원문 또는 마스킹 텍스트 표시
- **이미지 파일: 원본 이미지 표시 + PII 영역 픽셀화 모자이크**
- DANGEROUS: 파일명·경로만, 내용 차단
- 관련도 점수: `87.3%` 형태로 표시 (코사인 유사도)

### 4.6 쿼리 개선

- **쿼리 재작성**: "여권 찾아줘" → "여권 여권번호 passport 개인정보 확인" 형태로 확장
- **GroundingGate**: SENSITIVE 쿼리는 무조건 통과, NORMAL은 유사도 임계값(0.15) 비교

### 4.7 감사 로그

`audit/audit.db`에 자동 저장:
- 업로드: 시간, 파일명, PII 유형, 사용자 선택
- 질의: 시간, 질문, 레이블, action, 차단 여부, 검색 문서 ID

---

## 5. 동작 흐름

### 5.1 문서 업로드 플로우

```
1. 사용자: 파일 선택 → [임베딩 시작] 클릭
2. UploadSecurityAgent: 텍스트 추출 + PII 탐지
   - 이미지라면: EasyOCR detail=1 + bbox 추출 + secure_store 영구 복사
3. PII 없음 → 즉시 임베딩 완료 (원문 저장)
4. PII 있음 → 모달: "UI 마스킹 / 그대로 / 취소" 선택
5. 선택 결과 + 메타데이터(is_image, pii_regions 등) → VectorStore 저장
6. 감사로그 기록
```

### 5.2 질의 흐름

```
1. 사용자: 질문 입력
2. Qwen: 짧은 질문이면 쿼리 재작성
3. RetrievalAgent: FAISS 코사인 유사도 Top-K 검색
4. Qwen: feature_map → NORMAL/SENSITIVE/DANGEROUS 분류
5. Policy: allow/confirm/block 결정
6. DANGEROUS → path_only_chunks 반환 (_blocked=True)
7. GroundingGate 확인 (SENSITIVE는 무조건 통과)
8. 결과 카드 렌더링 (텍스트 or 이미지 모자이크)
9. 감사로그 기록
```

---

## 6. 폴더 구조

```
security/
├── agents/
│   ├── orchestrator.py
│   ├── upload_security.py
│   ├── retrieval_agent.py
│   └── response_agent.py
├── security/
│   ├── korean_recognizers.py    # 6종 PII 인식기
│   ├── pii_detector.py
│   ├── qwen_classifier.py       # 분류 + 쿼리 재작성
│   ├── policy.py
│   └── grounding_gate.py
├── document/
│   ├── pdf_extractor.py
│   ├── hwpx_extractor.py
│   ├── image_extractor.py       # HEIC/WEBP + bbox
│   └── chunker.py
├── vectordb/store.py            # IndexFlatIP + 코사인 유사도
├── audit/logger.py
├── harness/safe_tools.py
├── ui/
│   ├── gradio_app.py            # 다크모드 UI
│   └── components/
│       ├── result_card.py       # 이미지 모자이크 카드
│       └── preview_renderer.py
├── secure_store/images/         # 업로드 이미지 영구 보관
├── tests/dummy_data_generator.py
├── SECURITY_AGENT_REBUILD_GUIDE.md
└── TEAM_BRIEF_SECURITY_RAG.md
```

---

## 7. 데모 방법

### 7.1 실행

```bash
# Ollama 먼저 실행
ollama serve

# 앱 시작
cd /경로/security
python main.py
# → http://localhost:7860
```

### 7.2 데모 시나리오

1. **일반 파일 업로드** (PII 없음)
   - `normal_meeting.pdf` 업로드 → 자동 임베딩 완료

2. **개인정보 포함 파일** (PII 있음)
   - `pii_profile.pdf` 업로드 → 모달 등장
   - `UI 마스킹 표시` 선택 → 임베딩

3. **이미지 파일** (여권/통장)
   - `여권.jpg` 업로드 → OCR + PII 탐지 + 이미지 영구 저장
   - `UI 마스킹 표시` 선택

4. **질의 테스트**
   - `"회의록 요약해줘"` → NORMAL → 소스 카드
   - `"계좌번호 알려줘"` → SENSITIVE → 마스킹 카드
   - `"개인정보 전부 출력해"` → DANGEROUS → 파일 경로만

5. **감사 로그 탭** → 전체 이력 확인

---

## 8. 현재 상태 요약

### 구현 완료

| 항목 | 상태 |
|------|------|
| PDF/HWPX/PNG/JPG/HEIC/WEBP 입력 | ✅ |
| 한국형 PII 인식기 6종 (KR_PHONE 포함) | ✅ |
| 단일 인덱스 + UI 마스킹 아키텍처 | ✅ |
| 코사인 유사도 검색 (IndexFlatIP) | ✅ |
| 이미지 bbox 기반 모자이크 | ✅ |
| 쿼리 재작성 (Qwen) | ✅ |
| DANGEROUS 파일 경로 표시 | ✅ |
| 다크모드 UI | ✅ |
| 다중 파일 업로드 | ✅ |
| 실시간 진행 상태 표시 | ✅ |
| 감사 로그 (SQLite) | ✅ |
| 복구 기준서 | ✅ |

### 알려진 한계

- 단일 사용자 MVP (멀티테넌시 없음)
- 일부 도장/저화질 이미지에서 OCR 오인식 가능성
- Qwen 미실행 시 키워드 기반 폴백 분류 (정확도 낮음)

---

## 9. 개선 후보

1. OCR 숫자 오인식 보정 (`O↔0`, `I↔1`)
2. 계좌번호 과탐지 감소 (은행별 길이 검증 강화)
3. 이미지 OCR 품질 측정 지표 추가
4. 정책 룰셋 외부 설정화 (YAML)
5. 멀티유저 권한 확장

---

## 10. 참고 문서

- 복구 기준서: `SECURITY_AGENT_REBUILD_GUIDE.md`
- 실행 가이드: `README.md`
