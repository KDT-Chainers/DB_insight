# MM Tri-CHEF — Movie & Music 검색 구현 로직

> **3축 복소수 검색엔진 (Tri-CHEF)** 의 Movie / Music 도메인 확장 구현 문서.  
> 작성일: 2026-04-23 · 브랜치: `feature/trichef-port`

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
13. [Admin UI 실행 방법](#13-admin-ui-실행-방법)

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
    ├─ BLIP 캡션 (Movie Z축)
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
| **Re** | 시각/의미 (Real) | SigLIP2-SO400M | BGE-M3 | Movie:1152 / Music:1024 |
| **Im** | 텍스트 의미 (Imaginary) | BGE-M3 (Whisper STT) | BGE-M3 (Whisper STT) | 1024 |
| **Z** | 세부 어휘 (Sparse/Caption) | BGE-M3 (BLIP 캡션) | zeros (lexical_rebuild) | 1024 |

### Re=Im 인 이유 (Music)

Music은 **순수 텍스트 도메인** — 이미지 키프레임이 없으므로 시각 축(Re)에 활용할 비주얼 정보가 없다. 대신 STT 텍스트 임베딩(BGE-M3)을 Re·Im 양쪽에 사용하여 텍스트 의미를 두 방향에서 강화한다.  
Movie의 Re는 SigLIP2(1152d)이므로, **Music 도메인 검색 시에는 쿼리 Re 축도 반드시 BGE-M3(1024d) 를 사용해야 차원 불일치를 방지**한다 (`_embed_query_for_domain` 참조).

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
├─ Step 2b: BLIP 캡션 Z 임베딩 (키프레임별)
│    ├─ qwen_caption.caption(frame_path) → str
│    └─ bgem3_caption_im.embed_passage([captions]) → (N_kf, 1024)
│
├─ Step 3: Whisper STT Im 임베딩 (STT 윈도우 청크별)
│    ├─ WhisperModel("medium", language="ko") → stt_segments.json
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
| `keyframe` | SigLIP2(해당 키프레임) | BGE-M3(STT 오버랩) | BGE-M3(BLIP 캡션) | 시각 변화 구간 |
| `stt` | SigLIP2(가장 가까운 키프레임) | BGE-M3(STT 윈도우) | zeros | 정적 구간 STT 보완 |

---

## 4. Music 파이프라인

```
WAV/MP3/M4A/… 파일
│
├─ Step 1: Whisper STT (_get_stt_segments)
│    ├─ WhisperModel("medium", language="ko", vad_filter=True)
│    ├─ 감지 언어 ≠ ko 이고 결과 없음 → 영어로 재시도
│    └─ 캐시: TRICHEF_MUSIC_EXTRACT/{stem_hash}/stt_segments.json
│
├─ Step 2: 슬라이딩 윈도우 청킹 (_window_chunks)
│    ├─ 윈도우: 30s, 오버랩: 50% (step=15s)
│    ├─ 세그먼트 경계를 자르지 않음
│    └─ 캐시: chunks.json
│
└─ Step 3: BGE-M3 임베딩
     ├─ Re = bgem3.embed_passage(texts)   → (N, 1024)
     ├─ Im = Re (동일 텍스트 도메인이므로 Re=Im)
     └─ Z  = zeros (sparse는 lexical_rebuild에서 별도 처리)
```

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
  │    └─ Music: q_Re = BGE-M3(variants) = q_Im  ← 차원 불일치 방지
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
FAR = TRICHEF_CFG["FAR_MOVIE"]  # 0.10 (10% 오탐율)
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
│   ├─ app.py                             ← Gradio Admin UI (이 파일)
│   └─ MR_TriCHEF.md                      ← 이 문서
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
        │       ├─ captions.json    ← BLIP 캡션
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
| `google/siglip2-so400m-patch16-naflex` | Movie Re (시각) | ~3.4 GB | ✅ HuggingFace |
| `BAAI/bge-m3` | Im/Z 텍스트 임베딩 | ~2.3 GB | ✅ HuggingFace |
| `Qwen/Qwen2.5-VL-3B-Instruct` | BLIP 캡션 / 쿼리 확장 | ~6.2 GB | ✅ HuggingFace |
| `faster-whisper medium` | STT (한/영) | ~1.5 GB | ✅ HuggingFace |

**필수 pip 패키지:**
```bash
pip install faster-whisper transformers torch gradio numpy chromadb tqdm
pip install opencv-python pillow scipy
```

---

## 13. Admin UI 실행 방법

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
| 📊 캐시 상태 | 캐시 세그먼트 수, 레지스트리 파일 수, calibration 파라미터 확인 |
| ⚙️ 재인덱싱 | 동영상 / 음원 / 전체 증분 인덱싱 실행 (스트리밍 로그) |
| 🔍 검색 | 쿼리 → Top-K 결과 + 구간 하이라이트 (mm:ss) |
| 📂 파일 목록 | Raw DB 파일 인덱스 상태 점검 (✅/⬜) |

### 검색 결과 예시

```
#1  강의_로봇공학.mp4
점수 0.7823 | 신뢰도 ████████░░ 84%
경로: /data/raw_DB/Video/강의_로봇공학.mp4

매칭 구간:
  - 12:30 ~ 13:00 (91%) 이제 마지막 조립 단계로 넘어가겠습니다
  - 08:15 ~ 08:45 (78%) 로봇 팔이 부품을 정밀하게 집어올립니다
```
