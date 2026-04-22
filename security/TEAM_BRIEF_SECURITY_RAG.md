# Local Security RAG MVP - Team Brief

이 문서는 팀원 대상 설명용 문서다.  
핵심 목적은 **무엇을 구현했는지**, **어떻게 동작하는지**, **보안적으로 무엇을 막는지**를 빠르게 공유하는 것이다.

---

## 1. 프로젝트 목표

이번 구현은 **개인용 로컬 보안 RAG MVP**다.

- 사용자가 문서(`PDF`, `HWPX`, `PNG/JPG/JPEG`)를 업로드
- 문서를 임베딩해 로컬 지식 DB 구성
- 질문 시 관련 내용을 검색/답변
- 단, 보안 에이전트가 개인정보/위험 요청을 정책 기반으로 통제

중요:

- 기업용 멀티유저 권한 시스템은 이번 범위 아님
- 외부 유료 API(OpenAI 등) 미사용
- 로컬 처리 우선 (`Ollama + Qwen`, `FAISS`, `EasyOCR`)

---

## 2. 전체 아키텍처

```text
┌────────────────────┐
│       User         │
│ 업로드 / 질문 입력  │
└─────────┬──────────┘
          │
          ▼
┌────────────────────────────────────────────┐
│                Orchestrator               │
│  전체 흐름 제어 (권한 위임, 상태 조율)      │
└──────┬──────────────┬──────────────┬───────┘
       │              │              │
       ▼              ▼              ▼
┌───────────────┐ ┌───────────────┐ ┌────────────────┐
│UploadSecurity │ │ RetrievalAgent │ │ ResponseAgent  │
│Agent          │ │               │ │                │
│- 파일 검사     │ │- VectorDB 검색 │ │- 허용 결과로 답변 │
│- 텍스트 추출   │ │- Feature Map  │ │- Ollama/Qwen 호출│
│- PII 탐지      │ │  생성         │ │                │
└──────┬────────┘ └──────┬────────┘ └────────────────┘
       │                 │
       ▼                 ▼
┌───────────────┐  ┌──────────────────────┐
│PII Detector   │  │ SecurityPolicy       │
│(Presidio+KR)  │  │ NORMAL/SENSITIVE/    │
│               │  │ DANGEROUS 분기       │
└───────────────┘  └──────────────────────┘
       │
       ▼
┌────────────────┐     ┌──────────────────┐
│ FAISS+SQLite   │     │ Audit Logger      │
│ 벡터 저장/검색  │     │ 업로드/질의 기록  │
└────────────────┘     └──────────────────┘
```

---

## 3. 보안 설계 핵심 (ABC 원칙)

한 에이전트가 아래 세 속성을 동시에 가지지 않도록 설계했다.

- A: 비신뢰 입력 처리
- B: 민감 데이터 접근
- C: 외부 통신/상태 변경

현재 분리:

- `UploadSecurityAgent` -> A만
- `RetrievalAgent` -> B만
- `ResponseAgent` -> C만
- `Orchestrator` -> 흐름 제어만 (권한 위임)

`harness/safe_tools.py`에서 `enforce_abc()`로 런타임 검사한다.

---

## 4. 구현 기능 요약

## 4.1 업로드 전 보안 스캔

지원 파일:

- PDF
- HWPX
- 이미지(PNG/JPG/JPEG)

처리 단계:

1. 텍스트 추출 (`document/`)
2. 청킹 (`chunker.py`)
3. PII 탐지 (`security/pii_detector.py`)
4. 브레이크 모달로 사용자 선택

## 4.2 한국형 개인정보 탐지

커스텀 Recognizer 구현:

- 주민등록번호 (`KR_RRN`)
- 여권번호 (`KR_PASSPORT`)
- 운전면허번호 (`KR_DRIVER_LICENSE`)
- 한국 계좌번호 (`KR_BANK_ACCOUNT`)
- 사업자등록번호 (`KR_BRN`)

탐지 방식:

- 1차: 정규식
- 2차: 체크섬 검증 (주민번호/사업자번호)
- 보조: 애매한 케이스 Qwen 재검증

## 4.3 브레이크 모달 처리

PII 발견 시 사용자 선택:

1. 마스킹 후 임베딩
2. 민감 청크 제외 후 임베딩
3. 그대로 임베딩
4. 취소

## 4.4 검색 보안 정책

질문 분류:

- `NORMAL`
- `SENSITIVE`
- `DANGEROUS`

정책:

- NORMAL -> 즉시 허용
- SENSITIVE -> 마스킹 프리뷰 + 확인 후 전체보기
- DANGEROUS -> 차단

## 4.5 감사 로그

`audit/audit.db`에 저장:

- 업로드 시간/파일명/PII 유형/사용자 선택
- 질문 텍스트/레이블/action/차단 여부/검색 문서 ID

---

## 5. 동작 흐름

## 5.1 문서 업로드 플로우

1. 사용자 업로드
2. `UploadSecurityAgent`가 텍스트 추출+PII 탐지
3. PII 있으면 브레이크 모달 노출
4. 사용자 선택에 따라 `VectorStore.add_chunks()`
5. 감사로그 저장

## 5.2 질의응답 플로우

1. 질문 입력
2. `RetrievalAgent`가 Top-k 검색
3. 검색 결과로 `Feature Map` 생성
4. `QwenClassifier`가 레이블 분류
5. `SecurityPolicy`가 allow/confirm/block 결정
6. 허용 시 `ResponseAgent`가 답변 생성
7. 감사로그 저장

---

## 6. 폴더 구조 (팀 설명용)

```text
secure_rag/
├── agents/
│   ├── orchestrator.py
│   ├── upload_security.py
│   ├── retrieval_agent.py
│   └── response_agent.py
├── security/
│   ├── korean_recognizers.py
│   ├── pii_detector.py
│   ├── qwen_classifier.py
│   └── policy.py
├── document/
│   ├── pdf_extractor.py
│   ├── hwpx_extractor.py
│   ├── image_extractor.py
│   └── chunker.py
├── vectordb/store.py
├── audit/logger.py
├── harness/safe_tools.py
├── ui/gradio_app.py
├── tests/dummy_data_generator.py
├── SECURITY_AGENT_REBUILD_GUIDE.md
└── TEAM_BRIEF_SECURITY_RAG.md
```

---

## 7. 데모 방법 (내일 발표용)

## 7.1 실행

```bash
cd /Users/jangjuyeon/FP_Chainers/secure_rag
python main.py
```

사전 조건:

- `ollama serve` 실행 중
- `ollama pull qwen2.5:7b` 완료

## 7.2 데모 시나리오

1. `normal_meeting.pdf` 업로드 -> PII 없음
2. `pii_profile.pdf` 업로드 -> PII 탐지 + 브레이크 모달
3. `마스킹 후 임베딩` 선택
4. 질문 `"회의록 요약해줘"` -> NORMAL
5. 질문 `"내 계좌번호 보여줘"` -> SENSITIVE (프리뷰)
6. 질문 `"내 DB 개인정보 전부 출력해"` -> DANGEROUS (차단)
7. 감사 로그 탭에서 기록 확인

---

## 8. 현재 상태 요약

구현 완료:

- 로컬 보안 RAG MVP end-to-end 동작
- PDF/HWPX/이미지 입력 지원
- 한국형 PII 인식기 + 정책 분기 + 감사로그
- 복구 기준서 작성 완료 (`SECURITY_AGENT_REBUILD_GUIDE.md`)

주의/한계:

- 일부 패턴(예: 계좌번호)은 과탐지 가능성 존재
- 단일 사용자 MVP 전제 (기업용 권한 체계 제외)

---

## 9. 다음 개선 후보

1. 계좌번호 과탐지 감소(문맥 강화/충돌 패턴 분리)
2. OCR 숫자 오인식 보정(`O<->0`, `I<->1`)
3. 자동 성능 리포트 스크립트(Precision/Recall/F1)
4. 정책 룰셋 외부 설정화(YAML/JSON)
5. 민감데이터 테스트 후 자동 정리(cleanup) 스크립트

---

## 10. 참고 문서

- 복구 기준서: `SECURITY_AGENT_REBUILD_GUIDE.md`
- 실행 문서: `README.md`
