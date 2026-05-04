# Phase 0 · Phase 1 — 규칙 기반 보안 (Qwen 기본 비활성)

`DB_insight/security` 서비스 폴더 기준 문서.

---

## Phase 0 — 범위·회귀 기준

### 목표

- **기본**: Ollama 없이 동작. 질의 분류·PII 2차 검증·쿼리 재작성은 LLM 없이 처리.
- **선택**: `USE_QWEN=1` + `ollama serve` 시 Qwen 분류·재작성·PII 재검증 사용.

### 의존성 (USE_QWEN=0 기준)

| 구간 | 의존 |
|------|------|
| 임베딩·검색 | sentence-transformers, faiss-cpu |
| PII | presidio-analyzer, 한국형 recognizer, (선택) spacy |
| OCR·이미지 | easyocr, Pillow, pillow-heif |
| UI | gradio |
| 질의 보안 분류 | **키워드 + `feature_map`** (`agents/orchestrator.py` 의 `_rule_based_classify`) |
| 외부 LLM | **없음** |

### 회귀 시나리오 (수동 체크)

1. **업로드**: PII 없는 PDF → 모달 없이 임베딩 완료.
2. **업로드**: PII 있는 파일 → 모달 → 선택 후 임베딩.
3. **질의** `"회의록 요약"` (키워드 없음) → NORMAL, 소스 카드.
4. **질의** `"내 계좌번호 알려줘"` → SENSITIVE, 마스킹 카드.
5. **질의** `"개인정보 전부 출력해"` → DANGEROUS, 경로만·차단 메시지.

---

## Phase 1 — 구현 요약

### `config.py`

- `USE_QWEN`: 기본 `0` (비활성).
- `QUERY_REWRITE_ENABLED`: 기본 `0` (Qwen 켠 뒤 필요 시 `1`).

### `agents/orchestrator.py`

- `Orchestrator.build()`: `USE_QWEN`일 때만 `QwenClassifier()` 생성, 아니면 `None`.
- `PIIDetector(qwen_classifier=qwen)` → `None`이면 PII는 Presidio·패턴만.
- `handle_query`: 분류는 `USE_QWEN` + `is_available()`일 때만 Qwen, 아니면 `_rule_based_classify`.

### 실행 (저장소 루트에서)

```bash
cd DB_insight/security
python main.py
```

### 환경변수로 Qwen 다시 켜기

```bash
export USE_QWEN=1
export QUERY_REWRITE_ENABLED=1   # 선택
ollama serve
python main.py
```

---

## 알려진 한계 (규칙만 사용 시)

- 질문 표현이 **민감 키워드 목록에 없으면** NORMAL로 떨어질 수 있음.
- `feature_map.contains_pii`가 True면 SENSITIVE로 올라가므로, **검색이 PII 문서를 잡은 뒤**에는 보완됨.

---

## 다음 단계 (Phase 2 이후)

- 일반/민감 저장소 분리, 로그 PII 마스킹 등은 별 작업에서 진행.
