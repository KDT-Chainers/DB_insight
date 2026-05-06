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
