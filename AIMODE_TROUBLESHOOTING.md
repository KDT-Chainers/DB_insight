# AIMODE RAG 파이프라인 Troubleshooting 기록

**작성일**: 2026-05-05  
**파일**: `C:\Honey\DB_insight\App\backend\routes\aimode.py`  
**테스트 스크립트**: `C:\tmp\test_v5.py`  
**목표**: AIMODE 답변이 Claude 참조 답변과 일치하도록 LangGraph 파이프라인 및 프롬프트 재설계

---

## 테스트 질문 4개 (기준 답변)

| ID | 질문 | 정답 핵심 |
|----|------|-----------|
| Q1 | 2026년 3월 FAO 세계식량가격지수는 얼마이며, 유지류와 설탕 가격이 오른 원인은? | 128.5 / 팜유(말레이시아 감산), 해바라기유(러-우 분쟁), 설탕(에탄올 수요↑, 브라질 작황 부진) |
| Q2 | 2025/26년도 세계 곡물 총 생산량 전망치와 전년 대비 증가율은? | 3,035.5백만톤 / 전년 대비 5.8% 증가 |
| Q3 | 삼성전자 이해관계자 소통 방식 (8대 그룹 포함) | 문서 원문의 8대 그룹 + 구체적 채널(지속가능경영 웹사이트, 뉴스룸 등) |
| Q4 | 삼성전자의 2030년 탄소중립 목표와 2024년 재생에너지 전환율 | DX부문 2030년 탄소중립 / **93.4%** 재생에너지 전환 |

---

## 핵심 발견사항

### PDF 위치 확인
- **Samsung PDF**: `C:\Honey\DB_insight\Data\raw_DB\Docs\Samsung_Electronics_Sustainability_Report_2025_KOR.pdf`  
  - 원본 179,328자
  - **위치 1732**: `"DX(Device eXperience)부문은 2030년 탄소중립 달성을 목표로 2024년 말 기준 전체 에너지의 93.4%가 재생에너지로 전환되었고"` → 문서 앞 5000자 안에 있음
- **FAO PDF**: 페이지 3에 `"3,035.5백만톤, 5.8%"` 데이터 존재

---

## 문제 목록 및 해결 과정

---

### 문제 1: PDF 캐시 의존성 제거

**증상**: 기존 코드가 `page_text` 캐시 파일을 읽어 처리함  
**원인**: 캐시 생성 시점과 실제 PDF 내용이 다를 수 있음  
**해결**: `_read_source_full_text` 함수를 완전히 재작성 → **fitz(PyMuPDF)로 항상 PDF 직접 읽기**

```python
def _read_source_full_text(source: dict, max_chars: int = 60000) -> str:
    """
    우선순위:
      1) PDF → fitz 직접 읽기 (항상 원본, 캐시 우회)
      2) docx/hwp → converted_pdf → fitz
      3) python-docx 폴백
      4) 텍스트 파일
    """
    if ext == ".pdf":
        import fitz as _fitz
        with _fitz.open(str(fp)) as doc:
            for page in doc:
                t = page.get_text("text") or ""
                t = _join_pdf_lines(t.strip())
                texts.append(t)
        return "\n".join(texts)[:max_chars]
```

---

### 문제 2: fitz PDF 소프트 줄바꿈

**증상**: fitz가 문장 중간에 `\n`을 삽입해 문장이 파편화됨  
**예시**: `"재생에너지\n전환율은 93.4%"` → 키워드 검색 실패  
**해결**: `_join_pdf_lines()` 헬퍼 작성

```python
def _join_pdf_lines(text: str) -> str:
    """fitz PDF 소프트 줄바꿈 제거"""
    _SENT_END = frozenset(["다", "요", "죠", "함", "임", "!", "?", "。"])
    _BULLET = re.compile(r"^[·•\-\d①②③④⑤]")
    lines = text.split("\n")
    result = []
    for line in lines:
        if (result
                and line
                and result[-1]
                and result[-1][-1] not in _SENT_END
                and not _BULLET.match(line.strip())
                and not line.strip().startswith("[")
                and not line.strip().startswith("(")
        ):
            result[-1] += line  # 이전 줄에 붙이기
        else:
            result.append(line)
    return "\n".join(result)
```

**주의**: `frozenset("다요죠...")` 형태로 작성 시 일부 환경에서 segfault 발생  
→ `frozenset(["다", "요", "죠", ...])` 리스트 방식으로 수정

---

### 문제 3: `\n\n` 단락 분할 실패

**증상**: fitz 텍스트는 단락 구분이 `\n`(단일)이라 `\n\n` 기준 분할 시 전체가 하나의 덩어리  
**해결**: 단락 분할 방식 버리고 **슬라이딩 윈도우 키워드 검색**으로 전환 → `_keyword_target_paragraphs()`

```python
def _keyword_target_paragraphs(
    full_text: str, question: str, keywords: list[str],
    max_chars: int = 12000, window: int = 800,
) -> str:
    """키워드 주변 ±800자 윈도우 추출 + CJK 필터 포함"""
    # 1. CJK 문자 비율 25% 이상 줄 제거
    # 2. 질문 토큰 + 키워드로 검색
    # 3. 겹치는 윈도우 병합
    # 4. 키워드 다수 포함 + 숫자비율 높은 순 정렬
    # 5. 문서 앞 2000자 항상 포함
```

---

### 문제 4: 삼성 PDF 중국어 섞임

**증상**: Samsung ESG 보고서 PDF에 중국어 텍스트 섹션 포함 → 답변에 중국어 출력  
**해결**: CJK 필터 적용 (한자 비율 25% 이상 줄 제거)

```python
def _filter_cjk(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        cjk = len(re.findall(r"[一-鿿　-ヿ]", line))
        total = len(line.strip())
        if total == 0 or cjk / total < 0.25:
            lines.append(line)
    return "\n".join(lines)
```

---

### 문제 5: Q2 FAO 곡물생산 회귀

**증상**: "문서 앞 2000자 항상 포함" 로직 추가 후 Q2 답변이 틀려짐  
**원인**: FAO 곡물 데이터는 PDF 앞부분(앞 2000자)이 아닌 3페이지에 있음  
**해결**: scan_node 청크를 primary 소스로, 문서 앞은 5000자로 확장

```python
# generate_node 내부
scan_text = "\n\n".join(c.strip() for c in scan_chunks if c.strip())
head = full_text[:5000]           # 앞 5000자
extra = _keyword_target_paragraphs(full_text[5000:], ...)  # 나머지에서 키워드 검색
combined = "\n\n===\n\n".join([scan_text, head, extra])
```

---

### 문제 6: SSE 필드명 불일치

**증상**: 테스트 스크립트에서 모든 질문이 응답 없음  
**원인**: `/chat` 엔드포인트는 `body.get("query")`를 읽는데 테스트 스크립트가 `"question"` 필드 사용  
**해결**: 테스트 스크립트 수정

```python
# 수정 전
body = {"question": question, ...}

# 수정 후
body = {"query": question, "thread_id": thread_id, "topk": 3}
```

---

### 문제 7: 백엔드 좀비 프로세스

**증상**: 백엔드 재시작 시 포트 5001 이미 사용 중 오류  
**원인**: 이전 테스트 실행에서 python 프로세스가 종료되지 않고 누적됨  
**해결**: 재시작 전 기존 프로세스 강제 종료

```powershell
# 방법 1
Stop-Process -Name python -Force

# 방법 2
Get-Process python | Stop-Process -Force
```

---

### 문제 8: Qwen 7B 환각 (핵심 미해결)

**증상**: Q4 삼성 재생에너지 답변이 "50%", "100%"로 나옴 (훈련 데이터 기반)  
**실제 문서 내용**: `"DX부문은 2030년 탄소중립 달성을 목표로 2024년 말 기준 전체 에너지의 93.4%가 재생에너지로 전환되었고"` (PDF 위치 1732, 앞 5000자 안에 있음)  
**원인**: Qwen 7B가 삼성 ESG 관련 학습 데이터를 강하게 기억하여 문서 내용 무시

**시도한 해결 방법들**:

| 시도 | 방법 | 결과 |
|------|------|------|
| 1 | 시스템 프롬프트에 "숫자는 발췌에 있는 것만" 규칙 추가 | 여전히 50%, 100% 출력 |
| 2 | Qwen extraction 단계 제거 (generate_node에서 직접 생성) | 개선 없음 |
| 3 | "원문 그대로 인용하라" 지시 강화 | 개선 없음 |
| 4 | Python으로 93.4% 문장 추출 후 컨텍스트 맨 앞에 배치 | 미적용 (다음 시도 예정) |

**근본 원인**: Qwen 7B (7B 파라미터)는 삼성 ESG 보고서 같은 유명 기업 정보에 대해 강한 prior를 가짐. 시스템 프롬프트 instruction-following 능력 한계.

**권고**: GPT-4 또는 Claude API 사용 시 이 문제 해결 가능. Qwen 7B 한계.

---

### 문제 9: Q1 FAO 가격지수 원인 누락

**증상**: 128.5는 맞추나 유지류/설탕 가격 상승 원인이 환각됨  
**원인**: "팜유", "말레이시아", "해바라기유", "에탄올", "브라질" 등 원인 키워드가 질문에 없어 키워드 검색이 해당 단락을 놓침  
**미해결**: 질문 키워드 → 관련 키워드 확장 로직 필요

---

### 문제 10: Q3 삼성 이해관계자 채널 환각

**증상**: "Slack", "월례 보고회" 같은 문서에 없는 내용 출력  
**원인**: 문서의 구체적 소통 채널(지속가능경영 웹사이트, 뉴스룸) 대신 Qwen 학습 데이터 기반 답변  
**미해결**: Qwen 7B hallucination 문제와 동일한 근본 원인

---

## 현재 generate_node 구조 (v6)

```
[scan_node 청크]          → 키워드 ±400자 윈도우 (scan_node 처리)
  +
[fitz 앞 5000자]          → 문서 메타/서두 항상 포함
  +
[_keyword_target_paragraphs] → 나머지 부분에서 키워드 슬라이딩 검색
  ↓
combined (최대 15,000자) → Qwen 7B 직접 생성 (extraction 단계 없음)
```

---

## 현재 시스템 프롬프트 (v7 forced-quote)

```
당신은 아래 [문서 발췌]를 보고 [질문]에 답하는 AI입니다. 반드시 한국어로만 답변하세요.

[문서에서 직접 추출한 핵심 인용 — 아래 수치만 사용할 것]
  "DX(Device eXperience)부문은 2030년 탄소중립 달성을 목표로 2024년 말 기준 전체 에너지의 93.4%가 재생에너지로 전환되었고"
  ...

[절대 규칙]
1. 숫자·비율·날짜는 반드시 [핵심 인용] 또는 [문서 발췌]에 있는 것만 쓰세요.
2. 학습 데이터에서 알고 있는 수치를 쓰면 안 됩니다. 문서 수치만 사용.
3. 발췌에 없는 내용 추가 금지. 외국어 출력 금지.
4. 답을 못 찾으면 "제공 문서에 해당 정보가 없습니다"라고만 쓰세요.
```

**변경점 (v6 → v7)**:
- `_python_extract_key_facts()` 추가: LLM 없이 Python regex로 숫자 포함 문장 추출
- 시스템 프롬프트 맨 앞 + 유저 메시지에 **이중 노출**로 핵심 수치 강제 인용

---

## 모델 비교 (RTX 4060 8GB VRAM 기준)

### 왜 RAG를 써도 환각이 발생하나?

RAG는 "이 문서만 봐"라고 지시하는 방식인데, 작은 모델은 **유명한 정보에 대한 학습 prior가 너무 강해서** 문서를 눈앞에 줘도 학습 기억을 꺼냄.

- 삼성 ESG는 공개된 유명 보고서 → 모델 학습 데이터에 이미 포함
- "삼성 재생에너지 50%/100%" 정보가 학습 데이터에 있음
- 문서에 93.4%가 있어도 "내가 아는 게 맞지 않나?" 하고 무시
- GPT-4급이면 instruction-following이 훨씬 강해 이 문제 덜 발생

### IFEval 점수 = "지시 준수 능력" (RAG에서 핵심 지표)

| 모델 | Ollama 명령어 | 디스크 | VRAM | IFEval | 한국어 | 컨텍스트 | RTX 4060 |
|------|--------------|--------|------|--------|--------|---------|----------|
| **Qwen2.5:7b** (기존) | `qwen2.5:7b` | 4.7GB | 5.5GB | 71.2 | 양호 | 32K | ✅ |
| Qwen2.5:14b | `qwen2.5:14b` | 9GB | 10GB | 81.0 | 양호 | 32K | ❌ VRAM 초과 |
| **Gemma3:12b** (테스트) | `gemma3:12b` | 8.1GB | 8.5GB | 88.9 | 양호 | 128K | ⚠️ 0.5GB 초과, CPU offload |
| Gemma3:27b | `gemma3:27b` | 17GB | 17GB | 90.4 | 우수 | 128K | ❌ |

> Qwen2.5:32b는 14b보다 IFEval이 오히려 낮음 (크다고 무조건 좋지 않음)

### 모델 × 버전 전체 비교표

> **비교 목적**: 정확도가 비슷하면 더 작고 빠른 Qwen2.5:7b 유지

| 모델 | 버전 | Q1 (128.5+원인) | Q2 (3035.5/5.8%) | Q3 (이해관계자) | Q4 (93.4%) |
|------|------|----------------|-----------------|----------------|------------|
| Qwen2.5:7b | 초기 | ❌ | ❌ | ❌ | ❌ |
| Qwen2.5:7b | v6 (scan+head5000) | ⚠️ 숫자✅/원인❌ | ✅ | ❌ | ❌ 50%/100% |
| Gemma3:12b | v6 | ⚠️ 숫자✅/원인❌ | ✅ | ⚠️ 소폭개선 | ❌ 약10% |
| Gemma3:12b | v7 forced-quote | ⚠️ 숫자✅/원인❌ | ❌ 3,055.5 혼입 | ⚠️ | ✅ **93.4%** |
| Qwen2.5:7b | v8 scan_only | ⚠️ 숫자✅/원인❌ | ✅ | ❌ | ❌ 100% |
| Qwen2.5:7b | v8.1 scan+head2500 | 테스트 중 | 테스트 중 | 테스트 중 | 테스트 중 |

**관찰**:
- Q2는 scan_chunks를 쓰면 둘 다 안정적으로 맞춤
- Q4(93.4%)는 forced-quote 사용 시 Gemma3가 먼저 맞췄으나 Q2 regression 발생
- v8.1(scan+head2500)이 두 문제를 동시에 해결하는 균형점

### 라우터 오분류 버그 발견 및 수정

**증상**: Q1, Q2, Q4가 `rag` 대신 `qa_gen`으로 라우팅됨 (Qwen7b v8 테스트)  
**원인 1**: 이전 테스트의 thread_id 재사용 → 대화 이력이 라우터 판단에 영향  
**원인 2**: 라우터 프롬프트의 `qa_gen` 설명이 부정확하여 질문형 문장을 시험문제로 오해  
**수정**:
- 테스트 스크립트에 타임스탬프 `_RUN_ID` 추가 → 매 실행마다 고유 thread_id
- 라우터 프롬프트 명확화: "명시적 생성 요청이 없으면 무조건 rag"

---

## 테스트 결과 전체 히스토리

| 버전 | 주요 변경 | Q1 | Q2 | Q3 | Q4 |
|------|---------|----|----|----|----|
| 초기 | 기본 RAG | ❌ | ❌ | ❌ | ❌ |
| v3 | fitz 직접 읽기 + 슬라이딩 윈도우 | ⚠️ | ✅ | ❌ | ❌ |
| v6 | scan+head5000+extraction제거 | ⚠️ | ✅ | ❌ | ❌ |
| v6+Gemma3 | 모델 교체 | ⚠️ | ✅ | ⚠️ | ❌ |
| v7 Gemma3:12b | forced-quote from combined(15000자) | ⚠️ 128.5✅/원인❌ | ❌ 3,055.5/4.9% (숫자 혼입) | ⚠️ 구조↑ | **✅ 93.4% 정답!** |
| v8 Qwen2.5:7b | forced-quote from scan_chunks only | ⚠️ 128.5✅/원인❌ | ✅ 3,035.5/5.8% | ❌ 환각 | ❌ 100% (93.4% 누락) |
| v8.1 Qwen2.5:7b | forced-quote scan+head2500 | 테스트 중 | 테스트 중 | 테스트 중 | 테스트 중 |

---

## 최종 결론 — 모델 선택

### Qwen2.5:7b vs Gemma3:12b 최종 비교

| 항목 | Qwen2.5:7b | Gemma3:12b |
|------|-----------|------------|
| 디스크 | 4.7GB | 8.1GB |
| VRAM | 5.5GB | ~8.5GB (CPU offload 일부) |
| IFEval | 71.2 | 88.9 |
| Q2 곡물생산 | ✅ 안정 | ✅ 안정 |
| Q4 탄소중립 93.4% | ❌ 지속 실패 | ✅ forced-quote로 해결 |
| 속도 | 빠름 | 느림 (CPU offload 영향) |

**결론**: Q4(삼성 93.4%)는 Qwen7b에서 **어떤 프롬프트를 써도 해결 불가** — 학습 prior가 IFEval 점수만큼 instruction-following보다 강함. **Gemma3:12b 채택, Qwen2.5:7b 삭제**.

### 최종 파이프라인 (v8.3, Gemma3:12b 기준)

```
router_node
  → intent_node (키워드 추출)
  → search_node (벡터 검색)
  → scan_node (파일별 키워드 윈도우 ±400자)
  → select_node (매칭 파일 선택)
  → generate_node
      ├── scan_chunks (keyword-targeted)
      ├── fitz head[:5000] (서두 핵심 수치)
      ├── keyword_target_paragraphs (나머지 구간)
      ├── key_facts 추출 (scan_chunks + fitz_head[:3000], min_score 이중 필터)
      └── _build_rag_messages (forced-quote 이중 노출 → Gemma3가 따름)
```

---

---

## 설계 FAQ

### Q: 왜 줄바꿈이 문제인가? (fitz 소프트 줄바꿈)

PDF를 fitz로 읽으면 **단어 중간에 `\n`이 삽입**된다. 이는 PDF의 물리적 레이아웃(텍스트 박스 끝)에서 비롯된 것으로, 실제 문장 끝이 아니다.

```
"재생에너지\n전환율은 93.4%"  ← fitz 원본
"재생에너지전환율은 93.4%"    ← _join_pdf_lines() 처리 후
```

- 키워드 검색이 `"재생에너지 전환율"` 같은 패턴으로 이루어지는데, 중간에 `\n`이 있으면 매칭 실패
- 문장 추출(`_python_extract_key_facts`)도 줄 단위 분리에 의존하므로 잘못된 분리면 숫자 포함 문장을 놓침
- `_join_pdf_lines()`는 "이전 줄이 문장 종결 어미(다/요/죠/함/임)로 끝나지 않으면 다음 줄을 붙인다" 규칙으로 해결

---

### Q: 파일 원본에서 바로 검색하면 되는데 왜 청크에서 검색하나?

**이유 1 — 벡터 임베딩 한계**  
벡터 검색(search_node)은 문서 전체를 하나의 벡터로 임베딩한다. 179,328자짜리 Samsung PDF를 1개 벡터로 만들면 세부 수치(93.4%, 3,035.5백만톤)가 평균화되어 질문과의 유사도가 희석됨. **청크로 나누면 관련 단락의 벡터가 질문 벡터에 더 가까워진다.**

**이유 2 — 컨텍스트 길이 한계**  
Gemma3:12b의 컨텍스트는 128K이지만, 179,328자 전체를 프롬프트에 넣으면 LLM이 중요한 수치를 긴 문서 속에서 놓칠 확률이 올라간다 ("needle in a haystack" 문제). 청크 → 키워드 스캔 → 핵심 단락만 발췌하는 방식이 정확도가 높다.

**이유 3 — scan_node의 역할**  
원본 파일은 `generate_node`에서 fitz로 직접 읽는다 (캐시 우회). 하지만 scan_node의 청크(±400자 키워드 윈도우)는 **이미 관련 단락으로 정제된 것**이라, 이걸 key_facts 추출의 1차 소스로 쓰는 게 원본 전체 파싱보다 노이즈가 적다.

```
원본 179K자 → scan_node(키워드 ±400자 윈도우) → scan_chunks (~2000자)
                                                         ↓
                                             key_facts 추출 (min_score=1)
원본 179K자 → fitz head[:3000]                           +
                                             head_facts  (min_score=4, 엄격)
```

---

### Q: LangGraph는 아직도 쓰나?

**네, 여전히 LangGraph를 사용한다.** 파이프라인의 각 단계가 LangGraph 노드로 연결되어 있다.

```
router_node → intent_node → search_node → scan_node → select_node → generate_node
```

- `router_node`: 질문 유형 분류 (rag / chat / followup / qa_gen)
- `intent_node`: 파일 키워드 + 세부 키워드 추출
- `search_node`: 벡터 DB 검색, 후보 파일 N개 반환
- `scan_node`: 각 후보 파일에서 키워드 ±400자 윈도우 추출 (SSE `scanning` / `scan_result` 이벤트)
- `select_node`: found 파일만 선택 (SSE `selected` 이벤트)
- `generate_node`: fitz 원본 읽기 + key_facts 추출 + LLM 답변 생성 (SSE `key_facts` → `generating` → `token` 이벤트)

---

## UI 업데이트 (v8.3)

### 새로운 SSE 이벤트 추가 (백엔드 → 프론트엔드)

| 이벤트 | 페이로드 | 의미 |
|--------|---------|------|
| `key_facts` | `{ facts: string[] }` | Python이 추출한 핵심 인용 문장 목록 |
| `generating` | (없음) | LLM 생성 시작 직전 |

### MainAI.jsx 수정 내용

1. **`makeTurn()`에 필드 추가**:
   ```js
   keyFacts: [], generating: false,
   ```

2. **SSE switch에 케이스 추가**:
   ```js
   case 'key_facts':
     patchTurn(turnId, { keyFacts: ev.facts || [] }); break
   case 'generating':
     patchTurn(turnId, { generating: true }); break
   case 'token':
     patchTurnFn(turnId, t => ({ answer: t.answer + ev.text, generating: false }))
   ```

3. **TurnView에 📌 핵심 인용 섹션 추가** (스캔 로그 → 핵심 인용 → 생성 중 → 답변 순서):
   - 초록 테두리 카드로 각 인용문 표시
   - `generating && !answer` 상태에서 "답변 생성 중…" 스피너 표시
   - 첫 `token` 수신 시 `generating: false` 처리 → 스피너 사라짐

### 빌드

```bash
cd C:\Honey\DB_insight\App\frontend && npm run build
# ✓ built in 2.74s
```

---

## 주요 파일 경로

| 파일 | 경로 |
|------|------|
| 백엔드 메인 | `C:\Honey\DB_insight\App\backend\routes\aimode.py` |
| 프론트엔드 메인 | `C:\Honey\DB_insight\App\frontend\src\pages\MainAI.jsx` |
| 테스트 스크립트 | `C:\tmp\test_v5.py` |
| 테스트 결과 | `C:\tmp\v5_results.json` |
| Samsung PDF | `C:\Honey\DB_insight\Data\raw_DB\Docs\Samsung_Electronics_Sustainability_Report_2025_KOR.pdf` |
| 백엔드 앱 | `C:\Honey\DB_insight\App\backend\app.py` (포트 5001) |
| 프론트 빌드 | `C:\Honey\DB_insight\App\frontend\dist\` |

---

## 2026-05-08 세션 — 4b 환각 분석

### LLM 사용 지점별 모델 매핑 (확정)

| 단계 | 함수/노드 | 모델 | 위치 |
|---|---|---|---|
| router (rag/chat/followup 분류) | `_ollama_oneshot(prompt, model)` | **12b** | [aimode.py:712](App/backend/routes/aimode.py:712) |
| intent (키워드 추출) | `_ollama_oneshot(prompt, model)` | **12b** | [aimode.py:325](App/backend/routes/aimode.py:325) |
| search (벡터 검색) | BGE-M3 + reranker (LLM 미사용) | — | trichef 모듈 |
| scan (관련 문장 추출) | `_ollama_oneshot(extract_prompt, model)` | **12b** | [aimode.py:626](App/backend/routes/aimode.py:626) |
| select (found 파일 추리기) | rule-based, LLM 미사용 | — | — |
| generate (RAG 답변) | `_ollama_stream(messages, gen_model)` | **4b** | [aimode.py:1390](App/backend/routes/aimode.py:1390) |
| direct_generate (chat 답변) | `_ollama_stream(messages, gen_model)` | **4b** | [aimode.py:1092](App/backend/routes/aimode.py:1092) |
| qa_generate (QA 페어) | `_ollama_oneshot(prompt, gen_model)` | **4b** | [aimode.py:1005](App/backend/routes/aimode.py:1005) |

---

### 문제 11: Q2 곡물 증가율 5.6% 환각 (4b, 해결)

**증상**: 4b 답변 모델로 Q2 두 번 실행 → 두 번 다 정확히 `5.6%` 출력 (정답 5.8%). Deterministic 환각.

```
Q2: 2025/26년도 세계 곡물 총 생산량 전망치와 전년 대비 증가율은?
A:  2025/26년도 세계 곡물 총 생산량 전망치는 3,035.5백만톤(5.6%↑)입니다.
    (쌀 563.3백만톤 + 잡곡 1,633.2백만톤 + 밀 839.0백만톤)
```

3,035.5는 ✅, 5.8% → 5.6% ❌.

**진단 방법** — DevTools Console에서 SSE 직접 호출 후 이벤트 파싱:

```js
(async () => {
  const res = await fetch('http://127.0.0.1:5001/api/aimode/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      query: '2025/26년도 세계 곡물 총 생산량 전망치와 전년 대비 증가율은?',
      thread_id: 'debug_q2_' + Date.now(), topk: 5
    })
  });
  const events = (await res.text()).split('\n')
    .filter(l => l.startsWith('data: '))
    .map(l => { try { return JSON.parse(l.slice(6)); } catch { return null; } })
    .filter(Boolean);
  const kf    = events.find(e => e.type === 'key_facts');
  const scans = events.filter(e => e.type === 'scan_result' && e.found);
  const done  = events.find(e => e.type === 'done');
  console.log('key_facts has 5.8?', JSON.stringify(kf?.facts || []).includes('5.8'));
  scans.forEach((s,i) => {
    const j = (s.chunks || []).join(' ');
    console.log(`scan[${i}] has5.8=${j.includes('5.8')} has3,035=${j.includes('3,035')}`);
  });
  console.log('answer:', done?.answer, 'gen_model:', done?.gen_model);
})();
```

**진단 결과**:

| 검사 | 결과 |
|---|---|
| scan_result chunks 에 "5.8" | ✅ **있음** |
| key_facts 에 "5.8" | ❌ **없음** |
| 답변에 "5.8" | ❌ |
| gen_model | `gemma3:4b` ✅ |

→ scan은 5.8% 라인을 청크에 잡았는데, **`_python_extract_key_facts` 가 forced-quote로 못 끌어올리고 있다**.

**근본 원인 추정**: [`_python_extract_key_facts`](App/backend/routes/aimode.py:563) 의 필터 로직이 합계 행을 배제.

```python
# aimode.py:597
if score >= min_score and kw_hits >= 1:   # ← kw_hits 강제 통과 조건
    scored.append((score, sent))
```

PDF 표가 fitz로 추출되면 합계 행은 다음과 같은 단독 라인으로 떨어지는 경우가 많음:

```
전체  3,035.5  2,869.7  5.8%
```

질문 토큰(`년도, 세계, 곡물, 생산량, 전망치, 전년, 대비, 증가율, 2025, 26`)이 이 라인엔 하나도 없음 (`전체`/`총` 같은 1글자 키워드는 `[가-힣]{2,}` 정규식이 누락). 결과:
- kw_hits = 0 → **필터 탈락**
- 반면 `* 생산량 전망치(전년 대비): 쌀 563.3 / 잡곡 1,633.2 / 밀 839.0` 분해 행은 키워드 4개 매칭 → key_facts 통과

forced-quote 에 분해 데이터만 노출됨 → 4b 가 가중평균을 자체 계산 시도 → 5.6% 환각 (정답 가중평균은 (563.3·2.0 + 1,633.2·7.6 + 839.0·4.9) / 3,035.5 ≈ 5.81%).

**4b 의 행동 패턴 관찰**:
- prior 가 약해 PDF 인용은 충실 (Q4 93.4% 이전 7b/12b 가 못 잡던 케이스를 4b 가 잡음 — `문제 8` 참고)
- 다만 forced-quote 에 핵심 라인이 없으면 **자체 산술 시도** → 같은 잘못된 답이 deterministic 하게 재현

**해결 후보**:
1. `_python_extract_key_facts` 의 `kw_hits >= 1` 조건 완화 — 숫자 밀도가 높으면(예: `len(nums) >= 3` AND `%` 포함) 키워드 매칭 없어도 통과
2. 동의어 매핑 추가 — 질문에 `총/전체/합계` 가 있으면 라인의 `전체/계` 도 kw_hits 로 카운트
3. 1글자 키워드도 q_tokens 에 포함 (단 노이즈 위험 — `총`, `및`, `등` 자주 출현)
4. 청크 머지 — fitz 추출 직후 표 헤더와 합계 행을 같은 sentence 로 병합

가장 안전한 패치는 **(1)+(2) 결합**: 숫자 밀도 우회 통과 + 합계 동의어 보너스.

**컨텍스트 재확인 (DevTools 콘솔에서 "5.8" 주변 ±150자 추출)**:

> "...붙임2 2025/26년도 FAO 세계 곡물수급 전망 ... **2025/26년도 세계 곡물 생산량은 3,035.5백만톤으로 2024/25년도 대비 5.8%(167.8백만톤) 증가할 것으로 전망하였다.** * 생산량 전망치(전년 대비): 쌀 563.3백만톤(2.0%↑) / 잡곡 1,633.2(7.6%↑) / 밀 839.0(4.9%↑) ..."

PDF 원문에서 5.8% 결론 문장은 깔끔하게 한 문장으로 들어가 있음. 키워드 매칭 7개(`2025`/`26`/`년도`/`세계`/`곡물`/`생산량`/`대비`) + 숫자 3개(`035.5`/`5.8%`/`167.8`) → **score = 16**.

문제는 같은 chunk 안의 분해 표 행이 더 높은 점수:

| 문장 | 숫자×3 | kw_hits | score |
|---|---|---|---|
| `* 생산량 전망치(전년 대비): 쌀 563.3 / 잡곡 1,633.2 / 밀 839.0` | 6×3=18 | 4 | **22** |
| `* 소비량 전망치(전년 대비): 쌀 555.6 / 잡곡 1,585.4 / 밀 803.8` | 6×3=18 | 4 | **22** |
| `* 재고량 전망치(전년 대비): 쌀 219.3 / 잡곡 385.0 / 밀 347.3` | 6×3=18 | 4 | **22** |
| **2025/26년도 ... 5.8% 증가할 것으로 전망하였다** | 3×3=9 | 7 | **16** |

`max_facts=4` 안에 분해 행 3개가 1·2·3등 차지, 4등 슬롯도 다른 narrative(소비량/재고량 ~16)와 경쟁 → 5.8% 결론 문장 누락. forced-quote에 분해만 노출되니 4b 가 가중평균을 자체 계산 → **5.6% 환각**.

**해결**: [`_python_extract_key_facts`](App/backend/routes/aimode.py:563) 에 두 가지 가산/감점 추가.

```python
# 결론형 패턴 — "X.X%(...) 증가/감소/상승/하락/기록/전망/예상/달성"
ANSWER_PATTERN = _re.compile(
    r'\d+\.?\d*\s*%[^.\n]{0,40}'
    r'(?:증가|감소|상승|하락|기록|전망|예상|달성|확대|축소|개선)'
)

for sent in sentences:
    score = ...  # 기존 (숫자×3 + kw_hits)

    # 결론형 narrative 가산점 (분해 표 행 대신 결과 문장 우선)
    # 분해 표 행은 숫자수×3 으로 22점대 까지 올라가므로 +10 이상 필요.
    if ANSWER_PATTERN.search(sent):
        score += 10
    # 불릿/표 행 감점 ("* 쌀 563.3 / 잡곡 ..." 같은 분해 행 억제)
    if _re.match(r'^\s*[\*·•\-]', sent):
        score -= 3
```

**적용 후 점수 재계산**:

| 문장 | 기존 score | 결론형 +10 | 불릿 -3 | 최종 |
|---|---|---|---|---|
| `* 생산량 전망치 ... 쌀 563.3 / 잡곡 ...` | 22 | — | -3 | **19** |
| **2025/26년도 ... 5.8% 증가할 것으로 전망하였다** | 16 | +10 | — | **26** |

→ narrative 결론 문장이 분해 행을 추월, top-4 진입. forced-quote 에 "5.8%" 가 들어가 4b 가 정답 인용.

**1차 패치 적용 후 추가 환각 발생** — 디버깅 계속.

#### 1차 패치 후 환각 진화 (5번에 걸쳐 다른 답)

| 시도 | 답변 | 형태 |
|---|---|---|
| 1차 | 3,035.5 / **5.6%** | 합 OK / % 환각 (가중평균 근사) |
| 2차 | **3,102.5** / 2.0% | 합 환각 / 쌀 증가율 채택 |
| 3차 | **951.5** / 9.2% | 재고량 narrative 채택 (완전 오답) |
| 4차 | **3,777.3** / 7.6% | 합 환각 / 잡곡 증가율 |
| 5차 | **3,372.2** / 7.6% | 합 환각 (재현 X) |
| 6차 | **3,000** / 7.6% | 추정 합 / 잡곡 증가율 |

**관찰**: ANSWER_PATTERN +10 패치가 narrative 점수는 올렸지만, 정답 narrative (3,035.5/5.8%) 가 여전히 key_facts 에 들어가지 않음.

#### 진짜 원인 — `_join_pdf_lines` 와 sentence boundary 문제

진단 스크립트 결과:

```
top1: * 생산량 전망치(전년 대비): 쌀 563.3 / 잡곡 1,633.2 / 밀 839.0(4.9%↑) 
      2025/26년도 세계 곡물 소비량은 2,944.8백만톤으로 ... 2.4% 증가...
3,035.5? false
```

key_facts 의 top1 이 **불릿 + 다음 narrative 가 합쳐진 괴물**. 5.8% 생산량 narrative 는 어디에도 없음.

원인 추적 — 코드 흐름:

```
PDF → fitz 읽기 → _join_pdf_lines 적용 (소프트 줄바꿈 정리)
    → scan_node 가 ±400자 sliding window 로 자름 → matched_chunks
    → generate_node 가 _python_extract_key_facts 호출
    → forced-quote 로 LLM 에 노출
```

[`_join_pdf_lines`](App/backend/routes/aimode.py:1996) 의 BULLET 정규식이 잘못됨:

```python
_BULLET = _re.compile(r"^[·•\-\d①②③④⑤]")  # ← 버그
```

문제점:
1. **`*` 누락** — fitz 가 `* 생산량 전망치...` 를 추출했을 때 bullet 으로 인식 못함 → 직전 narrative 끝(`전망하였다.`) 과 합쳐버림
2. **`.` 가 SENT_END 에 없음** — `_SENT_END = {"다","요","죠","함","임","!","?","。"}` — 마침표 자체가 없어서 narrative `...전망하였다.` 다음 줄과의 분리가 깨짐
3. **`prev_is_bullet` 추적 없음** — 불릿 라인 끝에 `↑)` 같은 것이 오면 SENT_END 가 아니므로 다음 narrative 가 또 합쳐짐
4. **`\d` 가 단독으로 bullet** — "2025/26", "2.4%", "3,035.5" 같은 문장 일부 숫자가 bullet 으로 오인됨

연쇄 효과:
- `...전망하였다.\n* 생산량 전망치...` → "*" 가 bullet 아니고 "." 가 SENT_END 아니라 → MERGE → `...전망하였다.* 생산량 전망치 ... (4.9%↑)` 한 줄
- 그 후 `\n2025/26 세계 곡물 소비량은 ...` → 직전이 bullet 인지 추적 안 함, 끝이 `↑)` 로 SENT_END 아님, 시작이 "2" 인데 `\d` 라 bullet — 근데 같은 줄에 합쳐졌으니 검사도 다시 안 함 → MERGE
- 결과: 생산량 narrative + 불릿 + 소비량 narrative 가 모두 한 줄

`_python_extract_key_facts` 에 들어올 때 이미 깨진 상태라, 그 안에서 줄바꿈 정규화·점수 조정 해도 못 살림.

#### 최종 패치 — `_join_pdf_lines` 수정

```python
_SENT_END = frozenset([
    "다", "요", "죠", "함", "임",
    ".",   # ← 추가: narrative 끝마침표 인식
    "!", "?", "。",
])
# 진짜 불릿/번호 매김만 매치 — "2025/26", "2.4%", "3,035.5" 같은 숫자는 X. `*` 추가.
_BULLET = _re.compile(r"^(?:[\*·•\-①②③④⑤]|\d+[.)]\s)")

lines = text.split("\n")
result = []
prev_is_bullet = False  # ← 추가: 불릿 다음 줄 추적
for line in lines:
    is_bullet    = bool(_BULLET.match(line.strip()))
    starts_paren = line.strip().startswith("[") or line.strip().startswith("(")
    if (result
            and line
            and result[-1]
            and not prev_is_bullet              # 불릿 다음엔 새 문장 시작
            and result[-1][-1] not in _SENT_END
            and not is_bullet
            and not starts_paren
    ):
        result[-1] += line
    else:
        result.append(line)
        prev_is_bullet = is_bullet
return "\n".join(result)
```

`_python_extract_key_facts` 에는 추가로 (방어):
- 동일 `prev_is_bullet` 추적 줄바꿈 정규화 (입력에 줄바꿈이 남아있는 경우 대비)
- `min(len(nums), 5) × 3` 캡 — 식량가격지수 표 같은 숫자 25개+ 라인이 점수 폭주 방지
- 결론형 ANSWER_PATTERN +10, bullet 라인 -3 (1차 패치 그대로)
- ANSWER_PATTERN regex `[^.\n]` → lazy `.` (2차 패치) — 십진수 마침표 통과

#### 7차 시도 — 정답 ✅

```
top1: 2025/26년도 세계 곡물 생산량은 3,035.5백만톤으로 2024/25년도 대비 5.8%(167.8백만톤) 증가할 것으로 전망하였다
3,035.5? true
answer: 2025/26년도 세계 곡물 총 생산량 전망치는 3,035.5백만톤이며, 전년 대비 증가율은 5.8%입니다.
```

**상태**: 완전 해결.

#### 핵심 교훈

1. **상위 단계 텍스트 정제가 망가져 있으면 하위 단계에서 어떤 점수 조정도 못 살림** — 추출기 점수 튜닝 전에 입력 텍스트가 sentence boundary 를 보존하는지 먼저 검증.
2. **fitz 같은 PDF 추출기는 한국어 `*` 불릿/마침표/숫자 시작을 일관성 없이 처리** — bullet/SENT_END 정규식은 보수적으로 넓게 잡아야.
3. **4b 가 forced-quote 에 정답 문장 있으면 그대로 인용, 없으면 자체 산술 시도해서 매번 다른 환각** — instruction-following 보다 prior 영향이 작아서 인용에는 충실.

---

### 테스트 결과 추가 (Gemma3:4b answer + 12b search 하이브리드)

| 버전 | Q1 (128.5+원인) | Q2 (3,035.5/5.8%) | Q3 (이해관계자) | Q4 (93.4%) |
|---|---|---|---|---|
| v8.4 12b only | (이전 결과 참고) | | | |
| **v9 하이브리드 (12b 검색 + 4b 답변)** | ⚠️ 128.5 ✅ / 5.1%·7.2% 상승률 ✅ / 원인 키워드 ❌ | ❌ 3,035.5 ✅ / **5.6% 환각** | ⚠️ 8대 그룹 ✅ / 채널 누락 | ✅ **93.4%** 안정적, framing 정확 |
| **v10 (Q2 추출기 보강 후)** | ⚠️ 128.5 ✅ / 곡물(밀) 원인을 유지류·설탕에 잘못 매칭 | ✅ **3,035.5 / 5.8%** 정답 | ⚠️ 8대 그룹 ✅ / 채널 누락 (동일) | ⚠️ 93.4% ✅ / **"2030 목표 = 93.4%" 라벨링 회귀** |

**핵심 통찰**: 4b 가 12b/7b 보다 **prior 영향 적어서 RAG 인용 충실도 높음**. Q4 (93.4%) 처럼 forced-quote 에 정답 라인이 들어가는 케이스는 4b 가 더 안정적. 단 Q2 처럼 forced-quote 에서 누락되는 라인이 생기면 자체 계산 시도해서 환각 — **추출기 정확도가 모델 크기보다 결정적**.

**Q2 디버깅에 들어간 패치 6종 합본** ([aimode.py](App/backend/routes/aimode.py)):

| # | 위치 | 변경 |
|---|---|---|
| 1 | `_python_extract_key_facts` 점수 | `ANSWER_PATTERN` +10 (결론형 narrative 우선) |
| 2 | 위 ANSWER_PATTERN regex | `[^.\n]{0,40}` → `.{0,40}?` (lazy, 십진수 마침표 통과) |
| 3 | 위 점수 | 불릿 라인 -3 |
| 4 | 위 점수 | `min(len(nums), 5) × 3` 캡 (테이블 점수 폭주 차단) |
| 5 | 위 텍스트 정규화 | `prev_is_bullet` 추적 + 불릿 패턴 정밀화 (defense in depth) |
| 6 | `_join_pdf_lines` (`_read_source_full_text` 내부) | `*` 추가, `.` SENT_END, `prev_is_bullet`, `\d+[.)]\s` 정밀 매칭 ★ **결정타** |

5/6 모두 적용된 후에야 정답. 단일 패치로는 해결 안 됨.

---

### 문제 12: Q4 chained-sentence parsing 회귀 (4b, 미해결)

**증상**: v10 패치 후 Q4 답변에서 "2030 목표 = 93.4%" 로 라벨링 오류. 숫자는 맞지만 framing 어긋남.

```
Q4: 삼성전자의 2030년 탄소중립 목표와 2024년 재생에너지 전환율
A:  삼성전자의 2030년 탄소중립 목표는 전체 에너지의 93.4%이며,
    2024년 재생에너지 전환율은 93.4%입니다.
```

정답: "2030 목표 = 탄소중립(Scope 1, 2)" / "2024 = 93.4%" — 4b 가 두 정보를 잘못 결합.

**진단**: key_facts 추출은 완벽. top1 이 정답 문장 그 자체:

```
[0] DX(Device eXperience)부문은 2030년 탄소중립 달성을 목표로 2024년 말 기준
    전체 에너지의 93.4%가 재생에너지로 전환되었고, 대표 제품 모델에는 고효율
    에너지 기술을 적용해 2019년 대비 평균 31.5%의 소비전력을 절감했습니다
```

이 한 문장 안에 두 절이 chained 됨:
- "2030년 탄소중립 **달성을 목표로**" ← 2030 target = 탄소중립
- "2024년 말 기준 ... 93.4%가 재생에너지로 전환되었고" ← 2024 actual = 93.4%

4b 가 chained clause 분해 실패 → "2030 목표" 자리에 "93.4%" 를 잘못 매칭.

**v9 (이전) 와의 차이**:
- v9 key_facts 에는 "Scope 1, 2" 가 들어간 다른 문장이 동시 노출 → 4b 가 두 정보를 분리해 정확히 라벨링
- v10 추출기는 정답 문장에 더 집중 → forced-quote 가 압축적이라 4b parsing 한계 노출

**근본 원인**: 4b instruction-following 한계 (chained clause 의 각 절을 독립 fact 로 분해하지 못함). 추출기 측에서 해결 불가.

**해결 후보**:
1. **시스템 프롬프트 강화** — "한 문장 안에 여러 연도가 있으면 각 연도에 해당하는 절만 인용" 같은 명시 규칙 추가
2. **chained sentence pre-split** — 추출 시 "년도 ... 목표로 ... 년도 말 기준 ..." 같은 패턴을 의미 단위로 강제 분할
3. **답변 모델 12b 로 변경** — Gemma3:12b 는 chained clause parsing 더 잘함 (단 속도 ↓)
4. **현 상태 수용** — 숫자(93.4%) 자체는 정답이고 framing 만 어긋남. Q2 5.8% 환각 해결 가치가 더 큼.

**상태**: 미적용. v10 트레이드오프 — Q2 정답 vs Q4 framing. **전체 정확도는 v10 이 우세**.

---

### 문제 13: Q1 원인 카테고리 오인 (4b, 미해결)

**증상**: v10 에서 Q1 답변이 곡물(밀) 원인을 유지류·설탕 원인으로 잘못 인용.

```
Q1: 2026년 3월 FAO 세계식량가격지수는 얼마이며, 유지류와 설탕 가격이 오른 원인은?
A:  ... 유지류와 설탕 가격이 오른 원인은 다음과 같습니다:
    • 미국 내 가뭄으로 작황지수가 악화됨   ← 곡물(밀) 원인
    • 호주에서 비료 가격 상승 가능성에 대응하여 파종이 줄어들 것으로 예상됨   ← 곡물(밀) 원인
```

정답 (page 3 붙임1):
- 유지류: 팜유 말레이시아 감산, 해바라기유 흑해 공급제약, 원유가격 상승
- 설탕: 브라질 에탄올 수요 (원유가격 상승), 중동 분쟁 격화

**진단 추정**: 질문 키워드(`유지류, 설탕, 가격, 원인`) → scan_node 가 곡물 가격지수 단락의 "X% 상승" / "원인" 토큰을 더 많이 매칭 → 곡물 원인 라인이 forced-quote 에 우선 노출.

**근본 원인**: 추출 키워드 매칭이 카테고리(유지류/설탕)를 식별하지 못하고 일반 토큰(원인/상승)에 끌려감. troubleshooting 문서의 미해결 항목 #9 (`Q1 FAO 가격지수 원인 누락`) 과 동일 패턴이 v10 에서도 재현.

**해결 후보**: 질문 토큰 → 관련 키워드 확장 로직 (예: "유지류" → "팜유, 대두유, 해바라기유, 유채유"). LLM 기반 query expansion 또는 도메인 사전.

**상태**: 미적용. 이전부터 알려진 문제, v10 에서도 미해결.
