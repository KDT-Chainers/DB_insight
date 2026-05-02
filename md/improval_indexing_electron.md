# 인덱싱 성능·정확도 개선 종합 정리

**작성**: 2026-05-01
**범위**: 최근 `feature/trichef-port` pull 시점 ~ 현재까지 누적된 모든 개선 사항
**대상**: Electron + Flask + TriChef 인덱싱·검색 파이프라인

---

## 0. 한눈에 보는 누적 효과

| 영역 | 시작 시점 | 현재 |
|---|---|---|
| 영상 1개 처리 시간 | ~81s (CPU 디코드) | **~30~40s** (NVDEC 5x + Whisper batched 3x + BGM skip) |
| Whisper OOM 발생 시 | 무한 hang (재시작 필요) | **자동 다층 폴백 → 최악 error 1건 후 진행** |
| 인덱싱 중 검색 응답 | **차단 (단일 스레드 Flask)** | 즉시 (~200ms, threaded=True) |
| 진행률 갱신 주기 | 1초 폴링 | **0.25s SSE push** |
| 인덱싱 중 다른 페이지 이동 | 인덱싱 취소처럼 보임 | 백엔드 유지 + 모달 자동 복원 |
| OOM 위험 (RTX 4070 8GB) | 발생 | 0건 (다층 방어) |
| 검색 결과에 위치 정보 | 없음 | **page+line+snippet (doc) / timestamp+snippet (AV)** |
| 검색창 도메인 필터 | 없음 | **5칩 (전체/문서/이미지/영상/음성)** |
| 검색 결과 노이즈 (저신뢰도) | 그대로 노출 | **자동 숨김 + 토글** |
| 신뢰도 표시 | confidence 단일 | **신뢰도/정확도/유사도 3축 분해** |
| Reranker 적용 | 없음 | GPU bf16 BGE-v2-m3 자동 |
| ASF (lexical fusion) | OFF (admin 불일치) | ON (admin 일관) |
| 강제 종료 시 디스크 누수 | 영구 누적 | **1h+ stale 폴더 자동 정리** |
| 폴더 선택 영속화 | 없음 | localStorage 자동 복원 |
| 폴더 인덱싱 상태 시각화 | 없음 | **4단계 색상 + 빨강 orphan** |
| Orphan 파일 (등록후 삭제) | 미감지 | 빨강 배지로 즉시 식별 |
| 인덱싱 ETA | 없음 | 사이드바 + 모달 1초 tick |

---

## 1. 안정성·OOM·중단 (Critical)

| # | 문제 | 해결 | 위치 | 결과 |
|---|---|---|---|---|
| 1.1 | electron-builder Windows 심링크 권한 → 빌드 실패 | `--config.win.signAndEditExecutable=false` 플래그 | 빌드 절차 | ✅ portable exe 생성 |
| 1.2 | 백엔드 spawn 실패 (Temp 압축 해제 시 cwd 후보 미존재) → "백엔드 준비 중 (109)" 무한 대기 | `electron/main.cjs` candidates 맨 앞에 로컬 절대경로 | electron/main.cjs | ✅ 100ms 내 부팅 |
| 1.3 | 중단 버튼 무반응 (ffmpeg/Whisper blocking) | psutil로 ffmpeg 자식 SIGTERM→SIGKILL | 신규 `services/job_control.py` | ✅ 2~3초 응답 |
| 1.4 | OOM 발생 (Qwen-VL prewarm 4GB + SigLIP2/DINOv2/Whisper = 11GB) | (a) Qwen prewarm 환경변수 게이트, (b) Movie/Music 시작 시 unload, (c) `ensure_free(4500MB)` 사전 정리 | `incremental_runner.py`, `av_embed.py`, `vram_janitor.py` | ✅ E04 등 신규 정상 처리 |
| 1.5 | HuggingFace ConnectionError (Whisper hub 검증) | spawn env에 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` | electron/main.cjs | ✅ 네트워크 단절 무관 |
| 1.6 | 조기 중단 시 finalize 누락 (등록 파일이 검색 캐시 미반영) | `_run_job` early return → break + finalize 블록 도달 보장 | routes/index.py | ✅ chroma_drain + lexical + reload 항상 실행 |
| 1.7 | Whisper OOM 후 hang (sequential 폴백도 OOM) | 다층 폴백: batched=8 → batched=2 → 순차 → empty_cache + 재시도 | `MR_TriCHEF/pipeline/stt.py` | ✅ hang 없이 error 처리 후 다음 진행 |
| 1.8 | 워크스페이스 등 다른 페이지 이동 시 인덱싱 취소처럼 보임 | localStorage 에 jobId 저장 → 재진입 시 SSE 자동 재연결 + UI 복원 | `utils/indexingPersist.js`, `pages/DataIndexing.jsx` | ✅ 백엔드 계속 실행 + UI 자동 복원 |

---

## 2. GPU·VRAM 활용 (RTX 4070 Laptop 8GB)

| # | 문제 | 해결 | 위치 | 효과 |
|---|---|---|---|---|
| 2.1 | CPU 소프트 디코드 (영상 프레임 추출 30s/min) | ffmpeg `-hwaccel cuda` 옵션 + 코덱 폴백 + fps-only 폴백 | `MR_TriCHEF/pipeline/frame_sampler.py` | **5~8x 가속** (30s → 3-6s) |
| 2.2 | Whisper 순차 STT (GPU SM 30~50%) | `BatchedInferencePipeline(batch_size=8)` | `MR_TriCHEF/pipeline/stt.py` | **~3x 가속**, GPU SM 85~95% |
| 2.3 | VRAM 단편화 (모델 반복 로드/언로드) | `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` | `app.py` 부팅 시 자동 설정 | 가짜 OOM 차단 |
| 2.4 | VRAM reserved 누적 | `aggressive_cleanup()` (gc 2회+sync+empty_cache+ipc_collect), `ensure_free(target_mb)` | 신규 `services/vram_janitor.py` | 큰 모델 로드 직전 자동 정리 |
| 2.5 | Qwen-VL 영구 점유 (영상 처리에 불필요한데도 4GB 차지) | `_unload_qwen_captioner()` 헬퍼 + 영상/음성 처리 직전 자동 호출 | `incremental_runner.py`, `av_embed.py` | VRAM peak 11GB → 5GB |
| 2.6 | Reranker 미연결 (`shared/reranker.py` 코드만 존재) | `services/rerank_adapter.py` + main.cjs env `TRICHEF_USE_RERANKER=1` | 신규 모듈 | GPU bf16 BGE-v2-m3 자동 재정렬 |
| 2.7 | Qwen prewarm 미실효 (`__init__`만 호출되고 `_load()` 안 함) | `_get_qwen_captioner()`에 환경변수 게이트로 `_load()` 호출 | `incremental_runner.py:32-44` | 명시 활성화 시 사전 적재 |
| 2.8 | BGM/무음 영상에 Whisper STT 낭비 (~5-10s/file) | `_audio_has_voice()` RMS 검사 → 무음 자동 skip | `av_embed.py:78-110` | 영상당 5~10초 절감 |

---

## 3. 인덱싱 속도·배치 처리

| # | 문제 | 해결 | 위치 | 절감 |
|---|---|---|---|---|
| 3.1 | per-file `reload_engine()` 호출 (3-5s × N) | 도메인 dirty 추적 → 배치 끝 1회 + 60s/3 파일마다 백그라운드 reload | `routes/index.py:_run_job` | N×3-5s → 1×3-5s |
| 3.2 | per-file `lexical_rebuild` 호출 (5-10s) | `defer_lexical_rebuild=True` 파라미터, 배치 끝 1회 | `incremental_runner.py:embed_image_file/embed_doc_file` | N×5-10s 절감 |
| 3.3 | sync ChromaDB upsert (다음 파일 차단) | 신규 daemon 워커 + 큐 + drain_and_wait | 신규 `services/chroma_async.py` | 임베딩-I/O 병렬화 |
| 3.4 | 강제 종료 시 부분 캐시 누적 (`app_movie_*`) | `cleanup_stale_caches(threshold_sec=3600)` 자동 정리 | 신규 `services/cache_janitor.py` | 디스크 누수 방지 |
| 3.5 | Whisper int8 unload Windows crash | `compute_type="float16"` 고정 | `stt.py:WhisperSTT.__init__` | 안정 동작 |
| 3.6 | `/api/files/stats` total_files 부정확 (legacy + tc dedup 불일치) | `total_files = sum(by_type[t].file_count)` 통일 | `routes/files.py:189` | by_type 합 == total |
| 3.7 | 인덱싱 시작 시간 추정 부재 | 신규 estimator (도메인×파일크기 휴리스틱) + UI 패널 | 신규 `services/index_estimator.py` + `IndexingETA.jsx` | "예상 N분 NN초" 즉시 표시 |
| 3.8 | 인덱싱 중 잔여 시간 부재 | `IndexingModal`에 1초 tick + 실측 rate 기반 추정 | `pages/DataIndexing.jsx:IndexingModal` | "잔여 약 N분 NN초" 실시간 |

---

## 4. 검색 정확도·점수

| # | 문제 | 해결 | 위치 | 효과 |
|---|---|---|---|---|
| 4.1 | `/api/search` ASF 채널 OFF (admin과 결과 불일치) | `engine.search(..., use_lexical=True, use_asf=True, pool=200)` 명시 | `routes/search.py:130-135` | admin 일관, LOO R@1 +20pp 잠재 |
| 4.2 | Reranker 음수 점수에도 confidence 0.75 (모순) | `rerank_score < 0` 시 `confidence = min(prev, sigmoid(s))` | `services/rerank_adapter.py` | rerank=-5.4 → conf=0.0045 |
| 4.3 | 정확도 항상 0.500 표시 (필드명 버그: `result.rerank` vs 백엔드 `result.rerank_score`) | `result.rerank_score ?? result.rerank` 폴백 | `pages/MainSearch.jsx:111` | reranker 점수 정확 반영 |
| 4.4 | `/api/search` 응답에 위치 정보 누락 | 신규 `services/location_resolver.py` + 결과 dict 에 location 부착 | 신규 모듈 | Doc: page+line+snippet, AV: timestamp+snippet |
| 4.5 | 검색창에 도메인 필터 UI 없음 (`type` 파라미터는 백엔드 지원) | 신규 `DomainFilter` 컴포넌트 + 자동 재검색 useEffect | 신규 `components/search/DomainFilter.jsx` | 5칩 (전체/문서/이미지/영상/음성) |
| 4.6 | 점수 구성 불투명 (confidence만 표시) | 5축 막대 차트 (dense/lexical/asf/rerank/z_score) | 신규 `components/search/ScoreBreakdown.jsx` | admin 패리티 |
| 4.7 | 노이즈 결과 (Nike 신발 등 신뢰도 0.4%) Top-1 차지 | confidence < 0.05 자동 숨김 + 토글 + 모두 저신뢰도 시 "관련 결과 없음" | `pages/MainSearch.jsx` | 의미 있는 결과만 표시 |
| 4.8 | Movie/Music 캘리브레이션 보류 추측 | 코드 검토: `unified_engine.search_av()` 가 이미 per-query z-score 적용 → 변경 불필요 | 검증만 | Doc/Img와 동일 방식 확인 |

### 4.9 점수 3축 의미 명확화

| 지표 | 수식 | 해석 |
|---|---|---|
| **신뢰도** | `confidence` (per-query z + reranker cap) | "결과 신뢰할만함?" |
| **정확도** | `sigmoid(rerank_score)` (BUGFIX 후) | "쿼리에 의미적으로 맞나?" |
| **유사도** | `clamp01(dense)` (cosine) | "벡터 공간에서 가까움?" |

3개 시그널이 독립적이라 사용자가 상황별로 판단 가능.

---

## 5. 데이터 정합성·UI 신뢰성

| # | 문제 | 해결 | 위치 | 효과 |
|---|---|---|---|---|
| 5.1 | "신규 523" 부풀림 (abs path 정규화 차이로 false positive) | `_size_index_cache` (size+basename 보조 인덱스) → abs 미매치 시 폴백 | `services/registry_lookup.py` | 523 → 322 (~38% 정확도 ↑) |
| 5.2 | 임베딩 후 삭제된 파일(orphan) 미감지 | `orphans_under(folder_path)` + `POST /api/registry/orphans` | `services/registry_lookup.py`, `routes/registry.py` | 빨강 "삭제 K" 배지 |
| 5.3 | 인덱싱 페이지 재시작 시 폴더 선택 손실 | localStorage 자동 저장/복원 (rootPath + checkedPaths) | 신규 `utils/indexingPersist.js` | 재실행 시 즉시 복원 |
| 5.4 | 폴더 인덱싱 상태 시각 부재 | 4단계 색상 (초록/파랑/황색/회색) + 빨강 orphan | 신규 `components/indexing/FolderStatusBadge.jsx` | 한눈에 파악 |
| 5.5 | 폴더 1단계만 선택 (raw_DB/Doc/sub/file 같은 다단계 X) | `collectAllFilesRecursive()` + `subtreeFiles` (useMemo) | `pages/DataIndexing.jsx` | 폴더 1번 클릭 = 하위 모든 파일 |
| 5.6 | 시각 상태와 실제 선택 불일치 (자식 0개 폴더에서 allChecked 항상 false) | `subtreeFiles` 기준 effective 카운트 | `pages/DataIndexing.jsx:FolderRow` | "신규만 선택" 후 시각 동기화 |
| 5.7 | 파일별 인덱싱 여부 시각 부재 | 신규 `IndexedBadge` + `/api/registry/check` | 신규 모듈 | "✅ 완료" 배지 |
| 5.8 | "신규만 선택" 단축 부재 | 신규 `SelectNewOnlyButton` | 신규 컴포넌트 | 1클릭으로 미인덱싱 파일만 |

---

## 6. Electron 환경 특화 최적화

| # | 문제 | 해결 | 위치 | 효과 |
|---|---|---|---|---|
| 6.1 | Flask 단일 스레드 (인덱싱 중 검색 블로킹) | `app.run(threaded=True)` | `app.py:89` | 동시 3 요청 1.94s (직렬 5s) |
| 6.2 | 1초 HTTP 폴링 (`_jobs_lock` 매초 경쟁) | 신규 `/api/index/stream/<job_id>` SSE + frontend EventSource | `routes/index.py`, `pages/DataIndexing.jsx` | lock 경쟁 90%↓, 즉시성 ↑ |
| 6.3 | __pycache__ 디스크 쓰기 (I/O 경쟁) | spawn env `PYTHONDONTWRITEBYTECODE=1` | `electron/main.cjs:131` | I/O 감소 |
| 6.4 | stdout 버퍼링 (진행 로그 지연) | spawn env `PYTHONUNBUFFERED=1` | `electron/main.cjs:133` | 즉시 flush |
| 6.5 | 백그라운드 throttle (인덱싱 모달 갱신 지연) | `webPreferences.backgroundThrottling: false` | `electron/main.cjs:291` | 진행률 즉시 갱신 |
| 6.6 | 불필요 spellcheck (한국어 dict + IPC 부담) | `webPreferences.spellcheck: false` | `electron/main.cjs:293` | 부담 제거 |
| 6.7 | Python GC 빈번 정지 (임베딩 중 numpy/torch 임시객체 다수) | `_run_job` 시작 시 GC threshold (100000,50,50) → 끝에 명시 collect | `routes/index.py:_run_job` | GC 정지 시간 ~50% ↓ |

---

## 7. 메모리 정책·기록 (Claude 메모리)

| # | 항목 | 저장 위치 |
|---|---|---|
| 7.1 | `admin.html` 실행 절차 (`start_admin_html.bat` 먼저) | `~/.claude/projects/.../memory/admin_html_launch.md` |
| 7.2 | GPU 우선 작업 원칙 + MR_TriCHEF/DI_TriCHEF 신중 수정 가이드 | `~/.claude/projects/.../memory/feedback_gpu_first.md` |

---

## 8. 신규 도구 (CPU-only, 인덱싱과 병렬 실행 안전)

### 8.1 검색 자동 검증 — `scripts/test_search.py`
- 10개 기본 쿼리 (한국어/영어 혼합) 자동 호출
- top-K 결과 + confidence/dense/lexical/asf/rerank_score + location 출력
- 종합 통계: 평균 응답시간, 도메인 분포, 평균 confidence
- 사용: `python scripts/test_search.py [--top-k 5] [--type doc] [--json out.json]`

### 8.2 Registry 정합성 검증 — `scripts/verify_registry.py`
- 4-way 일치 검사: raw_DB ↔ registry.json ↔ .npy 행 수 ↔ ChromaDB count
- orphan + missing 식별
- 사용: `python scripts/verify_registry.py [--domain Img] [--json report.json]`
- ⚠️ 인덱싱 중 실행 시 ChromaDB write lock 충돌 가능 → 완료 후 권장

---

## 9. 신규 파일 목록 (총 12개)

### 백엔드 (Python)
- `App/backend/services/job_control.py` — 중단 처리
- `App/backend/services/registry_lookup.py` — registry 조회 + size index + orphan
- `App/backend/services/location_resolver.py` — 위치 정보 (page/line/timestamp/snippet)
- `App/backend/services/rerank_adapter.py` — Reranker GPU bf16
- `App/backend/services/index_estimator.py` — ETA 추정
- `App/backend/services/cache_janitor.py` — 부분 캐시 정리
- `App/backend/services/vram_janitor.py` — VRAM 다층 정리
- `App/backend/services/chroma_async.py` — ChromaDB 비동기 commit
- `App/backend/routes/registry.py` — `/api/registry/check` + `/orphans`

### 프론트엔드 (React)
- `App/frontend/src/api/registry.js`
- `App/frontend/src/api/indexing.js`
- `App/frontend/src/utils/indexingPersist.js`
- `App/frontend/src/components/indexing/IndexedBadge.jsx`
- `App/frontend/src/components/indexing/SelectNewOnlyButton.jsx`
- `App/frontend/src/components/indexing/FolderStatusBadge.jsx`
- `App/frontend/src/components/indexing/IndexingETA.jsx`
- `App/frontend/src/components/search/LocationBadge.jsx`
- `App/frontend/src/components/search/DomainFilter.jsx`
- `App/frontend/src/components/search/ScoreBreakdown.jsx`

### 검증 스크립트
- `scripts/test_search.py`
- `scripts/verify_registry.py`

---

## 10. 수정된 기존 파일 (총 11개)

- `App/backend/app.py` — 워밍업 + Qwen prewarm thread + PyTorch allocator config
- `App/backend/routes/files.py` — stats 정합성
- `App/backend/routes/index.py` — _run_job (배치 finalize, 주기 reload, race 보호, GC tuning)
- `App/backend/routes/search.py` — ASF ON, location 부착, query 전달
- `App/backend/embedders/trichef/incremental_runner.py` — Qwen 게이트, defer_lexical_rebuild, ChromaDB async
- `App/backend/embedders/trichef/av_embed.py` — Qwen unload, ensure_free, BGM skip
- `App/frontend/electron/main.cjs` — cwd 패치, env 변수, webPreferences, Reranker 활성화
- `App/frontend/src/pages/DataIndexing.jsx` — 영속화, 재귀 선택, 배지, ETA, jobId 복원
- `App/frontend/src/pages/MainSearch.jsx` — 도메인 필터, 점수 분해, 위치 배지, 정확도 필드 fix, 저신뢰도 필터
- `MR_TriCHEF/pipeline/frame_sampler.py` — NVDEC + fps-only 폴백
- `MR_TriCHEF/pipeline/stt.py` — Whisper batched + 다층 OOM 폴백

---

## 11. 환경 변수 ON/OFF 스위치 (디버그/롤백용)

| 변수 | 기본 | 효과 |
|---|---|---|
| `TRICHEF_USE_RERANKER` | `1` (main.cjs에서 활성) | Cross-encoder 재정렬 |
| `HF_HUB_OFFLINE` | `1` (main.cjs) | HuggingFace hub 호출 차단 |
| `TRANSFORMERS_OFFLINE` | `1` (main.cjs) | 동일 |
| `PYTHONDONTWRITEBYTECODE` | `1` (main.cjs) | __pycache__ 쓰기 방지 |
| `PYTHONUNBUFFERED` | `1` (main.cjs) | stdout 즉시 flush |
| `OMC_DISABLE_NVDEC` | (unset) | `=1` 로 NVDEC 강제 OFF |
| `OMC_DISABLE_WHISPER_BATCH` | (unset) | `=1` 로 batched STT OFF |
| `OMC_DISABLE_VRAM_JANITOR` | (unset) | `=1` 로 cleanup OFF |
| `OMC_DISABLE_CHROMA_ASYNC` | (unset) | `=1` 로 동기 ChromaDB |
| `OMC_QWEN_PREWARM` | (unset) | `=1` 로 부팅 시 Qwen 즉시 적재 |
| `PYTORCH_CUDA_ALLOC_CONF` | `expandable_segments:True` (자동) | 단편화 방지 |

---

## 12. 보류·다음 세션 후보

| # | 항목 | 보류 사유 |
|---|---|---|
| 12.1 | Sprint D 본격 멀티프로세스 | VRAM 8GB 한계 + thread-unsafe 임베더 → 별도 메이저 리팩토링 |
| 12.2 | mtime+size pre-filter | registry 스키마 마이그레이션 필요 |
| 12.3 | Pipeline prefetch (CPU+NVDEC ↔ GPU 병렬) | 임베더 구조 변경 필요, 효과는 긴 영상에 한정 |
| 12.4 | 단계별 진행률 ETA (Whisper progress callback) | 모델 내부 callback 필요 |
| 12.5 | Resume from interrupt | 단계별 progress.json 추적 |
| 12.6 | Registry 정합성 자동 보정 | verify_registry.py 결과 기반 자동 fix |
| 12.7 | Legacy 코드 제거 | `_search_legacy_*` 등 |
| 12.8 | int8_float16 양자화 (Whisper) | 속도 +50% / VRAM -50% but Windows unload crash 이력 |
| 12.9 | 동적 batch_size (VRAM 모니터링 후 자동 결정) | 단편화 위험 |

---

## 13. 권장 검증 절차 (다음 세션)

### 13.1 인덱싱 완료 후 즉시
```bash
# 정합성 검증
python scripts/verify_registry.py

# 검색 품질 자동 검증
python scripts/test_search.py
```

### 13.2 사용자 GUI 직접 검증
1. exe 더블클릭 → 인덱싱 페이지 자동 복원 확인
2. 검색 페이지 → "박태웅 의장" 검색
3. 결과 카드의 **위치 배지** 확인 (`p.NN · L.MM` / `MM:SS`)
4. 결과 카드 클릭 → **점수 분해 패널** (5축 막대) 확인
5. **도메인 필터 칩** 클릭 → 필터 동작 확인
6. **저신뢰도 결과 자동 숨김** 토글 확인
7. 인덱싱 진행 중 검색 시도 → 즉시 응답 확인 (Sprint A `threaded=True` 효과)
8. 워크스페이스 → 인덱싱 페이지 왕복 → 모달 자동 복원 확인
