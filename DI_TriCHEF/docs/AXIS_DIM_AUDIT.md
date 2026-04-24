# TRI-CHEF 3축 차원 감사 (Axis Dimension Audit)

작성일: 2026-04-24  
작성 기준 코드:
- `MR_TriCHEF/pipeline/vision.py`
- `MR_TriCHEF/pipeline/music_runner.py`
- `App/backend/embedders/trichef/siglip2_re.py`
- `App/backend/embedders/trichef/dinov2_z.py`
- `App/backend/embedders/trichef/bgem3_caption_im.py`

---

## 1. 도메인별 3축 실제 차원 (코드 기준)

| 축 | Doc/Img | Movie | Music |
|---|---|---|---|
| **Re** | SigLIP2-SO400M · **1152d** · 이미지 의미 | SigLIP2-SO400M · **1152d** · 프레임 이미지 | BGE-M3 · **1024d** · 30s 윈도우 STT 텍스트 |
| **Z** | DINOv2-large · **1024d** · 이미지 구조 | DINOv2-large · **1024d** · 프레임 이미지 | zeros · **1024d** · 영상 없음(플레이스홀더) |
| **Im** | BGE-M3 · **1024d** · 캡션 텍스트 | BGE-M3 · **1024d** · 프레임 STT 정렬 텍스트 | BGE-M3 · **1024d** · 30s 윈도우 STT 텍스트 |

---

## 2. 교차 도메인 비교 가능성

| 축 | Doc ↔ Movie | Doc ↔ Music | Movie ↔ Music | 비고 |
|---|---|---|---|---|
| **Re** | ✅ 동일 모델·차원 | ❌ 모델·차원 모두 다름 | ❌ 모델·차원 모두 다름 | Music만 이질적 |
| **Z** | ✅ 동일 모델·차원 | ⚠️ 차원 동일, Music은 zero 벡터 | ⚠️ 차원 동일, Music은 zero 벡터 | Music Z는 정보 없음 |
| **Im** | ✅ 동일 모델·차원 | ✅ 동일 모델·차원 | ✅ 동일 모델·차원 | 3개 도메인 공통 공간 |

---

## 3. 확인된 이슈

### 이슈 1: Music Re축 — 모델·차원 불일치 [중대]

**위치**: `MR_TriCHEF/pipeline/music_runner.py` L121  
```python
Re = vec   # BGE-M3 1024d
Im = vec.copy()  # 동일 벡터 복사
```

**문제**:
- Doc/Img, Movie의 Re축은 SigLIP2 1152d (시각 의미 공간)
- Music의 Re축은 BGE-M3 1024d (텍스트 의미 공간)
- 서로 다른 모델·차원으로 생성된 벡터 → 코사인 유사도 비교 불가
- 현재 domain별 분리 검색(top-N 각자) 후 score 합산으로 우회 중이므로 런타임 오류는 없으나, Re축 통합 검색 시 의미 없는 점수 산출

**부가 문제**: Music은 Re = Im (완전 동일 벡터 복사)  
→ Re축과 Im축이 중복 정보 → 검색 다양성 없음

### 이슈 2: Music Z축 — zero 벡터 [보통]

**위치**: `MR_TriCHEF/pipeline/music_runner.py` L25, L123  
```python
Z_DIM_MUSIC = 1024
Z = np.zeros((vec.shape[0], Z_DIM_MUSIC), dtype=np.float32)
```

**문제**:
- Music Z는 모든 벡터가 0 → L2 norm = 0 → 코사인 유사도 미정의 (NaN 또는 0)
- Z축 가중치가 있을 경우 검색 점수 왜곡 또는 NaN 전파 위험
- 현재 `unified_engine.py`의 Z축 score 계산에서 Music Z에 대한 NaN guard 필요

### 이슈 3: music_runner.py 주석 오류 [경미]

**위치**: `MR_TriCHEF/pipeline/music_runner.py` L4 (docstring)  
```python
# 잘못된 주석: "Z=zeros(768d)"
# 실제 코드:   Z_DIM_MUSIC = 1024  →  zeros(1024d)
```

### 이슈 4: frame_sampler.py timestamp 오류 [중대]

**위치**: `MR_TriCHEF/pipeline/frame_sampler.py` L66-75  
```python
# scene change + uniform tick 으로 비균등 추출된 프레임을
# dur/n 으로 균등 분배해 가짜 타임스탬프 생성
step = dur / n
t0 = i * step  # 실제 추출 시각이 아님
```

**문제**:
- scene change로 특정 구간에 프레임이 몰려도 코드는 균등 분포로 가정
- STT 텍스트와 프레임의 시각 정렬 오류 발생
- 관리자 UI 타임라인 점프 기능(seg-btn)의 시각 오차

**원인**: ffmpeg `loglevel=error`로 `showinfo` stderr 출력 억제  
**수정 방법**: `loglevel=info`로 변경 후 stderr에서 `pts_time` 파싱

---

## 4. 개선 방안

### 방안 A: Music Re축 → SigLIP2 text-encoder 통일 (권장)

SigLIP2는 dual-encoder (image + text 모두 1152d 공유 공간)  
→ Music의 STT 텍스트를 SigLIP2 text-encoder로 임베딩하면 Re축 vector space 통일

```python
# music_runner.py 개선안
from .vision import SigLIP2Encoder

sig = SigLIP2Encoder()
Re = sig.embed_texts(win_texts)   # 1152d, Doc/Img/Movie와 동일 공간
sig.unload()

bge = BGEM3Encoder()
Im = bge.embed(win_texts, batch=16)  # 1024d, 텍스트 의미
bge.unload()

Z = np.zeros((len(win_texts), 1024), dtype=np.float32)  # 그대로
```

**장점**: Re축 3개 도메인 통합, Re=Im 중복 해소  
**비용**: Whisper + SigLIP2 + BGE-M3 3모델 순차 로드 필요, Music 재인덱싱 필요

### 방안 B: Music Z축 NaN guard 추가 (즉시 적용 가능)

`unified_engine.py`의 Z축 score 계산 시:
```python
z_score = np.dot(q_Z, doc_Z)
if not np.isfinite(z_score):
    z_score = 0.0
```
또는 Music Z 임베딩 시 zeros 대신 Im 벡터 복사 (정보 손실 없이 NaN 방지)

### 방안 C: frame_sampler.py pts_time 파싱 (인덱싱 완료 후 적용)

```python
# loglevel을 info로 변경하여 pts_time 캡처
cmd = [..., "-loglevel", "info", ...]
proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
import re
pts_list = re.findall(r"pts_time:([\d.]+)", proc.stderr)
# SampledFrame.t_start = float(pts_list[i]) if i < len(pts_list) else i*step
```

---

## 5. 우선순위 요약

| 우선순위 | 이슈 | 영향 | 필요 작업 |
|---|---|---|---|
| 🔴 즉시 | frame_sampler timestamp | STT-프레임 정렬 오류, UI 타임점프 부정확 | 인덱싱 완료 후 수정 + 재인덱싱 |
| 🔴 중요 | Music Re 불일치 | 교차 도메인 Re 검색 무의미 | SigLIP2 text-encoder + 재인덱싱 |
| 🟡 보통 | Music Z zeros → NaN | 점수 왜곡 위험 | unified_engine NaN guard |
| 🟢 경미 | docstring 오류 | 가독성 | 1줄 수정 |
