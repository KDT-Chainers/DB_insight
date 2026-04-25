# Movie / Rec (Music) 파이프라인 — 구현 계획서

> 문서 유형: 구현 계획서 (Implementation Plan)
> 대상 시스템: DB_insight · MR_TriCHEF · Movie / Rec 도메인
> 작성일: 2026-04-24 · 버전: v1.0

---

## 1. 개요

### 1.1 목적
동영상(`raw_DB/Movie/*.mp4`) 과 음원(`raw_DB/Rec/*.{m4a,mp3,wav,flac}`) 을 **자막/STT/오디오 임베딩** 기반으로 검색한다. 자연어 질의에 대해 **파일 단위** 로 집계하되, 결과에 **상위 세그먼트 타임라인** 을 함께 반환해 사용자가 해당 시점으로 바로 점프할 수 있게 한다.

Doc/Img 파이프라인과 같은 3축 복소-에르미트 프레임워크를 **재사용**하지만, 멀티미디어 특성상 실제 채널 구성과 검색 집계 방식이 독립적이다.

### 1.2 성공 기준

| 영역 | 지표 | 목표 |
|---|---|---|
| 지연 | p50 search_av (topk=10, movie, 세그먼트 N=수천) | ≤ 300 ms |
| 지연 | 세그먼트화(STT 포함) 처리속도 | ≥ 실시간의 3× (RTF ≤ 0.33) |
| 품질 | 고정 20쿼리 Top-1 파일 정답률 | ≥ 70% |
| 품질 | 세그먼트 타임코드 정확도 (±2초 이내) | ≥ 90% |
| 운영 | AV 도메인 zero-hit 쿼리 (회귀 5쿼리) | 0 / 5 |
| 증분 | 신규 movie 1개 (10분 길이) 흡수 | ≤ 5 분 |

### 1.3 범위
- **Movie**: `.mp4`, `.mov`, `.mkv`, `.avi` — FFmpeg 디코딩 가능한 모든 형식
- **Rec (Music/Audio)**: `.m4a`, `.mp3`, `.wav`, `.flac`, `.aac`, `.ogg`
- **제외**: 이미지/문서 (→ Doc/Img 별도 계획서), 실시간 스트림

---

## 2. 아키텍처

### 2.1 데이터 흐름

```
[RAW]                    [SEGMENT / STT]               [EMBED 3축]                   [INDEX]                 [SEARCH_AV]
raw_DB/Movie/*.mp4  → FFmpeg 씬 분할 or        → Re/Im/Z: 세그먼트 텍스트       → segments.json         → query
raw_DB/Rec/*.m4a    →  고정 구간(예: 30s)       →   (BGE-M3 동일 1024d)          → cache_{movie,music}_   → search_av
                    → Whisper STT → 자막        → + 선택적 CLAP Z축 (오디오)     →   {Re,Im,Z}.npy       → hermitian
                    → Qwen 자막 캡션 (선택)                                                               → 파일 단위 집계
                                                                                                          → topk + 세그먼트 타임라인
```

### 2.2 모델 스택

| 축 / 채널 | 모델 | 차원 | 역할 |
|---|---|---|---|
| STT | `openai/whisper-large-v3` (또는 `whisper-small` 저사양) | — | 발화 → 한국어 텍스트 |
| 캡셔너(옵션) | `Qwen/Qwen2-VL-2B-Instruct` | — | Movie 키프레임 한국어 캡션 |
| Re | `BAAI/bge-m3` dense | 1024 | **Doc/Img 와 다름** — Re=Im 동일 공간 (쿼리가 텍스트라) |
| Im | `BAAI/bge-m3` dense | 1024 | 세그먼트 텍스트 임베딩 |
| Z | `BAAI/bge-m3` dense | 1024 | 기본은 Im 과 동일. 선택적 `laion/clap-htsat-unfused` 로 오디오 Z축 치환 가능 |

### 2.3 핵심 수식 (AV 특수)

```
Hermitian score (동일):  s(q, seg) = √(A² + (α·B)² + (β·C)²)

쿼리 임베딩 (AV 전용):
  q_Re = q_Im  # SigLIP2 대신 BGE-M3 사용 — 세그먼트 텍스트와 차원 일치

Calibration gate (완화):
  if s < abs_threshold * 0.5:   # Doc/Img 의 절반
      skip

파일 집계:
  for seg in all_segments:
      if s(seg) >= thr*0.5:
          file_best[file_path] = max(file_best[file_path], s)
  return top-K files + top-M segments per file
```

Doc/Img 와 달리 **Re 축이 텍스트 공간**이고, **집계 단위가 세그먼트 → 파일**이라는 두 가지가 AV 만의 특성이다.

### 2.4 모듈 구조

```
App/backend/                           ← DI_TriCHEF 와 공유
├── routes/trichef.py                  # POST /api/trichef/search (domain ∈ movie/music 로우팅)
├── services/trichef/
│   ├── unified_engine.py
│   │   ├── _build_av_entry()          # segments.json 로드
│   │   ├── search_av()                # 파일 단위 집계 진입점
│   │   └── _embed_query_for_domain()  # domain=music 면 q_Re=q_Im
│   ├── tri_gs.py                      # hermitian_score (공유)
│   └── calibration.py                 # get_thresholds(domain) (공유)
└── embedders/trichef/
    └── incremental_runner.py
        ├── run_movie_incremental()
        └── run_music_incremental()

MR_TriCHEF/                            ← 병행 사이드프로젝트 (계보)
├── segmenter/                         # FFmpeg 씬/고정 구간
├── stt/                               # Whisper 래퍼
├── audio_embed/                       # CLAP Z축 (옵션)
└── docs/
```

---

## 3. 구현 단계 (WBS)

### Phase 1 — Segmentation / STT 기반 구축
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| M1-1 | FFmpeg 씬 분할 또는 고정 구간 (30s) 전략 결정 | `segmenter/` | 🟡 설계됨 |
| M1-2 | Whisper STT 래퍼 + batch 처리 | `stt/whisper.py` | 🟡 스캐폴드 |
| M1-3 | 세그먼트 메타 스키마 (`start_sec`, `end_sec`, `stt_text`, `caption`, `type`) | `segments.json` | ✅ |
| M1-4 | Qwen 자막 캡션(옵션) — 키프레임 OCR 대체 | `captioner/qwen_vl_ko.py` 재사용 | 🟡 옵션 |

### Phase 2 — 임베딩
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| M2-1 | 세그먼트 텍스트 → BGE-M3 dense | `cache_{movie,music}_{Re,Im,Z}.npy` | ✅ |
| M2-2 | CLAP 오디오 Z축 (선택) | `cache_{movie,music}_Z_clap.npy` | 🟡 실험중 |
| M2-3 | Gram-Schmidt — Re=Im 이면 projection 생략하고 L2-norm | `tri_gs.orthogonalize` 재사용 | ✅ |

### Phase 3 — 인덱스 / 증분
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| M3-1 | `run_movie_incremental()` SHA-256 registry | `incremental_runner.py` | ✅ |
| M3-2 | `run_music_incremental()` | 동일 | ✅ |
| M3-3 | Chroma 컬렉션 (`trichef_movie`, `trichef_music`) 선택적 | `_upsert_chroma` | 🟡 선택 |
| M3-4 | 세그먼트 → 파일 매핑 유지 (`segments.json`) | — | ✅ |

### Phase 4 — 검색 (search_av)
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| M4-1 | `engine.search_av()` 파일 단위 집계 | `unified_engine.py` | ✅ |
| M4-2 | 세그먼트 타임라인 동봉 (top_segments=5) | `TriChefAVResult.segments` | ✅ |
| M4-3 | abs_thr × 0.5 완화 게이트 | 게이트 로직 | ✅ |
| M4-4 | 도메인별 쿼리 임베딩 분기 | `_embed_query_for_domain` | ✅ |

### Phase 5 — Calibration
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| M5-1 | random-pair null 분포 (`calibrate_domain`) 재사용 | `calibration.py` | ✅ |
| M5-2 | AV 도메인별 FAR 설정 | `TRICHEF_CFG["FAR_MOVIE"], FAR_MUSIC` | ⚪ 미정의 (현재 공용 FAR 사용) |
| M5-3 | 폭증 거부 가드 적용 확인 | calibration 가드 | ✅ (공유) |

### Phase 6 — 운영 신뢰성
| ID | 작업 | 산출물 | 상태 |
|---|---|---|---|
| M6-1 | AV 회귀 스위트 (20 쿼리 파일 정답률) | `scripts/bench_av.py` | 🟡 TODO |
| M6-2 | 세그먼트 타임코드 정확도 측정 | `scripts/check_timestamps.py` | 🟡 TODO |
| M6-3 | STT 언어 오탐 검출 (비한국어 필터) | `scripts/fix_non_korean_av.py` | 🟡 TODO |

### Phase 7 — 후속 로드맵 (미착수)
| ID | 작업 | 착수 조건 |
|---|---|---|
| M7-1 | CLAP Z축 정식 채택 여부 (실험 → A/B) | Phase 6 지표 안정화 후 |
| M7-2 | 영상 키프레임 CLIP 임베딩을 Re 축으로 추가 | Re=Im 의 한계가 드러날 때 |
| M7-3 | 자막 파일(.srt, .vtt) 우선 취합 | 자막 제공 코퍼스 확보 시 |
| M7-4 | 화자 분리 (pyannote) → 세그먼트 속성화 | 다화자 코퍼스 요구 시 |

---

## 4. 데이터셋 / 스토리지 계획

| 경로 | 내용 | 비고 |
|---|---|---|
| `Data/raw_DB/Movie/*.mp4` | 원본 영상 | SHA-256 registry |
| `Data/raw_DB/Rec/*.m4a` | 원본 음원 | 동일 |
| `Data/extracted_DB/Movie/{stem}/segments.json` | 세그먼트 메타 | id, start_sec, end_sec, stt_text, caption, type |
| `Data/extracted_DB/Movie/{stem}/keyframes/*.jpg` | (옵션) 키프레임 | Qwen 캡션용 |
| `Data/embedded_DB/Rec/cache_music_{Re,Im,Z}.npy` | 세그먼트 임베딩 | (N_seg, 1024) |
| `Data/embedded_DB/Movie/cache_movie_{Re,Im,Z}.npy` | 동일 | — |
| `Data/embedded_DB/Rec/music_ids.json` | `["{file_id}#{seg_idx}", ...]` | 세그먼트 ID 포맷 |

### 세그먼트 스키마 (`segments.json`)
```json
[
  {
    "id": "movie_042#0007",
    "file_path": "C:/.../movie_042.mp4",
    "file_name": "movie_042.mp4",
    "start_sec": 210.5,
    "end_sec": 240.2,
    "stt_text": "안녕하세요 오늘은 ...",
    "caption": "회의실에서 발표 중인 남자",
    "type": "stt"
  }
]
```

---

## 5. API 계약

### 5.1 검색 요청 예
`POST /api/trichef/search`
```json
{ "query": "웃고 있는 강아지", "domain": "music", "topk": 10, "top_segments": 5 }
```

### 5.2 응답
```json
{
  "top": [
    {
      "file_path": "C:/.../music_03.m4a",
      "file_name": "music_03.m4a",
      "domain": "music",
      "score": 0.78,
      "confidence": 0.96,
      "segments": [
        {"start": 42.0, "end": 72.0, "score": 0.78, "text": "...", "caption": "", "type": "stt"},
        {"start": 120.5, "end": 150.5, "score": 0.71, "text": "...", "caption": "", "type": "stt"}
      ]
    }
  ]
}
```

---

## 6. 테스트 계획

### 6.1 단위
| 대상 | 검증 |
|---|---|
| `_build_av_entry` | segments.json 길이 == Re.shape[0] |
| `search_av` 파일 집계 | 동일 파일 중복 없음, file_best 최댓값 정확 |
| `_embed_query_for_domain(domain="music")` | q_Re == q_Im 차원 일치 |

### 6.2 통합 (신규 작성 TODO)

`MR_TriCHEF/scripts/bench_av.py`  (가칭, Phase 6 산출물)
- 20 고정 쿼리 × {movie, music}
- 각 쿼리별: 정답 파일 Top-1 포함 여부 / 타임코드 허용오차
- 게이트: Top-1 정답률 ≥ 70%, 타임코드 오차 ±2s 내 비율 ≥ 90%

### 6.3 회귀 쿼리 세트 (예시)
Movie: `"회의 발표"`, `"도로 주행"`, `"요리 시연"`, `"스포츠 하이라이트"`, `"인터뷰 장면"`
Music: `"잔잔한 피아노"`, `"밝은 여성 보컬"`, `"하드락 드럼"`, `"재즈 색소폰 솔로"`, `"클래식 오케스트라"`

---

## 7. 운영 · 모니터링

### 7.1 증분 러너 로그
- `run_movie_incremental`: `segmented X segs, STT done, embedded, upserted`
- 실패 파일명 명시 (FFmpeg 코덱 오류 등)

### 7.2 경보 기준
- STT 언어 오탐률 > 10% → 담당자 리뷰
- AV 도메인 평균 topk 파일수가 0 → 집계 로직 / calibration 확인

### 7.3 백업
- `segments.json` 은 Git LFS 또는 타임스탬프 스냅샷 보관 (재생성에 STT 재실행 필요)
- 캐시 npy 는 ids.json 과 함께 복사

---

## 8. 리스크 · 완화

| # | 리스크 | 영향 | 확률 | 완화 |
|---|---|---|---|---|
| AV-R1 | Whisper 한국어 오인식 (고유명사) | Recall 저하 | 중 | 재귀 사전(prompt) 적용, `fix_non_korean_av.py` 정기 검수 |
| AV-R2 | 긴 영상(>1시간) STT 시간 폭증 | 증분 지연 | 중 | 세그먼트 병렬 처리 + batch_size 튜닝 |
| AV-R3 | 동영상 무음 구간 → 빈 세그먼트 | 노이즈 | 저 | 무음 세그먼트 임계 RMS 로 제외 |
| AV-R4 | FFmpeg 코덱 미지원 (HEVC 등) | 파일 누락 | 저 | 사전 코덱 검증 + skip list |
| AV-R5 | search_av 쿼리 임베딩 축 불일치 (Re=SigLIP2 혼입) | 차원 에러 | 저 | `_embed_query_for_domain` 분기 유지 |
| AV-R6 | abs_thr × 0.5 완화로 false positive 과다 | Precision 악화 | 중 | 회귀 쿼리에서 상시 모니터링, 필요시 0.6 / 0.7 로 상향 |
| AV-R7 | CLAP 오디오 임베딩이 텍스트 쿼리와 스케일 불일치 | 점수 왜곡 | 중 | 활성화 시 별도 calibration 실행 |

---

## 9. 의존성

### 9.1 외부 모델
- `openai/whisper-large-v3` (또는 small)
- `BAAI/bge-m3`
- `Qwen/Qwen2-VL-2B-Instruct` (키프레임 캡션 옵션)
- `laion/clap-htsat-unfused` (오디오 Z축 옵션)

### 9.2 외부 도구
- **FFmpeg** — 필수 (씬 분할, 오디오 추출)
- (옵션) pyannote.audio — 화자 분리 확장 시

### 9.3 파이썬 패키지
torch (CUDA), transformers, openai-whisper, ffmpeg-python, soundfile, numpy, FlagEmbedding, flask

---

## 10. Doc/Img 파이프라인과의 독립성

| 항목 | Doc/Img | Movie/Rec |
|---|---|---|
| **진입점** | `run_{image,doc}_incremental` | `run_{movie,music}_incremental` |
| **캐시** | `TRICHEF_{IMG,DOC}_CACHE` | `TRICHEF_{MOVIE,MUSIC}_CACHE` |
| **검색 API** | `engine.search()` | `engine.search_av()` |
| **Re 축 모델** | SigLIP2 (1152d img-text) | BGE-M3 (1024d text-text, Re=Im) |
| **Lexical sparse** | ✅ | ❌ (텍스트만 검색) |
| **ASF 필터** | ✅ | ❌ |
| **세그먼트 집계** | ❌ (페이지/이미지 단위) | ✅ (파일/세그먼트 단위) |
| **Calibration 완화** | abs_thr | abs_thr × 0.5 |

**공유 레이어**: `TriChefEngine` 라우팅, `hermitian_score`, `calibration`, `qwen_expand`, `shared/reranker` (cross-encoder). 이를 통해 단일 `/api/trichef/search` 엔드포인트 뒤에 통합되지만, 데이터 · 파라미터 · 평가 지표는 독립적으로 관리한다.

---

## 11. 산출물 · 문서

| 문서 / 코드 | 위치 |
|---|---|
| 본 계획서 | `MR_TriCHEF/docs/IMPLEMENTATION_PLAN_MOVIE_REC.md` |
| 파이프라인 개요 | `md/TRICHEF_PIPELINE_AND_CONCEPTS.md` |
| (TODO) AV 회귀 스위트 | `MR_TriCHEF/scripts/bench_av.py` |
| (TODO) 타임코드 검증 | `MR_TriCHEF/scripts/check_timestamps.py` |
| 세그먼트 · STT 모듈(계보) | `MR_TriCHEF/` |

---

## 12. 완료 판정 체크리스트

- [x] `run_movie_incremental()` / `run_music_incremental()` 증분 러너
- [x] BGE-M3 기반 세그먼트 임베딩 3축 캐시
- [x] `search_av()` 파일 집계 + 세그먼트 타임라인 반환
- [x] abs_thr × 0.5 완화 게이트
- [x] 도메인별 쿼리 임베딩 분기 (`q_Re = q_Im` for music)
- [x] Calibration 폭증 거부 가드(공유)
- [ ] AV 전용 FAR 설정 (`FAR_MOVIE`, `FAR_MUSIC`) — 현재는 공유 값
- [ ] AV 회귀 스위트 (`bench_av.py`) — 미작성
- [ ] 세그먼트 타임코드 정확도 측정 스크립트 — 미작성
- [ ] STT 비한국어 필터 (`fix_non_korean_av.py`) — 미작성
- [ ] CLAP Z축 A/B 실험 — 실험 전
- [ ] Top-1 파일 정답률 ≥ 70% 검증 — 스위트 작성 후 측정

---

*문서 끝 · `MR_TriCHEF/docs/IMPLEMENTATION_PLAN_MOVIE_REC.md`*
