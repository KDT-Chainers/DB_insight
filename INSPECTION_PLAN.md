# DB_insight 시스템 종합 점검 계획 (야간 실행용)
> 작성일: 2026-05-08 | 대상 커밋: 6ef2fef (BGM 임계값 + 단건 삭제 통합 + 캘리브레이션 갱신)

---

## ⚠️ 새 환경(클론 후) 필수 실행

`Data/` 디렉토리는 `.gitignore` 대상이므로 캘리브레이션 임계값(`Data/embedded_DB/trichef_calibration.json`)이
git에 포함되지 않습니다. 클론 또는 임베딩 재생성 후에는 반드시 아래 명령을 실행해야
doc_page / image / movie / music 도메인의 부적합 쿼리 필터링 임계값이 올바르게 설정됩니다.

```bash
cd <repo_root>
python scripts/recalibrate_query_null.py
# 소요 시간: 약 3~5분 (GPU 가속 시 1분)
# 결과: Data/embedded_DB/trichef_calibration.json 에 TOP-1 null 기반 임계값 저장
#   image    → ~0.2992  (FAR=0.30)
#   doc_page → ~0.2718  (FAR=0.05)
#   movie    → ~0.2985  (FAR=0.05)
#   music    → 0.8500   (상한 캡 — search_av는 임계값 미사용)
```

> **왜 필요한가?** 기존 self-pair 기반 캘리브레이션(doc_page thr=0.9536)은 query→doc 실제
> 점수 분포와 괴리가 커 부적합 쿼리 차단률 0%를 유발했습니다.
> TOP-1 null 분포 방식으로 전환 후 doc_page/image 차단률 90%로 개선됩니다.

---

## 0. 점검 전 체크리스트

```bash
# 실행 전 반드시 확인
cd App/backend
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# → True, NVIDIA GeForce RTX 4070 Laptop GPU 확인

# 현재 캘리브레이션 상태 확인
python -c "
import json, pathlib
p = pathlib.Path('../../Data/embedded_DB/trichef_calibration.json')
if p.exists(): print(json.loads(p.read_text()))"

# BGM 캘리브레이션 상태 확인
python -c "
import json, pathlib
p = pathlib.Path('../../Data/embedded_DB/Bgm/calibration.json')
if p.exists(): print(json.loads(p.read_text()))
else: print('BGM calibration.json 없음 — 기본값 사용 중')"
```

---

## 1. 코드 분석으로 발견된 기존 문제점 (점검 전 사전 파악)

### 🔴 Critical (성능 직접 영향)

| # | 위치 | 문제 | 개선 방향 |
|---|------|------|-----------|
| C1 | `config.py:107` | `DOC_IM_ALPHA=0.35` 이지만 튜닝 결과 최적값 **0.20** (R@5 0.907 vs 0.880) | `"DOC_IM_ALPHA": 0.20` 으로 변경 후 벤치 재확인 |
| C2 | `unified_engine.py:322` | 텍스트 쿼리 시 `q_Z = np.zeros_like(q_Im)` → Z축(DINOv2) **완전 비활성화** | 설계 의도 맞는지 재확인; 실질 2축 검색임 |
| C3 | `unified_engine.py:557` | `search_av()` 에서 `q_Z = q_Im` → Z축이 Im축 **복제** → 독립 신호 아님 | Z=zeros 적용 또는 Z-skip 설계로 통일 |
| C4 | `unified_engine.py:648` | AV 가중치 주석 `α=0.75, γ=0.25` 이지만 실제 코드 `_ALPHA=0.60, _BETA=0.15, _GAMMA=0.25` — **주석 불일치** | 주석 수정 또는 코드 재검토 |
| C5 | `unified_engine.py:427` | 임계값 통과 결과 없을 때 **무조건 전체 fallback** (low_confidence=True로 전부 반환) → 관련 없는 결과 상위 노출 가능 | fallback 조건 강화: CMP < 0.40 이면 빈 결과 반환 옵션 추가 |

### 🟡 Warning (잠재적 품질 저하)

| # | 위치 | 문제 | 개선 방향 |
|---|------|------|-----------|
| W1 | `config.py:71` | `FAR_IMG=0.20` (20% 오탐 허용) — 이미지 임계값이 지나치게 관대 | FAR_IMG를 0.10~0.15로 낮춰 precision 향상 |
| W2 | `calibration.py:52` | `calibrate_domain()` — 동일 모달(doc-doc) 분포 측정이 query-doc 스케일과 불일치 (주석에 언급됨) | crossmodal calibration 적용 범위 확대 |
| W3 | `unified_engine.py:402` | ranking 기준: `fused_scores` (dense+lexical+ASF 혼합) 이지만 confidence 표시는 `dense_scores` 기반 — **랭킹과 신뢰도 비일관** | confidence도 fused_scores 기반으로 통일 검토 |
| W4 | `cmp_scoring.py:62` | `DOMAIN_RAW_FLOOR["audio"]=0.95` 로 설정 (거의 모두 통과 문구 있음) — 실제 필터 효과 없음 | 오디오 도메인 floor 값 재측정 필요 |
| W5 | `blip_caption_triple.py:1` | BLIP 캡션 모델이 **영어 전용** (Salesforce/blip-image-captioning-base) — 한국어 이미지/문서의 텍스트 내용 캡션 품질 저하 | Qwen2-VL 캡션으로 일원화 검토 |
| W6 | `unified_engine.py:774` | `_is_content_stub()` 필터가 날짜코드 파일명(`12-2026-4-27-r-1-o-3-vr.wav`)을 삭제 — 정상 파일 일부 누락 가능 | 필터 조건 재검토 |

### 🔵 Info (구조적 설계 사항 — 의도적이지만 문서화 필요)

| # | 위치 | 내용 |
|---|------|------|
| I1 | `tri_gs.py:36` | `orthogonalize()` 가 Re(1152d)↔Im(1024d) 차원 불일치로 실제 직교화 없이 L2 정규화만 수행 |
| I2 | `config.py:117` | `USE_ASF_DEFAULT=False` — ASF 기본 비활성 (벤치 -20pp 손해). 한국어 특화 vocab 품질 개선 전까지 off 유지 |
| I3 | `config.py:125` | image 도메인 sparse/ASF 화이트리스트 제외 — 벤치 -14pp/-24pp |
| I4 | `search_av():614` | AV 도메인 `abs_thr = q_mu` (전체 segment 평균) — null calibration 아닌 per-query 적응형 |

---

## 2. 점검 영역별 상세 계획

### 2-A. 도메인별 임계값 · 캘리브레이션 점검

#### [Doc 도메인]
```python
# 점검 스크립트 — App/backend 에서 실행
python - <<'EOF'
import json, pathlib
data = json.loads(pathlib.Path("../../Data/embedded_DB/trichef_calibration.json").read_text())
d = data.get("doc_page", {})
print(f"[Doc] mu_null={d.get('mu_null'):.4f}  sigma={d.get('sigma_null'):.4f}  thr={d.get('abs_threshold'):.4f}  FAR={d.get('far')}  N={d.get('N')}  method={d.get('method','self_pair')}")
EOF
```
**점검 기준:**
- `abs_threshold` 범위: 0.25 ~ 0.45 (너무 낮으면 오탐 과다, 너무 높으면 히트율 감소)
- `N` ≥ 100 (캘리브레이션 신뢰성)
- `method` = `crossmodal_v1` 권장 (self-pair 보다 실제 검색 분포 반영)
- FAR = 0.05 확인

#### [Image 도메인]
```python
d = data.get("image", {})
print(f"[Img] mu={d.get('mu_null'):.4f}  sigma={d.get('sigma_null'):.4f}  thr={d.get('abs_threshold'):.4f}  FAR={d.get('far')}  N={d.get('N')}  method={d.get('method','self_pair')}")
```
**점검 기준:**
- FAR=0.20 → 실제 오탐율이 20%인지 샘플링 검증
- `crossmodal_v1` 미적용이면 `calibrate_crossmodal("image", ...)` 재실행 권장

#### [BGM 도메인]
```python
import pathlib, json
p = pathlib.Path("../../Data/embedded_DB/Bgm/calibration.json")
if p.exists():
    print(json.loads(p.read_text()))
else:
    print("⚠ BGM calibration.json 없음 → 기본값 mu=0.40 sigma=0.08 사용 중")
```
**점검 기준:**
- 기본값 mu=0.40 sigma=0.08이 실제 CLAP null 분포와 일치하는지 확인
- BGM 데이터 추가/변경 후 `scripts/bgm_calibrate.py` 재실행 여부

#### [Movie/Rec 도메인]
- AV 도메인은 per-query 캘리브레이션 방식 — 별도 JSON 없음 (설계상 정상)
- `abs_thr = q_mu` (segment 평균) 방식이 적절한지 극단적 쿼리로 검증

---

### 2-B. Hermitian 베타함수 가중치 점검

**현재 수식**: `score = sqrt(A² + (0.4·B)² + (0.2·C)²)`
- A = Re(SigLIP2) 내적, B = Im(BGE-M3) 내적, C = Z(DINOv2) 내적
- `alpha=0.4`, `beta=0.2` — [tri_gs.py:49]

**도메인별 실효 가중치:**

| 도메인 | Re 가중 | Im 가중 | Z 가중 | 비고 |
|--------|---------|---------|--------|------|
| Doc (텍스트 쿼리) | 1.0 | 0.4 | **0** (q_Z=zeros) | 실질 2축 |
| Image (텍스트 쿼리) | 1.0 | 0.4 | **0** (q_Z=zeros) | 실질 2축 |
| Image (이미지 쿼리) | 1.0 | 0.4 | 0.2 | 3축 모두 활성 |
| Movie/Music (AV) | 1.0 | 0.4 | **0.2(=Im 복제)** | Z=Im 중복 |

**점검 항목:**
```python
# 점검: alpha=0.4, beta=0.2 vs alpha=0.5, beta=0.0 벤치마크 비교
# MR_TriCHEF/scripts/incremental_index_and_bench.py 실행
python MR_TriCHEF/scripts/incremental_index_and_bench.py --domain movie --eval-only
python MR_TriCHEF/scripts/incremental_index_and_bench.py --domain music --eval-only
```

---

### 2-C. MR_TriCHEF 파이프라인 점검

#### 검증 항목
1. **Movie 세그먼트 인덱스 무결성**
```python
python - <<'EOF'
import json, numpy as np, pathlib
p = pathlib.Path("Data/embedded_DB/Movie")
Re = np.load(p / "cache_movie_Re.npy")
segs = json.loads((p / "movie_segments.json").read_text())
ids = json.loads((p / "movie_ids.json").read_text())["ids"]
print(f"Re shape: {Re.shape}")
print(f"segments: {len(segs)}, ids: {len(ids)}")
assert Re.shape[0] == len(segs) == len(ids), "⚠ 불일치 — 재인덱싱 필요"
print("✓ Movie 인덱스 정합성 OK")
EOF
```

2. **Music Re축 확인** (SigLIP2-text 통일 여부)
```python
# MR_TriCHEF/pipeline/music_runner.py Re축 설계: SigLIP2 text (1152d)
# Im축: BGE-M3 (1024d), Z축: zeros (1024d)
import numpy as np, pathlib
p = pathlib.Path("Data/embedded_DB/Rec")
Re = np.load(p / "cache_music_Re.npy")
print(f"Music Re shape: {Re.shape}  → dim={Re.shape[1]}")
# 1152 이면 SigLIP2-text 정상, 1024 이면 BGE-M3 사용 중
```

3. **STT 텍스트 품질 샘플 확인**
```python
import json, pathlib
segs = json.loads(pathlib.Path("Data/embedded_DB/Movie/movie_segments.json").read_text())
for s in segs[:5]:
    print(f"[{s.get('file_name','')} {s.get('start_sec',0):.0f}s] "
          f"STT: {s.get('stt_text','')[:100]}")
```

---

### 2-D. DI_TriCHEF 파이프라인 점검

#### 검증 항목
1. **문서 Im_body fusion 상태**
```python
import numpy as np, pathlib
p = pathlib.Path("Data/embedded_DB/Doc")
Im = np.load(p / "cache_doc_page_Im.npy")
body = p / "cache_doc_page_Im_body.npy"
print(f"Im shape: {Im.shape}")
print(f"Im_body 존재: {body.exists()}")
if body.exists():
    B = np.load(body)
    print(f"Im_body shape: {B.shape}  → fusion 활성화됨 (alpha={0.35})")
    print("⚠ 권장: DOC_IM_ALPHA=0.20 (현재 0.35, config.py:107 참고)")
```

2. **3단계 캡션 fusion 상태 (이미지)**
```python
import numpy as np, pathlib
p = pathlib.Path("Data/embedded_DB/Img")
for level in ["L1", "L2", "L3"]:
    fp = p / f"cache_img_Im_{level}.npy"
    if fp.exists():
        print(f"  cache_img_Im_{level}.npy: {np.load(fp).shape} ✓")
    else:
        print(f"  cache_img_Im_{level}.npy: ⚠ 없음 — 단일 캡션 Im 사용 중")
```

3. **doc_page_ids 유효성 확인**
```python
import json, pathlib
ids = json.loads((pathlib.Path("Data/embedded_DB/Doc") / "doc_page_ids.json").read_text())["ids"]
print(f"총 페이지 수: {len(ids)}")
# 샘플 — [파일명]_p{페이지번호} 형식인지 확인
for x in ids[:5]: print(f"  {x}")
```

---

### 2-E. BGM 파이프라인 점검

#### BGM 전용 검색 엔진 점검 (`services/bgm/search_engine.py`)
```python
# BGM 인덱스 무결성
import json, numpy as np, pathlib
p = pathlib.Path("Data/embedded_DB/Bgm")
files = list(p.glob("*.json"))
print(f"BGM 인덱스 파일: {[f.name for f in files]}")

# CLAP 임베딩 shape 확인
clap_file = p / "bgm_clap.npy"
if clap_file.exists():
    emb = np.load(clap_file)
    print(f"CLAP 임베딩 shape: {emb.shape}")  # (N, 512) 예상
```

**BGM 임계값 점검 (`services/bgm/bgm_config.py`):**
- `SCORE_MARGIN_HIGH`, `SCORE_MARGIN_MED` 값 확인
- `CLAP_THRESHOLD` 실제 필터링 효과 검증

---

### 2-F. ASF · Lexical 채널 점검

#### ASF (Adaptive Sieve Filter)
```python
# ASF 토큰셋 무결성
import json, pathlib, numpy as np

# Doc 도메인
p_doc = pathlib.Path("Data/embedded_DB/Doc")
asf_doc = p_doc / "asf_token_sets.json"
if asf_doc.exists():
    sets = json.loads(asf_doc.read_text())
    Re = np.load(p_doc / "cache_doc_page_Re.npy")
    print(f"Doc ASF sets: {len(sets)}  Re rows: {Re.shape[0]}")
    if len(sets) != Re.shape[0]:
        print("⚠ ASF sets 수 불일치 — build_asf_token_sets.py 재실행 필요")
    else:
        print(f"✓ Doc ASF 정합성 OK, 평균 토큰 수: {sum(len(s) for s in sets)/len(sets):.1f}")
```

#### Sparse Lexical
```python
from scipy import sparse as sp, pathlib
sparse_doc = sp.load_npz("Data/embedded_DB/Doc/cache_doc_page_sparse.npz")
print(f"Doc sparse matrix: {sparse_doc.shape}  nnz: {sparse_doc.nnz}")
# (N_pages, vocab_size) — nnz가 0이면 인덱싱 실패
```

---

### 2-G. 쿼리 생성 [제목] · [한줄요약] · [상세] 점검

#### 현재 구현 상태 파악
```python
# 문서 캡션/텍스트 추출 결과 확인
import json, pathlib, os
caption_dir = pathlib.Path("Data/extracted_DB/Doc/captions")
page_text_dir = pathlib.Path("Data/extracted_DB/Doc/page_text")

# 샘플 5개 확인
for f in list(caption_dir.glob("*.json"))[:5]:
    d = json.loads(f.read_text(encoding="utf-8"))
    print(f"\n[파일: {f.name}]")
    print(f"  L1 (제목/짧은설명): {d.get('L1','없음')[:80]}")
    print(f"  L2 (키워드): {d.get('L2','없음')[:80]}")
    print(f"  L3 (상세): {d.get('L3','없음')[:80]}")
```

**점검 기준:**
- L1 = `[제목]` 역할: 1문장, 15단어 이내
- L2 = `[한줄요약]` 역할: 키워드 5~10개, 쉼표 구분
- L3 = `[상세]` 역할: 30~60단어 단락
- 한국어 문서의 경우 BLIP(영어 전용) 대신 Qwen 캡션 적용 여부 확인

#### 이미지 내 텍스트 검색 가능 여부
```python
# OCR 처리 여부 확인
import pathlib
ocr_dir = pathlib.Path("Data/extracted_DB/Img")
ocr_files = list(ocr_dir.rglob("*.txt"))  # OCR 텍스트 파일
print(f"OCR 텍스트 파일 수: {len(ocr_files)}")

# Qwen 캡션이 이미지 내 텍스트를 포함하는지 샘플 확인
caption_dir = pathlib.Path("Data/extracted_DB/Img/captions")
for f in list(caption_dir.glob("*.json"))[:3]:
    d = json.loads(f.read_text(encoding="utf-8"))
    print(f"\n[{f.stem}]")
    print(f"  캡션: {str(d)[:200]}")
```

> **⚠ 설계 갭**: 현재 이미지 내 텍스트(OCR)는 BLIP/Qwen 캡션이 묘사 방식으로 포함하거나 누락할 수 있음. 전용 OCR(pytesseract/EasyOCR) 미적용 시 이미지 내 텍스트는 검색 불가.

---

### 2-H. 유사도·정확도·신뢰도 랭킹 수학적 로직 최종 점검

#### 현재 랭킹 파이프라인 (텍스트 검색)

```
[쿼리] → qwen_expand (N=3 variants)
       → SigLIP2 text → Re (1152d)
       → BGE-M3 dense → Im (1024d)
       → q_Z = zeros (Z축 비활성)
         ↓
[Hermitian score] = sqrt(A² + (0.4B)² + 0²)
         ↓
[substring boost] +0.05×matched_tokens +0.10 if full_match
         ↓
[Weighted min-max fusion]
  w_dense=0.60, w_lex=0.25, w_asf=0.15
  (비활성 채널 → dense로 자동 이전)
         ↓
[abs_threshold 필터]
  abs_thr = μ_null + Φ⁻¹(1-FAR) × σ_null
         ↓
[per-query confidence]
  z = (dense_score - q_mu) / max(q_sig, 0.05)
  conf = Φ(z) = 0.5 × (1 + erf(z/√2))
         ↓
[최종 정렬] → fused_scores 기준 (NOT confidence!)
```

#### 점검 항목

**1. 유사도(similarity) — raw cosine 보존 여부**
```python
# results[i]["similarity"] = raw cosine 값 (정보용)
# 실제 랭킹은 fused_scores 기준인지 확인
```

**2. 정확도(accuracy) — 임계값 통과율**
```python
# 5도메인 각각 10개 관련 쿼리로 top-5 히트율 측정
python scripts/run_bench_all_domains.py  # 있을 경우
```

**3. 신뢰도(confidence) — CMP 계산 일관성**
```python
# search() 반환 confidence vs cmp_scoring.apply_blended_to_results() 불일치 확인
# search()는 erf(z) 방식, cmp_scoring은 sigmoid(α·z+β) 방식 — 두 경로 사용 중
# → routes/trichef.py가 어느 방식을 최종 사용하는지 확인 필요
import pathlib
src = pathlib.Path("App/backend/routes/trichef.py").read_text(encoding="utf-8")
print("cmp_scoring 사용:", "cmp_scoring" in src)
print("blended 사용:", "blended" in src)
```

**4. 중요도 순서: 유사도 → 정확도 → 신뢰도 가중치 검증**

현재 최종 정렬 기준: `fused_scores` (dense 60% + lexical 25% + ASF 15%)

```
권장 우선순위:
  1순위: confidence (Φ(z) 기반 통계적 신뢰도) — 도메인 무관 비교 가능
  2순위: similarity (raw cosine) — 원본 의미 거리
  3순위: fused score — multi-channel 보완

현재 구현: fused_scores 기준 정렬 후 confidence는 표시용만 사용
→ 이는 "유사도→정확도→신뢰도" 의도와 반대일 수 있음 — 재검토 필요
```

---

## 3. 가상 쿼리 테스트 셋 (도메인별 성능 검증)

### 3-A. Doc 도메인 테스트 쿼리

| 유형 | 검색어 | 예상 히트 | 검증 포인트 |
|------|--------|-----------|------------|
| 단순 키워드 | `탄소중립 정책` | Doc 관련 문서 | ASF vocab 포함 여부 |
| 법안 검색 | `재정건전화법안 입법과제` | 국회 보고서 | 노이즈 제거 후 쿼리 확인 |
| 영문 혼합 | `AI regulation policy` | 영문 문서 | bilingual 확장 작동 |
| 한영 크로스 | `인공지능 regulation` | 한영 혼합 문서 | query_expand.expand_bilingual |
| 표/그래프 포함 | `GDP 성장률 그래프` | 그래프 포함 문서 | doc_page Im 채널 |
| 이미지 내 텍스트 | `2024년 예산안 표` | 표가 있는 페이지 | OCR 유무 확인 |
| 부적합 필터 | `오늘 날씨` | 빈 결과 | fallback 작동 확인 |
| 긴 문장 | `재정건전화를 위한 입법과제와 주요 쟁점에 대한 분석 자료를 찾아줘` | 관련 문서 | 노이즈 제거 적용 확인 |

### 3-B. Image 도메인 테스트 쿼리

| 유형 | 검색어 | 예상 히트 | 검증 포인트 |
|------|--------|-----------|------------|
| 시각 묘사 | `하늘색 배경에 빨간 원` | 해당 이미지 | SigLIP2 Re 채널 |
| 한국어 씬 | `공원에서 산책하는 사람들` | 야외 인물 사진 | Qwen 캡션 한국어 |
| 영문 씬 | `people walking in a park` | 동일 이미지 | bilingual 확장 |
| 다이어그램 | `파이프라인 아키텍처 다이어그램` | 기술 도표 | 캡션 내 기술 용어 |
| 그래프 | `막대 그래프 통계` | 통계 차트 | L2 키워드 캡션 |
| 이미지 내 한글 | `2023 연간보고서` | 표지 이미지 | OCR 유무 |
| 부적합 | `바나나 레시피` | 빈 결과 | FAR_IMG=0.20 필터 |

### 3-C. Movie 도메인 테스트 쿼리

| 유형 | 검색어 | 예상 히트 | 검증 포인트 |
|------|--------|-----------|------------|
| 인물명 | `박태웅 의장` | 해당 강의 영상 | substring boost +0.40 |
| 주제어 | `코스모스` | NGC 코스모스 시리즈 | 파일명 매칭 +1.5 보너스 |
| 시리즈 전체 | `코스모스 에피소드` | E01~E13 전부 | 시리즈 보장 로직 |
| STT 내용 | `인공지능의 미래` | 관련 강연 | BGE-M3 Im 채널 |
| 시각적 씬 | `화산 폭발 장면` | 자연 다큐 | SigLIP2 Re 채널 |
| 부적합 | `피자 레시피` | 빈/저신뢰 결과 | q_mu 임계값 |
| 숫자 파일명 필터 | (내부 테스트) | 001.mp4 등 미포함 | `_is_content_stub` 확인 |

### 3-D. Rec (음성/녹음) 도메인 테스트 쿼리

| 유형 | 검색어 | 예상 히트 | 검증 포인트 |
|------|--------|-----------|------------|
| 강의 주제 | `머신러닝 기초 강의` | STT 포함 강의 | BGE-M3 STT 채널 |
| 발표자명 | `홍길동 발표` | 해당 발표 녹음 | substring boost |
| 영어 강의 | `deep learning tutorial` | 영어 강의 | bilingual 확장 |
| 회의록 | `2024년 3분기 팀 회의` | 회의 녹음 | 날짜+내용 검색 |

### 3-E. BGM 도메인 테스트 쿼리

| 유형 | 검색어 | 예상 히트 | 검증 포인트 |
|------|--------|-----------|------------|
| 분위기 | `잔잔한 피아노 배경음악` | 조용한 BGM | CLAP text 임베딩 |
| 장르 | `업템포 팝 광고음악` | 활기찬 BGM | nlp_query 처리 |
| 악기 | `어쿠스틱 기타 연주` | 기타 중심 | librosa 특징 매칭 |
| 감정 | `슬프고 우울한 분위기` | 장조/단조 | CLAP 감정 매칭 |
| 부적합 | `오늘 점심 메뉴` | 빈/저신뢰 결과 | BGM confidence 임계값 |

---

## 4. 이미지 검색 심화 점검

### 4-A. 문서 내 이미지 (doc_page)

```python
# 문서 페이지가 이미지로 렌더링되었는지 확인
import pathlib
page_imgs = list(pathlib.Path("Data/extracted_DB/Doc/page_images").glob("*.png"))
print(f"렌더링된 페이지 이미지 수: {len(page_imgs)}")
# 샘플 파일명 — {doc_id}_page{n}.png 형식이어야 함
for f in page_imgs[:5]: print(f"  {f.name}")
```

### 4-B. 독립 이미지 파일 캡션 품질

```python
# Qwen vs BLIP 캡션 비교 샘플링
import pathlib, json
qwen_captions = pathlib.Path("Data/extracted_DB/Img/captions")
for f in list(qwen_captions.glob("*.json"))[:3]:
    d = json.loads(f.read_text())
    print(f"\n[{f.stem}]")
    # Qwen 캡션이 한국어인지, 이미지 내 텍스트를 언급하는지 확인
    cap = d.get("caption", d.get("L3", str(d)))
    print(f"  캡션: {cap[:200]}")
    print(f"  한국어 포함: {'✓' if any(ord(c) > 0xAC00 for c in cap) else '✗'}")
```

### 4-C. 이미지 내 텍스트(OCR) 검색 가능 여부 종합 진단

> **현재 상태**: Qwen2-VL 캡션이 이미지 내 텍스트를 자연어 묘사로 포함 가능하나, 정확한 OCR 텍스트 추출은 별도 구현 필요.

```
진단 체크리스트:
□ BLIP 캡션 — 영어 묘사만 (이미지 내 한글 텍스트 인식 불가)
□ Qwen2-VL 캡션 — 한국어 묘사 가능, 이미지 내 일부 텍스트 언급 가능
□ OCR (pytesseract/EasyOCR) — 미구현 (확인 필요)
□ doc_page PNG → 렌더링 후 Im 채널에 텍스트 내용 포함 여부
```

---

## 5. 성능 향상 가능성 요약

### 즉시 적용 가능 (코드 1~2줄)

| 개선항 | 변경 위치 | 예상 효과 |
|--------|-----------|-----------|
| `DOC_IM_ALPHA: 0.35 → 0.20` | `config.py:107` | Doc R@5 +2.7pp (0.880→0.907) |
| `FAR_IMG: 0.20 → 0.10` | `config.py:71` | Image precision ↑, recall 소폭↓ |
| `search_av()` Z축 zeros화 | `unified_engine.py:557` | AV 점수 일관성 ↑ |
| fallback 조건 강화 (빈 결과 허용) | `unified_engine.py:430` | 관련 없는 결과 상위 노출 방지 |

### 중기 적용 (스크립트 재실행 필요)

| 개선항 | 소요 시간 | 예상 효과 |
|--------|-----------|-----------|
| BGM calibration.json 재생성 | ~30분 | BGM 신뢰도 정확도 ↑ |
| Doc crossmodal calibration 재실행 | ~20분 | Doc 임계값 정밀도 ↑ |
| L1/L2/L3 캡션 Qwen으로 재생성 (이미지) | ~2시간 | 한국어 이미지 캡션 품질 ↑ |
| auto_vocab 재빌드 (한국어 특화) | ~30분 | ASF 활성화 가능성 ↑ |

### 장기 검토 (설계 변경)

| 개선항 | 설명 |
|--------|------|
| OCR 통합 | pytesseract/EasyOCR로 이미지·문서 내 텍스트 추출 → Im 채널 품질 향상 |
| confidence 기반 정렬 | fused_scores → blended_confidence 기준 정렬로 변경 |
| ASF vocab 품질 개선 | 한국어 형태소 분석기(Mecab/Kiwi) 도입으로 ASF -20pp 문제 해결 |
| Z축 독립 활용 | doc_page/image 텍스트 쿼리에서도 DINOv2 구조 축 활성화 방안 |

---

## 6. 야간 자동 점검 실행 순서

```bash
# ====================================================
# 실행 환경: App/backend 디렉토리, Python 가상환경 활성화
# 예상 총 소요 시간: 3~5시간
# ====================================================

# STEP 1. 환경 확인 (5분)
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
python -c "from services.trichef.unified_engine import TriChefEngine; e=TriChefEngine(); print('Engine OK:', list(e._cache.keys()))"

# STEP 2. 캘리브레이션 상태 점검 (10분)
python - < scripts/check_calibration.py  # 아래 스크립트 생성 필요

# STEP 3. 인덱스 정합성 점검 (15분)
python - < scripts/check_index_integrity.py

# STEP 4. 도메인별 쿼리 테스트 (60분)
python scripts/domain_bench_queries.py --domains doc image movie music bgm --topk 5

# STEP 5. 이미지 내 텍스트 검색 실험 (30분)
python scripts/test_ocr_search.py  # 이미지 내 텍스트가 있는 샘플로 검색

# STEP 6. 부적합 쿼리 필터링 검증 (20분)
python scripts/test_irrelevant_queries.py  # 오늘 날씨, 피자 레시피 등

# STEP 7. Doc alpha 변경 효과 A/B 테스트 (30분)
python scripts/ab_test_doc_alpha.py --alpha-a 0.35 --alpha-b 0.20

# STEP 8. 결과 리포트 생성
python scripts/generate_inspection_report.py
```

---

## 7. 점검 스크립트 생성 목록 (구현 필요)

다음 스크립트를 `scripts/` 에 생성하여 야간 점검에 활용:

```
scripts/
├── check_calibration.py         # 5도메인 캘리브레이션 상태 점검
├── check_index_integrity.py     # Re/Im/Z/ids/segs 정합성 확인
├── domain_bench_queries.py      # 가상 쿼리 테스트셋 일괄 실행
├── test_ocr_search.py           # 이미지 내 텍스트 검색 실험
├── test_irrelevant_queries.py   # 부적합 쿼리 필터링 검증
├── ab_test_doc_alpha.py         # DOC_IM_ALPHA A/B 테스트
└── generate_inspection_report.py # 결과 JSON → Markdown 리포트
```

---

## 8. 점검 결과 기록 양식

```markdown
## 점검 결과 (날짜: ______)

### 캘리브레이션 현황
| 도메인 | mu_null | sigma_null | abs_thr | FAR | N | 상태 |
|--------|---------|------------|---------|-----|---|------|
| doc_page | | | | 0.05 | | |
| image | | | | 0.20 | | |
| BGM | | | | - | | |

### 도메인별 쿼리 테스트 결과
| 도메인 | Hit@1 | Hit@3 | Hit@5 | 부적합 차단율 | 비고 |
|--------|-------|-------|-------|--------------|------|
| Doc | | | | | |
| Image | | | | | |
| Movie | | | | | |
| Rec | | | | | |
| BGM | | | | | |

### 발견된 신규 문제점
1. 
2. 

### 적용 권장 개선사항 (우선순위)
1. [즉시] DOC_IM_ALPHA 0.35 → 0.20
2. [즉시] 
3. [중기] 
```

---

> **주의사항**: 야간 점검 중 코드 변경 시 `git stash` 로 변경 사항 보관, 메모리 내 자동 커밋·푸시 금지 (memory: feedback_no_auto_commit.md 참조)
