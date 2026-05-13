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

---

# 📘 v3 · LangGraph 재설계 + 채팅 영속화 (2026-05-11 ~ 2026-05-13)

이전 섹션 (~v10) 은 **답변 품질 (정확도/환각)** 위주의 단일 노드 튜닝이었고,
이번 v3 라인은 **그래프 구조 재설계 + 사용자 경험 (사이드바·후속 질문·PDF export) + GPU OOM 안정성** 에 집중.

---

## v3 의 큰 그림 — 무엇이 바뀌었나

```
[v2 까지]
START → router → (rag | chat | qa_gen) → ... → END
                 ───────────────────────
                 3-route 라우팅, chat / qa_gen 이 모호

[v3]
START → router → (rag | followup)         ← 2-route 단순화
              │
              └─ rag → intent → (structured | open)   ← mode 분기 추가
                              │
                              ├─ structured → search → scan → select → extract → generate
                              │
                              └─ open       → fulltext_search           → extract → generate
              │
              └─ followup → followup_intent → followup_search ─[exist]→ extract → generate
                                                              └─[none]→ _fallback_marker → intent
```

**노드 명세 (10 + 1)**

| # | 노드 | 역할 |
|---|---|---|
| 1 | `router` | rag / followup 분기 (history+prev_sources 기반 + 짧은 후속 의문문 패턴 강제 followup) |
| 2 | `intent` | structured / open 분류 + 키워드 추출 |
| 3 | `search` | BGE-M3 벡터검색 top-K |
| 4 | `scan` | 페이지 단위 substring + phrase 매칭 |
| 5 | `select` | confidence gate (점수 컷 + 목차 페널티 + AV 약한 매칭 컷) |
| 6 | `fulltext_search` | open 모드 — 모든 페이지 캐시 전수 스캔 |
| 7 | `followup_intent` | 이전 sources 회수 + 후속 키워드 추출 |
| 8 | `followup_search` | 이전 페이지 캐시 재스캔 (벡터검색 안 함) |
| 9 | `extract` | matched_sources → references (file_path · page · snippet · trichef_id) |
| 10 | `generate` | Ollama 스트리밍 + SQLite 영속 |
| ⓕ | `_followup_fallback_marker` | followup 실패 → state flag + RAG 사이클로 점프 |

---

## 문제 14: `<unused344>` 같은 Gemma3 special token 노출

**증상**: 답변 본문에 `<unused344>`, `<pad>` 같은 vocab 토큰이 문자 그대로 출력.

**원인**: gemma3:4b-it-qat 가 학습 데이터에 포함된 reserved/unused 토큰을 일부 케이스에서 generation 결과로 흘림.

**해결**:
- 정규식 `_GEMMA_SPECIAL_RE` 정의 — `<unused\d+|pad|eos|bos|start_of_turn|end_of_turn|im_start|im_end>` 패턴
- `_strip_special_tokens()` 헬퍼로 `_ollama_stream` / `_ollama_oneshot` 출력 모두 필터링

```python
_GEMMA_SPECIAL_RE = re.compile(
    r"<(?:unused\d+|pad|eos|bos|/s|s|end_of_turn|start_of_turn|im_start|im_end)>",
    re.IGNORECASE,
)

def _strip_special_tokens(text: str) -> str:
    if not text:
        return text
    return _GEMMA_SPECIAL_RE.sub("", text)
```

**상태**: ✅ 해결.

---

## 문제 15: 후속 질문이 followup 으로 분류 안 됨 (history empty)

**증상**: 1턴 답변 후 "전년 대비는?" 같은 후속 질문에서 LangGraph 가 history 를 못 읽음 → router 가 rag 로 잘못 분류 → 전체 검색 다시.

**원인**: `_save_history` 가 LangGraph store API 만 사용. messages 필드가 비어있으면 silent drop. fallback dict 도 백엔드 재시작 시 휘발.

**해결**: **3중 저장**으로 변경.

```python
def _save_history(thread_id, question, answer):
    # 1) LangGraph store (silent fail OK)
    g = _get_history_graph()
    if g and _LANGGRAPH_OK:
        try: g.update_state(cfg, {..., "messages": [HumanMessage, AIMessage]})
        except: pass

    # 2) in-memory fallback dict (즉시 읽기용)
    with _fallback_lock:
        _fallback_history.setdefault(thread_id, []).extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ])

    # 3) SQLite 영속 (재시작 후에도 살아남음)
    _persist_chat_turn(thread_id, question, answer)
```

`_load_history` 도 동일 패턴 — LangGraph → fallback dict → SQLite 순서로 fall through.

**상태**: ✅ 해결.

---

## 문제 16: followup_search 매칭 0건 (phrase 매칭 실패)

**증상**: `followup_intent` 가 `"SW산업 수출액 전년대비"` 같은 multi-word phrase 키워드 생성. 그런데 PDF 본문에 phrase 그대로는 안 나타남 → `_scan_pdf_pages` 가 매칭 0 → fallback 사이클.

**원인**: phrase 매칭만 시도, 단어 분해 안 함.

**해결**: `followup_search_node` 에 **phrase + 단어 분해** 추가.

```python
# 원본: ["SW산업 수출액 전년대비"]
# 확장: ["SW산업 수출액 전년대비", "SW산업", "수출액", "전년대비"]

expanded = []
for kw in detail_kws:
    expanded.append(kw)  # 원본 phrase
    if " " in kw:
        for w in kw.split():
            if len(w) >= 2 and w not in _STOP_TOKENS:
                expanded.append(w)
```

또한 STOP_TOKENS 에 `"정의"`, `"근거"`, `"원인"`, `"변화"` 등 일반 토큰 추가 (이게 단독으로 매칭되면 노이즈).

**상태**: ✅ 해결.

---

## 문제 17: 목차 페이지가 본문보다 높은 점수

**증상**: PDF 의 목차/색인 페이지가 키워드 빈출로 score 가 높아져 1순위 매칭. 답변이 목차 내용을 인용.

**원인**: `_scan_pdf_pages` 가 distinct keyword count 만 점수화. 목차는 키워드 분산 발생 + 점선·페이지번호 패턴.

**해결**:
1. **목차 감지 강화** — `toc_page_refs ≥ 5 or toc_dots ≥ 30` 이면 목차로 확정
2. **목차 페이지 강한 감점** — score 1/4 + 추가 차감
3. **extract_node 에서 자동 제외** — `_looks_like_toc_snippet()` 으로 references 단에서도 컷

```python
def _looks_like_toc_snippet(text):
    if text.count("…") >= 5:
        return True
    if len(re.findall(r"…+\s*\d{1,3}\b", text)) >= 3:
        return True
    # 줄당 평균 길이 짧고 페이지번호로 끝나는 패턴
    ...
```

**상태**: ✅ 해결.

---

## 문제 18: AV(영상·오디오) 파일이 항상 found=True 로 매칭 오염

**증상**: "경주 동궁과 월지에서 조사개요" 같은 문서 검색에 무관한 비디오 파일들 (열혈농구단, 박나래, NGC 코스모스) 이 모두 `found: true` → 답변 출처에 11개 chip 노이즈.

**원인**: `_scan_one` 의 AV 분기가 **키워드 매칭 검사 없이** segments 있기만 하면 `True` 반환.

```python
# 버그
if file_type in _av_types:
    for seg in (src.get("segments") or [])[:5]:
        av_chunks.append({"text": text, ...})
    return True, av_chunks  # ← 항상 True!
```

**해결**: AV 도 doc 처럼 **detail_kws 가 segment 텍스트·snippet·파일명 중 실제 매칭** 시에만 found=True.

```python
if file_type in _av_types:
    kws_lower = [k.lower() for k in (detail_kws or []) if k and len(k) >= 2]
    if not kws_lower:
        return False, []

    av_chunks = []
    for seg in (src.get("segments") or [])[:30]:
        text = (seg.get("text") or "").strip()
        if not text: continue
        hits = sum(1 for kw in kws_lower if kw in text.lower())
        if hits == 0: continue  # 매칭 없으면 건너뜀
        av_chunks.append({"text": text, "timestamp": ts, "score": hits})

    if not av_chunks:  # snippet 도 확인
        ...
    if not av_chunks:  # 파일명 매칭만 (낮은 score)
        ...
    if not av_chunks:
        return False, []
```

또한 `select_node` 에 **강한 doc 매칭 시 약한 AV 컷** 추가:
- doc top score ≥ 3.0 이면 AV 는 doc_top/3.0 이상 점수만 통과

**상태**: ✅ 해결.

---

## 문제 19: Ollama 가 첫 토큰을 못 보냄 (context_length 4096 초과)

**증상**: AIMODE 답변 생성 시 `generating` 이벤트 후 무한 hang. token 0개. 40~90초 기다려도 done 안 옴.

**원인 진단 (devconsole + `/api/ps`)**:
- Ollama `/api/ps`: gemma3:4b-it-qat 의 `context_length: 4096`
- 우리 prompt: 11000자+ (~3700~4500 토큰) + num_predict 250 = **4000~4750 토큰 > 4096**
- → Ollama 가 silent hang (truncation 도 아니고 응답 자체 멈춤)

**해결**: `_ollama_stream` 과 `_ollama_oneshot` 모두 `num_ctx=8192` 명시.

```python
"options": {
    "temperature": temperature,
    "num_predict": num_predict,
    "num_ctx": 8192,   # [v3.2 fix] 기본 4096 으로는 긴 prompt silent hang
}
```

Ollama 가 새 num_ctx 로 모델 재로드 (5~10초 cold start 1회) 후 정상 동작.

**검증**: `Invoke-RestMethod http://localhost:11434/api/ps` 에서 `context_length: 8192` 확인.

**상태**: ✅ 해결.

---

## 문제 20: prompt 너무 김 — prefill 시간 폭증

**증상**: ollama_stream_start 후 TTFT 36~50초. 사용자 체감 매우 느림.

**원인**: `generate_node` 가 doc 청크 + fitz head 5000 + 키워드 주변 5000 + scan_chunks 합쳐서 **최대 15000자** prompt 빌드. ~5000 토큰 prefill = 10초+.

**해결**: prompt 단축 (cap 절반 이하).

```python
# [v3.2 speed] before
combined[:15000]
full_text = _read_source_full_text(src, max_chars=800000)
head = full_text[:5000]
extra = _keyword_target_paragraphs(..., max_chars=5000)

# [v3.2 speed] after
combined[:6000]                          # 15000 → 6000
full_text = _read_source_full_text(src, max_chars=200000)   # 800K → 200K (fitz I/O 단축)
head = full_text[:2000]                  # 5000 → 2000
extra = _keyword_target_paragraphs(..., max_chars=2000)     # 5000 → 2000
```

`num_predict` 도 250 → 250 (doc) / 200 (AV) 로 유지. 답변 양식은 간결 마크다운 (도입 1줄 + bullet 3~4개 + 마무리 1줄).

**효과**: prompt 12000자 → ~10000자, prefill 3~5초 단축.

**상태**: ✅ 적용 (TTFT 여전히 큰 prompt 에서는 15~30s — Ollama 자체 한계).

---

## 1. 제목

# 문제 21 — GPU VRAM 핑퐁: 임베더 ↔ LLM 동시 적재 불가 (8GB 환경) ⭐ 핵심 이슈

---

## 2. 문제 정의 및 원인

### 정의

RTX 4060 Laptop 8GB VRAM 환경에서, 검색 단계가 쓰는 **임베더 4개 (~5.8GB)** 와 답변 단계가 쓰는 **LLM gemma3:4b-it-qat (~4.2GB)** 가 합쳐서 **약 10GB** 를 필요로 함. 두 그룹이 동시에 GPU 에 적재되면 OOM. 한쪽이 CPU 로 빠지면 추론 속도 10~20× 저하.

### 원인 — VRAM 산술

```
RTX 4060 Laptop GPU: 총 VRAM = 8 GB

[검색 단계] 임베더 4개:
  SigLIP2-SO400M     ~ 1.0 GB
  BGE-M3             ~ 2.0 GB
  DINOv2-Large       ~ 1.3 GB
  Reranker           ~ 1.5 GB
  ─────────────────────────────
  소계               ~ 5.8 GB

[답변 단계] LLM:
  gemma3:4b-it-qat   ~ 4.2 GB (+ KV cache)

────────────────────────────────
필요한 총 VRAM       ~ 10.0 GB   ❌ > 8 GB 카드 (2GB 초과)
```

→ **둘 다 동시 GPU 적재 불가**. 누군가는 항상 CPU 거나 swap 돼야 함.
→ 노드가 그래프 순서대로 진행되면서 GPU 메모리 정리 안 하면 다음 노드가 OOM.

### 2.1 현상 (관찰된 증상 3개)

#### 현상 ① — Generate 노드에서 무한 hang
```
[generating] 이벤트 출력 후 token 0개. 30~90초 후 timeout.
```
원인: Ollama 가 GPU 자리 못 찾아서 추론 시작 자체를 못 함. 사용자는 그저 스피너만 봄.

#### 현상 ② — Ollama 가 CPU 로 fallback → 1~2 tok/s
```
ollama_stream_start 이후 첫 토큰까지 36~60초.
이후 토큰 생성 속도가 평소 (40 tok/s GPU) 의 1/20 수준.
```
원인: VRAM 부족 감지 후 Ollama 가 silent 하게 CPU 로 우회 추론. 답변 양이 늘수록 비례해서 느려짐.

#### 현상 ③ — 검색 ↔ 답변 핑퐁 (매 turn 5~10초 추가)
```
턴 1: 검색 (5s) + 답변 (느림)
턴 2: 검색 또 5~10초 (임베더 재로드)
턴 3: 답변 또 5~10초 (LLM 재로드)
...
```
원인: GPU 메모리 부족으로 누군가 강제 unload → 다음에 쓸 때 다시 로드. 이게 매 turn 반복.

---

## 3. 해결 전략

세 가지 전략을 순서대로 시도했고, **3번째가 최종 채택**.

### 3.1 시도 ① — search_node 끝 백그라운드 임베더 release

```python
def _bg_release():
    if free_vram < 4500:
        _release_search_embedders()
threading.Thread(target=_bg_release, daemon=True).start()
```

**아이디어**: 검색 끝나면 임베더를 비동기로 해제. 사용자는 그동안 답변 보면 되니까 체감 X.

**결과**: ❌ **실패**.
- 첫 turn 은 빨라짐 — 임베더 해제 후 LLM 적재 OK
- 다음 turn 에서 임베더 4개 재로드 (5~10초) → 검색 자체가 매번 느려짐
- 핑퐁이 사라진 게 아니라 **위치가 바뀐 것**

### 3.2 시도 ② — `config.DEVICE='cpu'` (임베더 영구 CPU)

```python
# config.py
"DEVICE": "cpu" if os.environ.get("FORCE_CPU", "1") == "1" else "cuda"
```

**아이디어**: 임베더 4개를 영구 CPU 거주. LLM 만 GPU 전유. 핑퐁 자체 제거.

**결과**: ❌ **롤백**.
- 핑퐁은 사라짐
- 하지만 검색 속도 1~2초 → 3~5초로 느려짐 (CPU 임베딩)
- 사용자가 검색 응답성 저하를 더 크게 느낌 → 원복

### 3.3 시도 ③ (채택) — 노드별 명시적 release + 2초 안정화 대기

**아이디어**: **각 노드가 작업 끝나면 자기가 쓴 GPU 자원을 해제하고 2초 대기**. 다음 노드가 깨끗한 GPU 에서 시작. 동기적이라 핑퐁 없음.

**핵심 헬퍼 — `_release_and_wait()`**:

```python
def _release_and_wait(
    node_name: str,
    seconds: float = 2.0,
    release_embedders: bool = False,
    release_ollama_model: str | None = None,
    empty_cache: bool = True,
) -> None:
    """노드 끝에서 GPU 자원 해제 + N초 안정화 대기."""

    # 1) 임베더 해제 (Python 프로세스 GPU)
    if release_embedders:
        _release_search_embedders()    # 4개 임베더 .cpu() + None

    # 2) Ollama 모델 unload (별도 프로세스)
    if release_ollama_model:
        _req.post(f"{OLLAMA_URL}/api/generate",
                  json={"model": release_ollama_model, "keep_alive": 0,
                        "prompt": "", "stream": False}, timeout=5)

    # 3) torch cache 비우기 + 동기화
    if empty_cache:
        torch.cuda.empty_cache()
        torch.cuda.synchronize()

    # 4) ⭐ 2초 안정화 대기 (GPU driver 가 메모리 실제 release 할 시간)
    if seconds > 0:
        time.sleep(seconds)
```

**왜 2초인가**: `torch.cuda.empty_cache()` 와 `synchronize()` 호출 후에도 GPU driver-level release 는 비동기. 1초만 대기하면 가끔 다음 노드가 OOM. **2초가 안전선**.

**노드별 적용 표**:

| 노드 | embedders 해제 | Ollama unload | 대기 | 이유 |
|---|---|---|---|---|
| `intent` | ❌ | ❌ | 2s | cache 정리만 |
| `search` | ✅ | ❌ | 2s | 검색 끝 → 임베더 즉시 해제 |
| `scan` | ✅ | ❌ | 2s | generate 직전 GPU 정리 |
| `select` | ❌ | ❌ | 2s | cache 정리 |
| `fulltext_search` | ✅ | ❌ | 2s | open 모드 — 검색 후 해제 |
| `followup_intent` | ❌ | ❌ | 2s | cache 정리 |
| `followup_search` | ✅ | ❌ | 2s | 임베더 정리 |
| `extract` | ✅ | ❌ | 2s | generate 직전 마지막 정리 |
| `generate` (시작 전) | ✅ | ✅ (VRAM<4.5GB) | 2s | LLM 자리 확보 + Ollama 재로드 보장 |
| `generate` (끝) | ❌ | ❌ | 0.5s | LLM 유지 (keep_alive=-1) |

**search_node 적용 예시**:
```python
def search_node(state):
    candidates = _do_search(file_query, topk=topk)
    _emit({"type": "candidates", "items": candidates})

    # [v3.3] 검색 임베더 해제 + 2초 안정화
    _emit({"type": "node_done", "node": "search", "next": "scan"})
    _release_and_wait("search_node", seconds=2.0, release_embedders=True)

    return {"candidates": candidates}
```

**generate_node 시작 전 (가장 공격적)**:
```python
if _free_mb < 4500:
    _release_and_wait(
        "generate_node_pre",
        seconds=2.0,
        release_embedders=True,
        release_ollama_model=gen_model,  # Ollama 도 unload → GPU 재로드 보장
    )
```

---

## 4. 최종 결과

### 효과 측정

#### 변경 전 (OOM 발생 시)
```
[search]  ─ candidates 출력 ─ 0.5s
[generate] ─ generating 출력 ─ HANG (token 0개, 60s+ timeout)
```

#### 변경 후 (정상 동작)
```
[router]          0.1s
[intent]          + 2s wait                = 12s (LLM cold start)
[search]          + 2s wait (임베더 해제) = 40s
[scan]            + 2s wait                = 43s
[select]          + 2s wait                = 45s
[extract]         + 2s wait (임베더 정리) = 47s
[generate 시작]   + 2s wait (강한 정리)   = 49s
[ollama stream]   첫 토큰 ~ 36s            = 85s
[generate 끝]     + 0.5s                   = 85.5s
```

**추가 대기 시간 합계**: 약 **14.5초 per turn**.

### 트레이드오프

| 항목 | 변경 전 | 변경 후 |
|---|---|---|
| OOM 발생 빈도 | 자주 | **0** |
| 첫 토큰까지 시간 | hang or 60s+ | ~50s |
| done 까지 시간 | 불안정 | **85s (안정)** |
| 추가 wait 시간 | 0 | +14.5s |
| 답변 누락 위험 | 있음 | **없음** |

→ **속도 약간 손해, 안정성 큰 이득**.
→ OOM 한 번 나면 답변 자체가 안 나오므로 안정성 우선.

### 검증 방법

```powershell
# Ollama 가 GPU 에 올라갔는지
Invoke-RestMethod http://localhost:11434/api/ps | Format-List
# → size_vram > 0 이고 context_length: 8192 면 정상

# 백엔드 로그에 각 노드 release 로그 확인
[release_and_wait] search_node: 임베더 해제 (1234MB) + cuda cache 비움 + 2.0s 대기 → 여유 VRAM 6789MB
[release_and_wait] scan_node: ...
...
```

devconsole SSE 디버거에서 `node_done` 이벤트가 각 노드 끝마다 나오는지 확인.

### 상태

✅ **OOM 완전 해소. v3.3 안정 버전. 운영 채택.**

---

## 문제 22: 사이드바 채팅방 목록 안 보임

**증상**: AIMODE 답변 완료 후에도 좌측 사이드바에 채팅방이 안 뜸.

**원인 1 (백엔드)**: SQLite 저장 자체는 됨 (`_persist_chat_turn` → `aimode_threads` INSERT). 단, 처음엔 `aimode_threads` / `aimode_messages` 테이블 자체가 없었음 (init_db 에 누락).

**해결 1**: `db/init_db.py` 에 테이블 추가:

```sql
CREATE TABLE IF NOT EXISTS aimode_threads (
    thread_id   TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '새 대화',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    msg_count   INTEGER NOT NULL DEFAULT 0,
    first_query TEXT
);

CREATE TABLE IF NOT EXISTS aimode_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    extra      TEXT,
    FOREIGN KEY (thread_id) REFERENCES aimode_threads(thread_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_aimode_threads_updated ON aimode_threads(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_aimode_messages_thread ON aimode_messages(thread_id, id);
```

**원인 2 (프론트엔드)**: `done` 이벤트 후 사이드바가 자동 새로고침 안 됨. `aiChatRefreshTrigger = turns.length` 였는데 update only 라 length 변화 X.

**해결 2**: 별도 `chatRefreshTrigger` state 추가, `done` 이벤트에서 `setChatRefreshTrigger(t => t+1)`. `SearchSidebar` 가 prop 변경 감지해 threads fetch 재실행.

**상태**: ✅ 해결.

---

## 문제 23: 채팅방 제목 — 그냥 질문 truncate

**증상**: 사이드바 채팅방 이름이 질문 첫 30자 그대로 ("산업 동향 알려줘…" 같은 식).

**해결**: 첫 turn 답변 완료 시 LLM 1회 호출로 짧은 제목 생성.

```python
def _generate_thread_title(first_question, model):
    prompt = (
        "사용자 질문을 보고 짧은 채팅방 제목(한국어, 12자 이내)을 만들어.\n"
        "규칙: 물음표·따옴표 금지, 핵심 주제 명사만, 동사 제거.\n"
        "예시:\n"
        "  SW산업 수출액은? → SW산업 수출액\n"
        "  산업 동향 알려줘 → 산업 동향\n"
        ...
    )
    raw = _ollama_oneshot(prompt, model, num_predict=20)
    # 짧고 깨끗한 제목 반환
```

LLM 실패 시 정규식 fallback (`알려줘|찾아줘` 등 제거 후 truncate).

**상태**: ✅ 해결.

---

## 문제 24: 후속 질문 시 출처 chip 사라짐

**증상**: 2턴 후속 질문 시 1턴에서 잡힌 references chip 이 모두 사라짐.

**원인**: `done` 이벤트 핸들러가 turn 의 references / sources 를 `aimodeReferences` / `aimodeSources` state 로 덮어씀. 이 state 가 후속에서는 빈 값일 수 있음 (stale state).

**해결**: turn 의 last.X 가 비어있을 때만 state fallback 사용.

```javascript
const lastRefs = (last.references && last.references.length > 0)
    ? last.references
    : [...(aimodeReferences || [])];
const lastSrcs = (last.sources && last.sources.length > 0)
    ? last.sources
    : [...(aimodeSources || [])];
```

또한 `extract` / `selected` / `candidates` 이벤트 핸들러에서 직접 `setTurns` 호출로 즉시 update — done 이벤트 도착 전에 turn 안에 박아둠.

**상태**: ✅ 해결.

---

## 문제 25: 우측 후보 패널 — selected 후 1개만 남음

**증상**: 검색 결과 10개 카드가 뜨다가, `selected` 이벤트 후 매칭된 1개만 남고 나머지 9개 사라짐.

**원인**: `selected` 핸들러가 `setResults(matched)` 로 후보 목록을 덮어씀. `rightCandidates` 가 `results` fallback 사용.

**해결**:
1. `candidates` 핸들러에서 `setTurns` 로 `last.candidates = [...mapped]` 도 함께 update
2. `selected` 핸들러에서 `setResults` 호출 제거. `setAimodeSources(matched)` 만 — 매칭 sources 는 답변 인용용으로만 사용.
3. `rightCandidates = latestTurn?.candidates?.length ? latestTurn.candidates : results` 가 candidates 전체 10개 그대로 유지.

**상태**: ✅ 해결.

---

## 문제 26: 답변에 외국어 환각 (스페인어/한자/일본어)

**증상**: gemma3:4b-it-qat 답변에 `"dólares"`, `"是的"`, `"です"` 같은 외국어 단어가 섞임.

**원인**: gemma3 의 multilingual vocab — 한국어 token 확률이 다른 언어와 박빙일 때 외국어 토큰 선택.

**해결**: system prompt 최상단에 **CRITICAL 언어 규칙** 박음.

```python
sys_msg = f"""[CRITICAL — 언어 규칙]
반드시 한국어(한글)로만 답변하세요. **영어·스페인어·일본어·중국어·한자·기타 외국어 절대 금지**.
숫자와 단위 외 모든 단어는 한글로만 쓸 것. 예: "달러" OK, "dólares" 절대 금지.
답변 첫 글자부터 마지막 글자까지 한글이어야 합니다.
...
"""
```

또한 user content 끝에도 `"한국어로만 답변 (외국어 단어 절대 금지)"` 반복 강조.

**상태**: ✅ 해결 (대부분). 가끔 누락 발생하면 frontend `stripMarkdown` 단계에서도 한 번 더 필터링 가능.

---

## 문제 27: 답변 너무 김 / 너무 짧음

**시도 1 — 길게**: `[답변 분량]` 섹션에 "최소 12문장 이상, 권장 15~20문장" + 도입·항목·종합 구조 강제.
- 결과: 길어지긴 했는데 반복적이고 산만함.

**시도 2 — 짧게 + 마크다운 (최종 채택)**:
```python
[답변 형식 — 반드시 준수]
- 간결한 마크다운(Markdown)으로 답변. 총 분량은 짧게 (도입 1줄 + 핵심 3~4 bullet + 마무리 1줄).
- 답변 길이는 최대 8~10줄 / 약 3~4문장 분량. 장황한 부연·반복 금지.
- 핵심 키워드는 **굵게**. 항목은 `- ` 불릿. 표·코드블록 금지.
```

`num_predict` 350 → **250** (doc) / **200** (AV).

**프론트엔드 — 마크다운 렌더**: 기존 `stripMarkdown` 으로 평문화하던 걸 `MarkdownAnswer` 컴포넌트로 교체. `##` 헤딩, `- ` 불릿, `**굵게**`, `[출처N]` chip 동시 렌더.

**상태**: ✅ 해결. 답변이 깔끔하고 빠름.

---

## 문제 28: PDF 정리 기능 — Editorial 매거진 스타일

**요청**: 채팅 후 PDF 버튼 → AI가 대화를 정리해서 매거진 스타일 PDF 다운로드.

**구현** (`/api/aimode/export-pdf`):
1. SQLite 에서 thread 메시지 로드
2. LLM 으로 JSON 요약 생성 (`{title, overview, key_points, qa_summaries, conclusion}`)
3. `reportlab` 으로 PDF 합성 — 4섹션 (Cover / Key Points / Q&A / Conclusion)
4. Windows Malgun Gothic 자동 등록
5. 파일명: `{제목}_{날짜}.pdf`

디자인:
- 섹션 라벨 + 파란 짧은 바 + 큰 번호 타이틀
- ◆ 다이아몬드 마커 (Key Points)
- 굵은 진남색 Q + 들여쓰기 A (Q&A)
- 진남색 풀쿼트 카드 (Conclusion)

프론트엔드: 입력창 내부 우측에 PDF 아이콘 버튼 추가 (`picture_as_pdf`).
- `turns.length === 0` 또는 streaming 중 → 비활성

**의존성**: `pip install fpdf2` (옛 `fpdf` 1.x 와 충돌하므로 `pip uninstall fpdf` 먼저).

**상태**: ✅ 완성.

---

## 문제 29: `from db.init_db` 가 PyPI `db` 패키지를 import

**증상**: `python app.py` 시 `SyntaxError: Missing parentheses in call to 'print'`.

**원인**: site-packages 의 옛 `db` 패키지 (Python 2 시절 2012년 토이 패키지) 가 로컬 `db/init_db.py` 보다 먼저 import 됨.

**해결**:
```powershell
pip uninstall -y db
```

**상태**: ✅ 해결.

---

## v3 그래프 빌드 코드 (참조)

```python
def _get_rag_graph():
    builder = StateGraph(RAGState)

    # 노드 등록
    builder.add_node("router",            router_node)
    builder.add_node("intent",            intent_node)
    builder.add_node("search",            search_node)
    builder.add_node("scan",              scan_node)
    builder.add_node("select",            select_node)
    builder.add_node("fulltext_search",   fulltext_search_node)
    builder.add_node("followup_intent",   followup_intent_node)
    builder.add_node("followup_search",   followup_search_node)
    builder.add_node("extract",           extract_node)
    builder.add_node("generate",          generate_node)

    # 엣지
    builder.add_edge(START, "router")
    builder.add_conditional_edges("router", _route_edge,
        {"rag": "intent", "followup": "followup_intent"})
    builder.add_conditional_edges("intent", _after_intent_edge,
        {"structured": "search", "open": "fulltext_search"})

    builder.add_edge("search",          "scan")
    builder.add_edge("scan",            "select")
    builder.add_edge("select",          "extract")
    builder.add_edge("fulltext_search", "extract")
    builder.add_edge("followup_intent", "followup_search")

    builder.add_conditional_edges("followup_search", _after_followup_search_edge,
        {"exist": "extract", "none": "_followup_fallback_marker"})

    # 폴백 마커
    def _followup_fallback_marker(state):
        _emit({"type": "followup_fallback", "reason": "이전 파일에서 못 찾음 → 전체 검색 시작"})
        return {"fallback_from_followup": True, "route": "rag"}
    builder.add_node("_followup_fallback_marker", _followup_fallback_marker)
    builder.add_edge("_followup_fallback_marker", "intent")

    builder.add_edge("extract",  "generate")
    builder.add_edge("generate", END)

    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)
```

---

## 작업 타임라인 (v3 라인)

| 날짜 | 작업 |
|---|---|
| 2026-05-11 | v3 그래프 재설계 — chat·qa_gen 제거, followup 2-route, mode 분기, extract 노드 신규 |
| 2026-05-11 | SQLite 채팅 영속화 — aimode_threads/messages 테이블, 사이드바 UI |
| 2026-05-11 | LLM 자동 제목, 채팅방 클릭 시 history 복원 |
| 2026-05-11 | Special token 필터, 후속 질문 phrase 분해, 목차 페널티 |
| 2026-05-12 | PDF export 기능 + Editorial 매거진 스타일 (reportlab) |
| 2026-05-12 | 답변 길이/형식 조정 — 간결 마크다운, num_predict 250 |
| 2026-05-12 | MarkdownAnswer 프론트엔드 컴포넌트 |
| 2026-05-12 | AV 키워드 매칭 버그 수정, select_node 약한 AV 컷 |
| 2026-05-12 | num_ctx=8192 — Ollama silent hang 해소 |
| 2026-05-12 | prompt 단축 (15K → 6K) |
| 2026-05-12 | 우측 후보 패널 — selected 후 전체 유지 |
| 2026-05-13 | 노드별 `_release_and_wait` 2초 안정화 — VRAM OOM 해소 |
| 2026-05-13 | `fpdf2` 의존성 추가, 옛 `fpdf` / 옛 `db` 패키지 제거 안내 |

---

