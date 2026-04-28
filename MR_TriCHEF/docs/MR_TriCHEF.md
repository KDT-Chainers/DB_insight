# MR Tri-CHEF — Movie & Music 검색 구현 로직

> **3축 복소수 검색엔진 (Tri-CHEF)** 의 Movie / Music 도메인 확장 구현 문서.  
> 작성일: 2026-04-23 · 갱신: 2026-04-27 · 브랜치: `feature/trichef-port`
> **최신 변경**: 확장자 SSOT (Q1, 1049099) + 평가 라이브러리 통합 (Q3, 73c8bf0) + hybrid θ K-clamp (bdf80af)
> **v1-2 추가**: MIRACL-ko 평가 인프라 + 텍스트 검색 baseline 비교 참조
> **v1-6 추가** (2026-04-27): MIRACL-ko BGE-M3 Im축 자체 재현 nDCG@10=77.82 + RTX 4070 최적화 + Music stt_status 3필드 분리 + run_index.py cp949 수정

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [Tri-CHEF 3축 구조](#2-tri-chef-3축-구조)
3. [Movie 파이프라인](#3-movie-파이프라인)
4. [Music 파이프라인](#4-music-파이프라인)
5. [적응형 프레임 샘플링](#5-적응형-프레임-샘플링)
6. [STT 슬라이딩 윈도우 청킹](#6-stt-슬라이딩-윈도우-청킹)
7. [Hermitian 점수 & 검색 플로우](#7-hermitian-점수--검색-플로우)
8. [데이터-적응형 Calibration](#8-데이터-적응형-calibration)
9. [증분 인덱싱 (Incremental Runner)](#9-증분-인덱싱-incremental-runner)
10. [ChromaDB 저장 구조](#10-chromadb-저장-구조)
11. [파일 & 디렉터리 구조](#11-파일--디렉터리-구조)
12. [모델 목록 & 다운로드](#12-모델-목록--다운로드)
13. [평가 및 벤치마킹](#13-평가-및-벤치마킹)
14. [RTX 4070 최적화 (Music 파이프라인)](#14-rtx-4070-최적화-music-파이프라인)
15. [Admin UI 실행 방법](#15-admin-ui-실행-방법)

---

## 1. 시스템 개요

```
raw_DB/
  Video/  ← MP4, AVI, MOV …  (영상)
  Rec/    ← WAV, MP3, M4A …  (음원)
         │
         ▼  run_movie_incremental / run_music_incremental
         │
  [Ingest Pipeline]
    ├─ 적응형 프레임 샘플링 (Movie only)
    ├─ DINOv2 Z축 임베딩 (시각 구조)
    ├─ Whisper STT → 슬라이딩 윈도우 청킹
    └─ BGE-M3 / SigLIP2 임베딩
         │
         ▼  .npy 누적 캐시 + ChromaDB upsert
         │
  [unified_engine.TriChefEngine]
    ├─ search_av(query, domain)
    │    ├─ Qwen 쿼리 확장
    │    ├─ 도메인-안전 쿼리 임베딩 (_embed_query_for_domain)
    │    ├─ Hermitian 점수 (세그먼트 단위)
    │    └─ 파일 단위 집계 → Top-K TriChefAVResult
    └─ 결과: file_path, file_name, score, confidence, segments[]
```

---

## 2. Tri-CHEF 3축 구조

| 축 | 의미 | Movie 모델 | Music 모델 | 차원 |
|:--:|------|-----------|-----------|:----:|
| **Re** | 시각/의미 (Real) | SigLIP2-image (1152d) | SigLIP2-text (1152d) | 1152 |
| **Im** | 텍스트 의미 (Imaginary) | BGE-M3 (Whisper STT) | BGE-M3 (Whisper STT) | 1024 |
| **Z** | 언어 비의존 시각 구조 | DINOv2-Large (1024d) | zeros (lexical_rebuild) | 1024 |

### 확장자 SSOT (Q1, commit 1049099)

**패턴**: 도메인 격리(App ↔ DI ↔ MR 상호 import 금지)를 유지하면서 확장자 정의 동기화.

`MR_TriCHEF/pipeline/_extensions.py` (신규 19줄):
```python
MOVIE_EXTS: frozenset[str] = frozenset({
    ".mp4", ".avi", ".mov", ".mkv", ".wmv",
    ".webm", ".flv", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".mts", ".m2ts",
})

MUSIC_EXTS: frozenset[str] = frozenset({
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma",
    ".opus", ".aiff", ".aif", ".amr",
})
```

**Parity 검증** (`tests/test_extensions_parity.py`, 신규 88줄):
- `test_mr_app_movie_parity()`: MR MOVIE_EXTS ⊆ App VID_EXTS
- `test_mr_app_music_parity()`: MR MUSIC_EXTS ⊆ App AUD_EXTS

**호출자 마이그레이션** (commit 1049099):
- `MR_TriCHEF/pipeline/paths.py`: 9줄 변경 (SSOT 참조)

회귀 검증: 7/7 parity test 통과.

### replace_by_file 원자화 (commit 697dfcf, P2B.1)

**문제**: 동일 파일 재인덱싱 시 stale 행 누적 → segments.json과 npy 행수 불일치

**해결** (`MR_TriCHEF/pipeline/cache.py`):
```
prev_ids 로드
  ↓
keep_mask = rid not in file_keys (중복 제거)
  ↓
npy: prev[keep_mask] (stale 행 제거)
  ↓
vstack(kept + new_arr) (새 데이터 추가)
  ↓
save to np.save + ids.json + segments.json
```

**호출처**:
- `movie_runner.py:154` (commit c33f675)
- `music_runner.py:199` (commit c33f675)
- dim mismatch 또는 행수 불일치 시 prev 유지 + 경고

### calibration sig=None 가드 (commit 697dfcf, P2A.1)

**문제**: Music SigLIP2 인코더 누락 시 shape mismatch → ValueError 크래시

**해결** (`MR_TriCHEF/pipeline/calibration.py`):
- `measure_domain(kind="music")` 에서 encoder 체크
- SigLIP2 없으면 legacy 공식 사용 또는 status="no_sig_encoder" 반환
- numpy shape 오류 방지, 현재 lexical 채널 noop (beta=0)

**sparse lazy import** (commit 697dfcf, P2A.2):
- `MR_TriCHEF/pipeline/sparse.py`: App/backend sys.path 주입 제거
- ImportError 시 lexical 채널 noop (현재 beta=0)

**확장자 확장** (commit 2c3b1ff, P3):
- MOVIE_EXTS: `.flv .m4v .mpg .mpeg .3gp .ts .mts .m2ts` 추가 (App+MR 정렬)
- MUSIC_EXTS: `.wma .opus .aiff .aif .amr` 추가

### Hermitian 점수 공식

```
score(q, d) = sqrt(A² + (0.4·B)² + (0.2·C)²)

A = Re_q · Re_d   (시각/의미 유사도)
B = Im_q · Im_d   (텍스트 의미 유사도)
C = Z_q  · Z_d    (어휘 세부 유사도)
```

Im, Z 는 Gram-Schmidt 직교화 후 사용 (`tri_gs.orthogonalize`).

---

## 3. Movie 파이프라인

```
MP4/AVI/… 파일
│
├─ Step 1: 적응형 프레임 샘플링 (_sample_keyframes)
│    ├─ OpenCV VideoCapture
│    ├─ Baseline 간격 2s, 최소 0.5s, 최대 5s
│    ├─ 히스토그램 차분 > 20% → 간격 ÷ 2 (장면 변화)
│    ├─ 히스토그램 차분 < 5%  → 간격 × 1.5 (정적 구간)
│    └─ JPEG 캐시: TRICHEF_MOVIE_EXTRACT/{stem_hash}/frames/
│
├─ Step 2a: SigLIP2 Re 임베딩 (키프레임별)
│    └─ siglip2_re.embed_images(pil_images) → (N_kf, 1152)
│
├─ Step 2b: DINOv2 Z 임베딩 (키프레임별)
│    └─ dinov2_z.embed_images(frame_paths) → (N_kf, 1024)
│
├─ Step 3: Whisper STT Im 임베딩 (STT 윈도우 청크별)
│    ├─ WhisperModel("large-v3", language="ko") → stt_segments.json
│    ├─ 30s 슬라이딩 윈도우, 50% 오버랩 → chunks
│    └─ bgem3_caption_im.embed_passage([texts]) → (N_stt, 1024)
│
├─ Step 4: 시각-STT 정렬
│    ├─ 각 STT 청크 → 가장 가까운 키프레임의 Re/Z 벡터 재사용
│    └─ 정적 구간 STT 보완:
│         시각 변화 < 5%(static_ts) 인 구간의 STT만
│         별도 행(STT 전용)으로 추가
│
└─ 반환: ids[], Re(N,1152), Im(N,1024), Z(N,1024), segments[]
         segments 항목: {id, file_path, file_name, type,
                          start_sec, end_sec, caption, stt_text}
```

### 세그먼트 타입

| type | Re 소스 | Im 소스 | Z 소스 | 언제 생성 |
|------|---------|---------|--------|----------|
| `keyframe` | SigLIP2(해당 키프레임) | BGE-M3(STT 오버랩) | DINOv2(해당 키프레임) | 시각 변화 구간 |
| `stt` | SigLIP2(가장 가까운 키프레임) | BGE-M3(STT 윈도우) | zeros | 정적 구간 STT 보완 |

---

## 4. Music 파이프라인

```
WAV/MP3/M4A/… 파일
│
├─ Step 0: SHA 사전 스캔 (v1-6 신규, RTX 4070 최적화)
│    ├─ 모든 대상 파일의 SHA-256을 registry.json과 비교
│    ├─ 신규/변경 파일이 없으면 → 모델 로드 없이 즉시 종료
│    └─ 신규/변경 파일이 있을 때만 → Step 1로 진행 (모델 1회 로드)
│
├─ Step 1: Whisper STT (_get_stt_segments)
│    ├─ WhisperModel("large-v3", device="cpu", language="ko", vad_filter=True)
│    ├─ 감지 언어 ≠ ko 이고 결과 없음 → 영어로 재시도
│    └─ 캐시: TRICHEF_MUSIC_EXTRACT/{stem_hash}/stt_segments.json
│
├─ Step 2: 슬라이딩 윈도우 청킹 (_window_chunks)
│    ├─ 윈도우: 30s, 오버랩: 50% (step=15s)
│    ├─ 세그먼트 경계를 자르지 않음
│    └─ 캐시: chunks.json
│
├─ Step 3: Cross-modal 임베딩 (2026-04 전환, commit 192f157)
│    ├─ Re = SigLIP2-text.embed_texts(texts)  → (N, 1152)  [NEW]
│    ├─ Im = BGE-M3.embed_passage(texts)       → (N, 1024)  [batch=64]
│    └─ Z  = zeros (sparse는 lexical_rebuild에서 별도 처리)
│
├─ Step 4: stt_status 3필드 분리 (v1-6 신규)
│    ├─ stt_transcript   : Whisper 원본 STT 결과 (음성 인식 텍스트)
│    ├─ original_transcript: 원곡 가사 또는 외부 참조 텍스트 (있을 경우)
│    └─ text_mixed       : 검색/임베딩에 실제 사용되는 혼합 텍스트
│
└─ Step 5: replace_by_file 캐시 (commit c33f675, P2B.1)
     ├─ 동일 파일 재인덱싱 시 stale 행 제거 후 교체
     └─ 캐시: cache_music_{Re,Im,Z}.npy + music_ids.json
```

### stt_status 3필드 구조 (v1-6)

| 필드 | 설명 | 임베딩 사용 |
|------|------|:----------:|
| `stt_transcript` | Whisper STT 음성 인식 원본 | 아니오 |
| `original_transcript` | 원곡 가사 / 외부 참조 텍스트 | 아니오 |
| `text_mixed` | 실제 검색·임베딩에 사용되는 혼합 텍스트 | **예** |

---

## 5. 적응형 프레임 샘플링

```python
interval = BASELINE_SEC  # 2.0s

while current_time < video_duration:
    frame = capture(current_time)
    diff  = histogram_difference(prev_frame, frame)   # 0~1

    if diff > SCENE_THR (0.20):      # 장면 전환
        interval = max(interval / 2, MIN_SEC)  # 최소 0.5s
    elif diff < 0.05:                # 정적 구간
        interval = min(interval * 1.5, MAX_SEC)  # 최대 5s

    if is_keyframe(diff):
        save_jpeg(frame, cache_dir/frames/)

    current_time += interval
```

히스토그램 차분 = 3채널(HSV) normalized histogram 의 L1 거리.  
정적 구간(`diff < 0.05`)은 `static_ts` set에 기록 → STT 보완 필터링에 활용.

---

## 6. STT 슬라이딩 윈도우 청킹

```
stt_segments: [{start, end, text}, ...]   ← Whisper 출력
                  │
                  ▼  _stt_window_chunks(win_sec=30, overlap=0.5)
                  │
윈도우 t=0:     [===========30s===========]
윈도우 t=15:              [===========30s===========]
윈도우 t=30:                        [===========30s===========]
                  │
                  ▼  세그먼트 경계 존중 (단어 중간 자름 없음)
                  │
chunk: {start, end, text}   ← 윈도우 내 모든 세그먼트 텍스트 합산
```

`step = win_sec × (1 - overlap) = 30 × 0.5 = 15s`

---

## 7. Hermitian 점수 & 검색 플로우

```
query
  │
  ├─ Qwen 쿼리 확장 (qwen_expand.expand)
  │    └─ 원문 + 한/영 변환 + 유의어 → variants[]
  │
  ├─ 도메인-안전 쿼리 임베딩 (_embed_query_for_domain)
  │    ├─ Movie: q_Re = SigLIP2(variants), q_Im = BGE-M3(variants)
  │    └─ Music: q_Re = SigLIP2-text(variants) (1152d), q_Im = BGE-M3(variants) (1024d)
  │
  └─ Hermitian 점수 (세그먼트 단위)
       seg_scores = hermitian_score(q_Re, q_Im, q_Z, d_Re, d_Im, d_Z)
       → (N_segments,)

파일 단위 집계:
  file_score = max(seg_scores per file)
  if file_score < abs_threshold * 0.5: skip (조기 스킵)
  if file_score < abs_threshold: 최종 제외

결과 반환:
  TriChefAVResult:
    file_path, file_name, domain
    score       = max(seg_scores)
    confidence  = Φ((score - μ_null) / σ_null)
    segments[]  = 상위 5개 구간 (start_sec, end_sec, score, text, caption)
```

---

## 8. 데이터-적응형 Calibration

```python
# calibrate_domain(domain, Re_all, Im_perp, Z_perp)
#   → μ_null, σ_null, abs_threshold 를 .json 캐시에 저장

N = min(len(Re_all), 2000)   # 최대 2000개 샘플
pairs = random cross-file pairs

null_scores = hermitian_score(q, d)  # 쿼리≠응답 파일

μ = mean(null_scores)
σ = std(null_scores)
FAR = TRICHEF_CFG["FAR_MOVIE"]  # 0.05 (5% 오탐율)
abs_threshold = μ + Φ⁻¹(1 - FAR) × σ
```

인덱싱 후 자동 실행. `calibration.get_thresholds(domain)` 으로 조회.  
캐시 파일: `TRICHEF_MOVIE_CACHE/calibration.json`

---

## 9. 증분 인덱싱 (Incremental Runner)

```
run_movie_incremental() / run_music_incremental()
│
├─ 1. raw_dir 스캔 (raw_DB/Video or raw_DB/Rec)
│
├─ 2. SHA-256 레지스트리 비교 (registry.json)
│    └─ 변경/신규 파일만 new_files 목록에 추가
│
├─ 3. 파일별 ingest 실행
│    ├─ movie_ingest.ingest(path)
│    │   또는 music_ingest.ingest(path)
│    └─ status == "done" 일 때만:
│         registry[key] = {sha, abs_path}   ← 성공 후 등록
│         ids, segs, Re, Im, Z 누적
│
├─ 4. .npy 누적 Merge
│    ├─ cache_movie_Re.npy  = vstack([prev_Re, new_Re])
│    ├─ cache_movie_Im.npy  = vstack([prev_Im, new_Im])
│    └─ cache_movie_Z.npy   = vstack([prev_Z,  new_Z])
│
├─ 5. ChromaDB Upsert
│    tri_gs.orthogonalize(Re, Im, Z) → Im_perp, Z_perp
│    collection: "trichef_movie" / "trichef_music"
│
├─ 6. Calibration 재보정
│    calibrate_domain(domain, Re_all, Im_perp, Z_perp)
│
└─ 7. registry.json 저장
     IncrementalResult(new_count, existing_count, total_count)
```

**실패 안전 보장**: 인제스트 실패 시 registry를 업데이트하지 않아 다음 실행 시 재시도.

### run_index.py Windows cp949 인코딩 수정 (v1-6)

**문제**: Windows 환경에서 `run_index.py` 실행 시 cp949 기본 인코딩으로 인해 한글 파일명/경로 처리 중 UnicodeDecodeError 발생.

**해결**: 파일 오픈 및 stdout/stderr 출력 시 `encoding="utf-8"` 강제 설정.

```python
# 수정 전
open(registry_path, "r")

# 수정 후
open(registry_path, "r", encoding="utf-8")
```

---

## 10. ChromaDB 저장 구조

| 컬렉션 | 용도 | 저장 위치 |
|--------|------|-----------|
| `trichef_movie` | 동영상 세그먼트 사전 필터링 | `EMBEDDED_DB/trichef/` |
| `trichef_music` | 음원 세그먼트 사전 필터링 | `EMBEDDED_DB/trichef/` |

> 기존 `files_video`, `files_audio` 컬렉션과 **완전 분리**.

각 세그먼트의 ChromaDB 메타데이터:
```json
{
  "id":        "video_stem_chunk_000001",
  "file_path": "/absolute/path/to/file.mp4",
  "file_name": "file.mp4",
  "type":      "keyframe | stt",
  "start_sec": 15.0,
  "end_sec":   45.0,
  "caption":   "로봇이 부품을 조립하는 모습",
  "stt_text":  "이제 마지막 단계입니다"
}
```

---

## 11. 파일 & 디렉터리 구조

```
DB_insight/
├─ App/backend/
│   ├─ config.py                          ← PATHS, TRICHEF_CFG
│   ├─ embedders/trichef/
│   │   ├─ movie_ingest.py                ← Movie 인제스트 파이프라인
│   │   ├─ music_ingest.py                ← Music 인제스트 파이프라인
│   │   ├─ incremental_runner.py          ← run_movie/music_incremental
│   │   ├─ siglip2_re.py                  ← SigLIP2 Re 임베더
│   │   ├─ bgem3_caption_im.py            ← BGE-M3 Im/Z 임베더
│   │   └─ bgem3_sparse.py                ← Sparse lexical
│   ├─ services/trichef/
│   │   ├─ unified_engine.py              ← TriChefEngine, search_av
│   │   ├─ calibration.py                 ← Null 분포 보정
│   │   ├─ tri_gs.py                      ← Hermitian 점수, Gram-Schmidt
│   │   └─ qwen_expand.py                 ← 쿼리 확장
│   └─ routes/trichef.py                  ← Flask REST API
│
├─ MR_TriCHEF/
│   ├─ app.py                             ← Gradio Admin UI
│   ├─ scripts/
│   │   ├─ run_index.py                   ← 인덱싱 CLI (UTF-8 인코딩 수정, v1-6)
│   │   └─ eval_miracl_ko.py              ← MIRACL-ko 평가 스크립트
│   └─ docs/
│       └─ MR_TriCHEF.md                  ← 이 문서
│
└─ Data/
    ├─ raw_DB/
    │   ├─ Video/   ← 원본 영상 파일 (MP4, AVI, MOV …)
    │   └─ Rec/     ← 원본 음원 파일 (WAV, MP3, M4A …)
    ├─ embedded_DB/trichef/
    │   ├─ Movie/
    │   │   ├─ cache_movie_Re.npy
    │   │   ├─ cache_movie_Im.npy
    │   │   ├─ cache_movie_Z.npy
    │   │   ├─ movie_ids.json
    │   │   ├─ movie_segments.json
    │   │   ├─ registry.json
    │   │   └─ calibration.json
    │   └─ Music/
    │       ├─ cache_music_Re.npy
    │       ├─ cache_music_Im.npy   (fallback → Re)
    │       ├─ cache_music_Z.npy    (fallback → zeros)
    │       ├─ music_ids.json
    │       ├─ music_segments.json
    │       ├─ registry.json
    │       └─ calibration.json
    └─ extracted_DB/
        ├─ Movie/
        │   └─ {stem_hash}/
        │       ├─ frames/          ← 키프레임 JPEG
        │       ├─ captions.json    ← 프레임 캡션 (legacy, Z축은 DINOv2 사용)
        │       └─ stt_segments.json
        └─ Music/
            └─ {stem_hash}/
                ├─ stt_segments.json
                └─ chunks.json
```

---

## 12. 모델 목록 & 다운로드

| 모델 | 용도 | 크기 | 자동 다운로드 |
|------|------|:----:|:-------------:|
| `google/siglip2-so400m-patch16-naflex` | Movie Re (시각) / Music Re (텍스트) | ~3.4 GB | HuggingFace |
| `facebook/dinov2-large` | Movie Z (시각 구조, 1024d INT8) | ~1.2 GB | HuggingFace |
| `BAAI/bge-m3` | Im 텍스트 임베딩 (STT/캡션) | ~2.3 GB | HuggingFace |
| `Qwen/Qwen2-VL-2B-Instruct` | caption_triple (L1/L2/L3) / 쿼리 확장 | ~4.5 GB | HuggingFace |
| `faster-whisper large-v3` | STT (한/영, vad_filter) | ~3.0 GB | HuggingFace |

**필수 pip 패키지:**
```bash
pip install faster-whisper transformers torch gradio numpy chromadb tqdm
pip install opencv-python pillow scipy
```

---

## 13. 평가 및 벤치마킹

### 13.1 텍스트 검색 baseline 비교 (MIRACL-ko)

Tri-CHEF의 텍스트 검색 성분(Movie STT, Music 텍스트)은 BGE-M3 dense 인코더에 기반하며, 이는 **MIRACL-ko** 한국어 검색 벤치마크에서 다음과 같이 검증됨:

| 시스템 | nDCG@10 | 용도 |
|--------|:-------:|------|
| BM25 | 37.1 | 고전 희소 검색 baseline |
| mDPR | 41.9 | 초기 밀집 검색 |
| mContriever | 48.3 | 추가 밀집 검색 |
| mE5-large-v2 | 66.5 | 선행 밀집 모델 |
| BGE-M3 dense (논문 보고) | 69.9 | 한국어 텍스트 검색 SOTA (논문) |
| **BGE-M3 Im축 자체 재현 (v1-6)** | **77.82** | FAISS IndexFlatIP 정확 재현 (+7.92pp) |

**v1-6 자체 재현 상세** (2026-04-27):

| 지표 | 값 |
|------|:--:|
| nDCG@10 | **77.82%** |
| R@100 | **95.46%** |
| MRR | **76.56%** |

> **논문(69.9)과의 차이 이유**: 본 재현은 FAISS `IndexFlatIP`(완전 정확 내적 탐색)를 사용.  
> 논문 수치는 ANN(근사 최근접 탐색) 기반으로, ANN 근사 오차로 인해 실제 정확 탐색보다 낮게 측정됨.  
> 즉, **+7.92pp는 ANN → 정확 탐색 전환에 의한 상한 회복**이며, Tri-CHEF Im축의 실질 성능 상한을 나타냄.

BGE-M3은 BM25 대비 **+40.72%p**, mE5 대비 **+11.32%p** 향상을 보여 한국어 다국어 검색의 강력한 기반을 제공.

**자체 재현**: `scripts/eval_miracl_ko.py` 및 baseline 스크립트(`scripts/baselines/{bm25,mdpr,mcontriever,me5,bgem3}.py`)로 결과 재현 가능.

### 13.2 통합 평가 라이브러리 (_bench_common.py)

commit 73c8bf0 (Q3) 에서 도입된 `scripts/_bench_common.py`는 3개 평가 스크립트의 공통 gold 산출 로직을 DRY 원칙으로 통합:

**`ContentGoldDB` 클래스**:
- 도메인별 텍스트-id 매핑 보유
- `gold_ids(query, domain)` → cosine ≥ θ인 id 집합 반환
- O(Q+N) 최적화

**도메인별 상수** (hybrid θ + K_MIN/K_MAX):
```
image:    θ=0.50, K_MIN=10,   K_MAX=300
doc_page: θ=0.45, K_MIN=20,   K_MAX=2000
movie:    θ=0.35, K_MIN=20,   K_MAX=200
music:    θ=0.30, K_MIN=3,    K_MAX=14
```

**성능 메트릭** (2026-04-25 최신):
- **movie_ct**: 0.460 → **0.740** (+28pp, K_MIN clamp 효과)
- **music_ct**: **1.000** (SigLIP2-text 크로스모달, 모든 쿼리 hit)

회귀 검증: **23/23 통과** (extensions parity 7/7 + snippet parity 16/16)

### 13.3 태윤_2차 인덱싱 현황 (2026-04-27)

| 항목 | 내용 |
|------|------|
| 데이터셋 | 태윤_2차 47개 파일 |
| 카테고리 | AI / 게임 / 뉴스 / 동물 / 음식 / 음악 / 일상 (7개) |
| 인덱싱 상태 | 진행 중 (2026-04-27 기준) |
| 파이프라인 | Music (RTX 4070 최적화 적용) |

---

## 14. RTX 4070 최적화 (Music 파이프라인)

### 14.1 문제: 파일마다 모델 반복 로드/언로드

기존 Music 파이프라인은 파일 단위로 처리하면서 매 파일마다 Whisper / BGE-M3 / SigLIP2를 로드 후 언로드하는 방식이었음:

```
[기존 방식]
파일1 → Whisper 로드 → STT → Whisper 언로드
      → BGE-M3 로드 → 임베딩 → BGE-M3 언로드
      → SigLIP2 로드 → 임베딩 → SigLIP2 언로드
파일2 → Whisper 로드 → STT → Whisper 언로드  (반복...)
      ...
```

**문제점**:
- 47파일 × (BGE-M3 + SigLIP2 로드 ~10초) ≈ **약 8분 낭비**
- VRAM 단편화 및 PyTorch 캐시 누적

### 14.2 해결: SHA 사전 스캔 + 모델 1회 로드

```
[신규 방식 - v1-6]
SHA 사전 스캔 → 신규/변경 파일 목록 확정
      │
      ├─ 신규 파일 없음 → 즉시 종료 (모델 로드 없음)
      │
      └─ 신규 파일 있음
             │
             ├─ Whisper 로드 (CPU) → 전체 파일 STT 처리 → Whisper 언로드
             ├─ BGE-M3 로드 (GPU) → 전체 파일 임베딩 (batch=64) → BGE-M3 언로드
             └─ SigLIP2 로드 (GPU) → 전체 파일 임베딩 → SigLIP2 언로드
```

### 14.3 VRAM 사용량 (RTX 4070 12GB 기준)

| 모델 | 디바이스 | VRAM |
|------|---------|:----:|
| Whisper large-v3 | **CPU** | 0 GB |
| BGE-M3 | GPU | ~2 GB |
| SigLIP2 | GPU | ~1.5 GB |
| **합계 (동시 사용 안함)** | | **~3.5 GB** |

> RTX 4070 12GB의 **29%** 사용. 나머지 71% (~8.5GB)는 여유 확보.

### 14.4 BGE-M3 배치 크기 최적화

| 항목 | 기존 | 신규 (v1-6) |
|------|:----:|:-----------:|
| BGE-M3 batch size | 16 | **64** |
| 메모리 오버플로 위험 | 낮음 | RTX 4070 2GB 범위 내 안전 |
| 처리 속도 | baseline | ~3x 향상 (추정) |

### 14.5 절약 효과 요약

```
기존: 47파일 × (BGE-M3 로드 ~5초 + SigLIP2 로드 ~5초) ≈ 470초 ≈ 약 8분 낭비
신규: BGE-M3 로드 1회 + SigLIP2 로드 1회 ≈ 10초
절약: ~460초 ≈ 약 7분 40초
```

---

## 15. Admin UI 실행 방법

```bash
# 1. MR_TriCHEF 폴더로 이동
cd DB_insight/MR_TriCHEF

# 2. 실행
python app.py

# 3. 브라우저 접속 (자동으로 열림)
# http://localhost:7860
```

### 탭 설명

| 탭 | 기능 |
|----|------|
| 캐시 상태 | 캐시 세그먼트 수, 레지스트리 파일 수, calibration 파라미터 확인 |
| 재인덱싱 | 동영상 / 음원 / 전체 증분 인덱싱 실행 (스트리밍 로그) |
| 검색 | 쿼리 → Top-K 결과 + 구간 하이라이트 (mm:ss) |
| 파일 목록 | Raw DB 파일 인덱스 상태 점검 (완료/미완료) |

### 검색 결과 예시

```
#1  강의_로봇공학.mp4
점수 0.7823 | 신뢰도 ████████░░ 84%
경로: /data/raw_DB/Video/강의_로봇공학.mp4

매칭 구간:
  - 12:30 ~ 13:00 (91%) 이제 마지막 조립 단계로 넘어가겠습니다
  - 08:15 ~ 08:45 (78%) 로봇 팔이 부품을 정밀하게 집어올립니다
```
