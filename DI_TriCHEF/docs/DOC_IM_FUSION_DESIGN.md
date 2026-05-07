# Doc Im축 Fusion 설계 (Caption + Body Score-Level Fusion)

작성일: 2026-04-24

---

## 1. 현재 구조의 문제

Doc/Img 파이프라인의 Im축은 현재 **페이지 캡션(제목/소제목)만** 임베딩한다.

```
현재: Im = BGE-M3(caption)   # 본문 텍스트 미포함
```

**결과**: 본문 내용이 쿼리와 매칭되어도 검색 안 됨.  
Reranker가 cross-encoder로 교정하지만, 후보군 자체에 없으면 교정 불가.

---

## 2. 0.3/0.7 블렌딩의 문제 (하드코딩 금지 이유)

임베딩 레벨 블렌딩:
```python
Im = 0.3 * embed(caption) + 0.7 * embed(body)  # ❌
```

| 문제 | 설명 |
|---|---|
| Magic number | 근거 없는 비율, 문서 종류별 최적값 다름 |
| 정보 손실 | 두 벡터 평균 → 둘 다 희석됨 |
| 검증 불가 | 어떤 축이 검색에 기여했는지 측정 불가 |
| 적응성 없음 | 짧은 쿼리 vs 긴 쿼리 동일 처리 |

---

## 3. 권장 설계: Score-Level Fusion

### 3-1. 저장 구조 변경

```
현재:  cache_doc_Im.npy         (N, 1024)  # caption 벡터만
변경:  cache_doc_Im_cap.npy     (N, 1024)  # caption 벡터
       cache_doc_Im_body.npy    (N, 1024)  # body 텍스트 벡터 (신규)
```

body 벡터가 없는 페이지(표지, 이미지 전용 등)는 `Im_body = Im_cap` 복사.

### 3-2. 검색 시 Score Fusion

```python
# unified_engine.py 검색 로직
sim_cap  = q_Im @ d_Im_cap.T    # (1, N) 캡션 유사도
sim_body = q_Im @ d_Im_body.T   # (1, N) 본문 유사도

alpha = _adaptive_alpha(query)   # 쿼리 길이에 따라 조정
score_Im = alpha * sim_cap + (1 - alpha) * sim_body
```

### 3-3. Adaptive alpha (query-adaptive)

```python
def _adaptive_alpha(query: str, base: float = DOC_IM_ALPHA) -> float:
    """짧은 쿼리 → caption 가중, 긴 쿼리 → body 가중."""
    if not DOC_IM_ALPHA_ADAPTIVE:
        return base
    tokens = len(query.split())
    # 1~5 tokens: alpha=base, 20+ tokens: alpha=base*0.4
    scale = max(0.4, 1.0 - (tokens - 5) * 0.04)
    return round(base * scale, 3)
```

### 3-4. Config (config.yaml 또는 paths.py 상수)

```python
# App/backend/config/trichef_config.py (신규)
DOC_IM_ALPHA: float = 0.35         # calibration으로 갱신
DOC_IM_ALPHA_ADAPTIVE: bool = True  # query-len 보정
DOC_IM_BODY_FALLBACK: str = "cap"   # body 없을 때 "cap" | "zero"
```

---

## 4. Calibration으로 alpha 자동 탐색

```python
# calibration/calibrate_doc_im.py (신규)
GOLD_QUERIES = [
    ("전이학습 기법",         "doc_page_id_xxx"),  # 짧은 쿼리 → caption 유리
    ("도메인 간 분포 차이가 클 때의 대응 전략",  "doc_page_id_yyy"),  # 긴 쿼리 → body 유리
    # ...
]

best_alpha, best_hit = 0.5, 0.0
for alpha in [i/10 for i in range(1, 10)]:
    hits = eval_topk(GOLD_QUERIES, alpha=alpha, topk=5)
    if hits > best_hit:
        best_alpha, best_hit = alpha, hits

# config 저장
save_alpha(best_alpha)
```

---

## 5. 구현 순서 (내일 작업 플랜)

| 단계 | 작업 | 예상 시간 |
|---|---|---|
| 1 | `incremental_runner.py`: body 텍스트 추출 (PDF pdfplumber) + `Im_body` 임베딩 | 30분 |
| 2 | `_build_entry()`: `Im_body` npy 로드 + `_cache` 에 추가 | 10분 |
| 3 | `unified_engine.py`: `score_Im = α·cap + (1-α)·body` fusion | 20분 |
| 4 | `_adaptive_alpha()` 구현 + config 상수 추가 | 10분 |
| 5 | Doc 재인덱싱 (Im_body 생성) | 20~40분 |
| 6 | 검색 품질 비교 (before vs after) | 15분 |
| 7 | Calibration 스크립트 + alpha 갱신 | 20분 |

**총 예상: 2~2.5시간**

---

## 6. 예상 효과

| 시나리오 | 현재 | 개선 후 |
|---|---|---|
| "전이학습" (짧은 키워드) | caption에 있으면 히트 | 동일 (alpha 높음) |
| "학생이 교수에게 면담 신청할 때 주의할 점" (긴 문장) | caption 없으면 miss | body에서 히트 가능 |
| "표 안의 숫자 데이터" | 거의 miss | body 추출 품질 따라 개선 |

---

## 7. 주의사항

- **재인덱싱 필요**: `Im_body` npy 추가로 기존 캐시 무효화
- **저장 용량**: Im_body npy 추가로 캐시 2배 (1024d × N × 4bytes)
- **PDF body 추출 품질**: 스캔 PDF는 OCR 없이 빈 텍스트 → body = cap fallback 처리 필요
- **성능**: 검색 시 sim 계산 1회 추가 (무시 가능 수준)
