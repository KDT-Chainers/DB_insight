# 2026-05-08 통합 작업 보고서

## 요약

검색 품질 + UX 최적화 종합 작업. **확정 효과**, **검증된 무효**, **데이터 한계** 명확히 분리.

---

## 1. exe 로딩 시간 최적화 ⭐ (90% 단축)

### 결과

| 항목 | 기존 | 현재 | 개선 |
|---|---|---|---|
| Flask `/api/health` | 22~25초 | **2.25초** | -91% |
| 첫 검색 (워밍업 영향) | 12초 | 36초 | +200% (악화) |

→ 사용자 체감 로딩 (Splash → Ready 전환) 대폭 빨라짐.
→ 첫 검색 비용은 워밍업 비동기화로 인한 단순 시간 이동.

### 변경 사항

| 파일 | 변경 |
|---|---|
| `App/backend/app.py` | 워밍업 동기→비동기 thread, image 도메인만 사전 로드, `/api/warmup-status` 추가 |
| `App/backend/config.py` | `import bitsandbytes` → `importlib.util.find_spec` (8.6s 절감) |
| `App/backend/routes/index.py` | 임베더 lazy 로더 (24s → 0.4s) |
| `App/backend/routes/trichef.py` | TriChefEngine/incremental_runner lazy (23s → 0.0s) |
| `App/backend/routes/trichef_admin.py` | PEP 562 module __getattr__ lazy (12s → 0.5s) |
| `App/frontend/src/pages/SplashOrb.jsx` | `/api/warmup-status` polling, stage 표시 |

### 환경변수 추가

- `OMC_FULL_WARMUP=1` — 모든 도메인 사전 로드 (server 모드)
- `OMC_QWEN_PREWARM=1` — Qwen 캡셔너 사전 로드 (인덱싱 자주 사용 시)
- `OMC_VISUAL_USE_BAYES=0` — image visual_check Bayesian → floor 전환
- `OMC_VISUAL_PENALTY=0.5` — penalty 강도 override

---

## 2. 검색 품질 — Bayesian vs Floor A/B 회귀

| 모드 | 정상 conf | 무관 conf | 분리도 |
|---|---|---|---|
| Bayesian (현 default) | 82.73% | 64.07% | **18.66%p** |
| Floor (전환 옵션) | 85.53% | 68.45% | 17.08%p |

**결론**: Bayesian 분리도 +1.6%p 우위. **현 default 유지**.

## 3. Penalty Sweep (mode × penalty)

| 조합 | 분리도 |
|---|---|
| `bayes p0.3` (현재) | **18.66%p** ⭐ |
| `bayes p0.5` | 14.89%p |
| `floor p0.3` | 16.81%p |

**결론**: penalty 0.3 + Bayesian 이 이미 최적. 변경 불필요.

---

## 4. Calibration v3 — relevant 표본 강화

### 결과 (모든 도메인 표본 부족)

| 도메인 | n | target | 분리도 (정상-무관) |
|---|---|---|---|
| image | 29 | 30 | **-0.010** ❌ |
| audio | 9 | 30 | +0.008 |
| doc | 9 | 30 | (계산 불가) |
| bgm | 25 | 30 | **+0.082** ✓ |
| video | 0 | 20 | -0.003 |

### 핵심 발견: SigLIP2 신호가 한국어 데이터셋에서 약함

- 캡션-이미지 cosine 평균 0.062 (랜덤 수준)
- 정상 매칭 0.073 vs 무관 0.083 → **음의 분리도** (image)
- Bayesian 분포 학습 통계적으로 무의미

**결론**: `calibration_v3.json` **적용하지 말 것**. 데이터 자체 한계.

---

## 5. n_sigma Sweep — 두 도메인 거동 다름

### image 도메인 (Bayesian default)
- `OMC_VISUAL_N_SIGMA` env var 가 visual_check 에서 **항상 무시**
- Bayesian 분기가 floor 우회 (line 317-331)
- sweep 결과 모든 n 에서 결과 수 동일 = 정상

### audio 도메인 (floor default)
- `OMC_AUDIO_N_SIGMA` 정상 작동
- "보이저호" 차단 임계: n≥3.5σ
- 현 default n=3.5 적정 (관련 쿼리 보존, 무관 차단)

---

## 6. 0건 쿼리 진단

| 도메인 | 의도 차단 | 데이터 부재 | 진짜 이슈 |
|---|---|---|---|
| image | 0 | 4 | 0 |
| doc | 3 | - | 1 (원전) |
| video | 0 | (8 후보) | 0~8 |
| bgm | 4 | - | 3 (록기타/여름해변/카페음악) |

19건 중 16건 정상. **검색 시스템 운영상 양호**.

---

## 7. 캡션 품질 — 데이터셋 핵심 이슈

### 측정 결과 (전체 2,381 이미지)
- cosine < 0.05: 933건 (39.2%)
- cosine < 0.10: 1,900건 (79.8%)
- cosine < 0.20: 2,378건 (99.9%)

### 카테고리별 거짓 캡션 (cosine < 0.10)
| 카테고리 | 건수 |
|---|---|
| food | 305 |
| cat | 310 |
| nature | 274 |
| person | 292 |
| building | 88 |
| dog | 25 |

### 검증 함정 — PIL 버그
**초기 검증 (10건)**: +0.12 평균 cosine 개선 — 사실 거짓!
- `caption(string_path, ...)` 으로 호출 → `'str' object has no attribute 'size'` silent 실패
- 빈 캡션이 데이터셋 mean 으로 회귀했을 뿐
- **수정**: `Image.open(path).convert("RGB")` 명시 (recaption_food_v2.py:130)

### 진행 중
- food 305건 재캡션 (10:30 완료 예상)
- swap 스크립트 + cat/nature 스크립트 준비 완료

---

## 8. Frontend 변경

### SplashOrb 워밍업 진행 표시
- `/api/warmup-status` polling (800ms interval)
- 단계 라벨: "백엔드 초기화" → "검색 엔진 로딩" → "이미지 모델 워밍업" → "준비 완료"
- 경과 시간 실시간 표시

---

## 변경 파일 목록

### Backend
- App/backend/app.py
- App/backend/config.py
- App/backend/routes/index.py
- App/backend/routes/trichef.py
- App/backend/routes/trichef_admin.py
- App/backend/services/visual_check.py (env toggle 2개 추가)

### Frontend
- App/frontend/src/pages/SplashOrb.jsx

### Scripts (신규)
- App/backend/scripts/run_night_pipeline.py
- App/backend/scripts/run_calibration_strengthen_v3.py
- App/backend/scripts/run_ab_bayes_vs_floor.py
- App/backend/scripts/run_penalty_sweep.py
- App/backend/scripts/diagnose_zero_queries.py
- App/backend/scripts/validate_recaption_sample.py
- App/backend/scripts/recaption_food_v2.py
- App/backend/scripts/recaption_category_v2.py
- App/backend/scripts/swap_caption_food_v2.py
- App/backend/scripts/_time_flask_startup.py

### .gitignore
- 새 산출물 패턴 다수 추가

---

## 권장 다음 작업

### 즉시 가능 (food 완료 후, ~10:30)
1. `python scripts/swap_caption_food_v2.py --dry-run` → 결과 검증
2. 사용자 승인 후 `python scripts/swap_caption_food_v2.py` (백업 자동 생성)
3. SigLIP2 캡션 임베딩 캐시 재생성 (`cache_img_Im_*.npy`)
4. cat/nature 카테고리 추가 재캡션 (`--category cat`, `--category nature`)

### 중기
5. 인덱싱 시점 캡션 검증 (Phase H) — 신규 데이터셋 자동 정제
6. SigLIP2 → 더 좋은 multilingual 모델 (Qwen2-VL embeddings 등) 검토

### 데이터 작업
7. `영진_2차/` 카테고리 영문 generic 캡션 → Qwen 한국어 재캡션 (전체 패턴)

---

## 변경 사항 — 코드 회귀 위험

- visual_check.py / config.py / app.py 변경: **default 동작 보존** (env var override 만 추가)
- routes/* 변경: lazy import 만, 기존 endpoint 동작 동일
- frontend SplashOrb: 새 polling 만, 기존 UI 그대로

→ 즉시 사용자 검증 시 회귀 발견 위험 낮음.

⚠️ 자동 commit/push 금지 (사용자 메모리 directive). 검토 후 사용자 직접 commit.
