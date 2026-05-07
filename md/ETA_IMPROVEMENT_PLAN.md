# 인덱싱 잔여 시간 개선 계획

_작성: 2026-05-07_

---

## Phase 1 — 완료 ✅ (2026-05-07)

### 수정된 파일
| 파일 | 변경 | 효과 |
|---|---|---|
| `App/backend/services/index_estimator.py` | B1: BGM 폴더 경로 기반 타입 분리, CLAP 계수 추가 | BGM 파일 시간 추정 ~4배 정확해짐 |
| `App/frontend/src/pages/DataIndexing.jsx` | B2: skipped 제외 rate 계산, B3: 가드 0.5s→5s | "26초→26분" 같은 큰 과소 추정 해결 |

### 핵심 수정 내용 (DataIndexing.jsx)

**Before (버그):**
```js
const rate = processed / elapsedSec;           // skipped 포함 → rate 비현실적
if (rate > 0) remainingSec = (total - processed) / rate;
// if (elapsedSec > 0.5)  ← 너무 이른 가드
```

**After (수정):**
```js
const actualDone      = done + errors;         // skipped 제외
const actualRemaining = total - skipped - actualDone;
const rate = actualDone / elapsedSec;          // 실제 처리 속도
if (elapsedSec > 5.0)                          // 5초 안정화 후 계산
```

### Phase 1 적용 방법 (VSCode 터미널)

```bash
# 1. Vite 빌드 (frontend)
cd App/frontend
npm run build

# 2. Electron 재실행 (개발 테스트)
npm run electron

# 3. 배포용 exe 재빌딩 (선택사항)
npm run dist
```

> 백엔드(`index_estimator.py`)는 Flask 재시작 시 자동 반영.

---

## Phase 2 — 가중 평균 + 실측 보정 ✅ (2026-05-07)

### 목표
- 현재: 모든 파일을 동일 속도로 가정 (`파일수/elapsed`)
- 개선: **도메인+크기 가중치** 기반 잔여시간 + **실측 보정 계수** 적용

### 구현 대상

#### W1. 백엔드: jobStatus에 `estimated_remaining` 추가

`routes/index.py` — `_run_job()` 수정:

```python
# 매 파일 완료 후 남은 파일들의 추정 시간을 재계산
from services.index_estimator import estimate as _est

def _calc_remaining_estimate(remaining_paths: list[str]) -> float:
    """남은 파일들의 가중 합산 추정치 (신규만)."""
    result = _est(remaining_paths)
    return result["total_seconds"]  # skipped overhead 포함하지 않으려면 new_count 기반
```

`_update_job()` 에 `estimated_remaining` 필드 추가:
```python
_jobs[job_id]["estimated_remaining"] = _calc_remaining_estimate(
    [p for p, r in zip(file_paths[i+1:], results[i+1:]) if r["status"] == "pending"]
)
```

#### W2. 프론트엔드: 실측/추정 보정 계수

`DataIndexing.jsx` — ETA 계산 블록 교체:

```js
// 백엔드가 estimated_remaining 을 제공하면 우선 사용
if (jobStatus?.estimated_remaining != null && actualDone > 0) {
  const estRemaining   = jobStatus.estimated_remaining;   // 가중 추정치
  const actualElapsed  = Date.now() / 1000 - jobStatus.started_at;
  
  // 지금까지 처리된 파일들의 실측/추정 비율로 보정
  const doneEstimate   = jobStatus.done_estimated ?? estRemaining; // 완료분 추정 합산
  const correction     = actualDone > 0 && doneEstimate > 0
    ? (actualElapsed / doneEstimate)    // 실측이 추정보다 빠르면 < 1
    : 1.0;
  
  remainingSec = estRemaining * Math.min(correction, 3.0); // 최대 3배 보정
} else {
  // fallback: Phase 1 방식
  const rate = actualDone / elapsedSec;
  if (rate > 0) remainingSec = actualRemaining / rate;
}
```

#### W3. 사전 추정(IndexingETA)에 skipped overhead 표시 개선

`IndexingETA.jsx` — skipped 시간을 total에서 분리해서 표시:
```jsx
// 현재: total_seconds = new_time + skipped_overhead
// 개선: new_time 만 표시, "건너뜀 N개 (해시 확인 ~Xs)" 분리 표시
const newOnlySecs = data.total_seconds - (data.skipped_count * 0.05);
```

### 예상 효과
| 시나리오 | Phase 1 후 | Phase 2 후 |
|---|---|---|
| PNG 2개(skip) + 동영상 1개 | "5s 후 표시 시작" → 대략 맞음 | "남은 1개 동영상 ~8분" 정확 |
| doc 5개 + image 20개 혼합 | 평균 속도 외삽 | 각 도메인 가중치 합산 |
| 50개 배치 (절반 skip) | skip 제외 실제 25개 기준 | 25개 × 타입별 계수 합산 + 실측 보정 |

---

## Phase 3 — 스테이지 단위 추정 ✅ (2026-05-07)

비디오 5단계(프레임→SigLIP2/DINOv2→Whisper→BGE-M3→DB) 각각의 진행 반영.
현재 `r.step / r.step_total` 데이터는 이미 백엔드가 제공 중 → 가중치만 추가하면 됨.

```python
_VIDEO_STAGE_WEIGHTS = {
    "frame_extract": 0.10,
    "siglip2_dino":  0.35,
    "whisper_stt":   0.40,
    "bge_m3_im":     0.10,
    "vectordb":      0.05,
}
# 현재 파일의 남은 시간 = 전체 추정 × (1 - 완료 스테이지 가중치 합)
```

---

## Phase 4 — 확장자/메타 기반 미세 추정 🔲 (선택)

| 도메인 | 추가 변수 |
|---|---|
| video | ffprobe 해상도, 길이, 코덱 |
| doc | pdfinfo 페이지 수, OCR 여부 |
| audio | 길이(초) |

---

## Phase 2 시작 방법 (다음 PC 켤 때)

```
1. VSCode에서 이 파일 열기
2. W1 구현: App/backend/routes/index.py → _run_job() 수정
3. W2 구현: App/frontend/src/pages/DataIndexing.jsx → ETA 블록 교체
4. W3 구현: App/frontend/src/components/indexing/IndexingETA.jsx → skipped 분리 표시
5. npm run build (App/frontend/)
6. Flask 재시작
7. 테스트: PNG 2개(이미 인덱싱) + 동영상 1개(신규) 혼합 인덱싱
```
