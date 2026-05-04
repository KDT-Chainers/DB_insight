# Security Critic + Summary Agent 도킹/통합 정리

`DB_insight/security` 기준 문서.

이 문서는 아래 2가지를 한 번에 정리한다.

1. **Security Critic + Summary Agent 합체(도킹) 과정**
2. **현재 전체 구조(역할/흐름/파일 맵)**

---

## 1) 핵심 결론

- 서비스는 하나로 유지: `DB_insight/security`
- 내부 도메인은 분리:
  - `agents/security/*` → 보안 승인 도메인
  - `agents/summary/*` → 요약 생성 도메인
- 최종 보안 원칙:
  - **Summary = 생성자**
  - **Critic = 승인자(필수 통과)**

즉, 요약을 만들 수는 있지만, 밖으로 나가기 전에는 항상 Critic이 최종 심사한다.

---

## 2) 도킹 전/후 아키텍처

### 도킹 전

```text
Query
 → Retrieval
 → GroundingGate
 → Security Critic
 → UI
```

### 도킹 후 (현재)

```text
[일반 질의]
Query
 → Retrieval
 → GroundingGate
 → Security Critic
 → UI

[요약 질의]
Query
 → Retrieval
 → GroundingGate
 → Summary Agent (선택 호출)
 → Security Critic (필수)
 → UI
```

### regenerate 경로

```text
Summary Agent 출력
 → Critic: regenerate_with_constraints
 → Summary Agent 재요청(제약 포함)
 → Critic 재심사
 → UI
```

---

## 3) 합체(도킹) 구현 단계 요약

### Step A. Summary Agent 독립 모듈화

- 생성: `agents/summary/summary_agent.py`
- 포함 기능(모두 이 파일 내부):
  - 프롬프트 관리
  - Qwen/Ollama 호출
  - `USE_QWEN=0` fallback 요약
  - 제약 기반 재생성(`summarize_with_constraints`)
  - 요약 출력 포맷

### Step B. Security 도메인 파사드 구성

- 생성: `agents/security/critic_domain.py`
- 역할:
  - 기존 구현(`security/security_critic.py`, `session_risk_engine.py`, `regenerate_handler.py`)을
    orchestrator 입장에서 한 군데로 묶어 import

### Step C. Orchestrator 최소 수정

- `is_summary_request(query)` 규칙 함수 추가
- 요약 요청일 때만 `SummaryAgent` 호출
- Critic은 항상 실행
- `regenerate_with_constraints` 시 SummaryAgent 재호출
- `QueryResponse`에 `summary` 필드 추가(요약 결과 전달)

### Step D. Audit/UI 최소 확장

- audit: `used_summary_agent`, `summary_regenerated` 저장
- UI: 정책 영역에 Summary 사용 여부 표시 + 요약 결과 박스 표시

---

## 4) 현재 폴더 구조 (도메인 분리 반영)

```text
DB_insight/security/
├── agents/
│   ├── orchestrator.py
│   ├── retrieval_agent.py
│   ├── upload_security.py
│   ├── response_agent.py
│   ├── summary/
│   │   ├── __init__.py
│   │   └── summary_agent.py
│   ├── security/
│   │   ├── __init__.py
│   │   └── critic_domain.py
│   └── summary_agent.py   # 호환용 shim (구 import 유지)
├── security/
│   ├── security_critic.py
│   ├── session_risk_engine.py
│   ├── critic_policy.py
│   ├── regenerate_handler.py
│   └── ...
├── audit/
│   └── logger.py
├── ui/
│   └── gradio_app.py
└── config.py
```

> 참고: `agents/summary_agent.py`는 기존 import 호환성을 위해 남겨둔 얇은 재내보내기(shim) 파일이다.

---

## 5) 역할 분리 표 (SRP / Low Coupling)

| 구성요소            | 책임                              | 하지 않는 일                        |
| ------------------- | --------------------------------- | ----------------------------------- |
| `SummaryAgent`      | 검색된 텍스트를 읽기 쉽게 요약    | 정책 판단, 차단 결정, DB 조회       |
| `SecurityCritic`    | 출력물 최종 승인/차단/재생성 요구 | 검색 수행, 요약 생성                |
| `SessionRiskEngine` | 세션 누적 위험 점수 관리          | 문서 생성/요약                      |
| `GroundingGate`     | 근거 충분성 판정                  | 보안 정책 승인                      |
| `Orchestrator`      | 흐름 제어/연결                    | 요약 상세 로직, 심사 로직 내부 구현 |

---

## 6) Summary 호출 규칙 (MVP 규칙 기반)

`orchestrator.is_summary_request()`가 다음 키워드를 기준으로 호출 여부를 판단한다.

- 예: `요약`, `정리`, `핵심`, `간단히`, `줄여`, `한줄`, `3줄`, `요점`, `summary`, `summarize`, `tldr`

### 동작 예시

- `"회의록 요약해줘"` → Summary Agent 호출
- `"핵심만 정리해줘"` → Summary Agent 호출
- `"계좌번호 보여줘"` → Summary Agent 미호출
- `"주민번호 확인해줘"` → Summary Agent 미호출

---

## 7) 보안 보장 포인트

1. Summary Agent는 **선택적**이다. (요약 요청일 때만)
2. Security Critic은 **필수**다. (모든 경로에서 통과)
3. Critic이 `regenerate_with_constraints`를 내리면
   - 요약 모드: SummaryAgent 재생성
   - 비요약 모드: 텍스트 PII strip 경로
4. Summary Agent는 DB 직접 접근이 없다.
5. Session Risk, Prompt Injection, Output PII 검사는 Critic이 담당한다.

---

## 8) 디버깅/유지보수 가이드

### Summary 품질/모델 문제일 때

- 수정 파일: `agents/summary/summary_agent.py` **한 파일**
- 점검 지점:
  - `_build_prompt()`
  - `_call_qwen()`
  - `_extractive_fallback()`
  - `_format_output()`

### 보안 승인/차단 문제일 때

- 수정 파일:
  - `security/security_critic.py`
  - `security/critic_policy.py`
  - `security/session_risk_engine.py`

### 흐름 연결 문제일 때

- 수정 파일: `agents/orchestrator.py`

### 감사 로그 표시 문제일 때

- 수정 파일:
  - `audit/logger.py`
  - `ui/gradio_app.py`

---

## 9) QA 체크리스트 (발표 전)

- [ ] 일반 질의에서 Summary Agent가 호출되지 않는다.
- [ ] 요약 질의에서만 Summary Agent가 호출된다.
- [ ] Summary 응답도 Critic에서 차단/마스킹/재생성될 수 있다.
- [ ] Critic 로그에 `used_summary_agent`가 정확히 기록된다.
- [ ] Critic 로그에 `summary_regenerated`가 정확히 기록된다.
- [ ] `USE_QWEN=0`일 때 fallback 요약이 정상 동작한다.
- [ ] `USE_QWEN=1` + Ollama 활성화 시 Qwen 요약이 정상 동작한다.

---

## 10) 운영 메모

- 현재 구조는 발표/데모/유지보수 관점에서 충분히 실무형이다.
- 추후 확장 시에도 서비스 루트는 유지하고, 도메인(`security`/`summary`)만 확장하면 된다.
- 결합도 최소화를 위해 orchestrator는 상세 로직을 계속 들고 있지 않고, 도메인 모듈에 위임하는 방식을 유지한다.
