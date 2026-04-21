# M11 동영상 의미 검색 시스템 — 구현 스펙

> **App 통합 버전**: 이 문서는 `App/backend/embedders/video.py` 구현 기준이다.
> 독립 실행 스크립트(embed.py / search.py)를 App에 통합한 것으로, 캐시 경로가 다르다.

---

## 시스템 전체 개념

M11은 동영상에서 **시각 정보(BLIP 캡셔닝)**와 **음성 정보(Whisper STT)** 두 가지를 추출해서,
각각 `multilingual-e5-large` 모델로 임베딩한 뒤, ChromaDB에 저장하고
쿼리가 들어오면 두 임베딩을 가중합으로 검색하는 시스템이다.

### 핵심 원칙

1. **이미지 파일은 저장하지 않는다.**
   프레임을 추출하되 BLIP으로 영어 캡션 텍스트만 뽑아서 저장한다.

2. **캐시를 최우선으로 재사용한다.**
   `extracted_DB/Movie/{stem}_captions.json`, `extracted_DB/Movie/{stem}_stt.txt`가 이미 있으면
   BLIP/Whisper를 절대 다시 실행하지 않는다.

3. **e5 모델은 multilingual이라 한국어 쿼리 ↔ 영어 캡션이 같은 벡터 공간에 매핑된다.**

4. **임베딩 시 `passage:` 접두사, 검색 시 `query:` 접두사를 반드시 붙인다.**

---

## 파이프라인 순서 (4단계)

```
[MP4 영상]
    │
    ├─── Step 1: 프레임 캡셔닝 (BLIP)
    │       매 30프레임마다 1장 추출 (이미지 파일 저장 X)
    │       각 프레임 → BLIP → 영어 캡션 1문장
    │       캐시: extracted_DB/Movie/{stem}_captions.json
    │
    ├─── Step 2: 음성 텍스트 변환 (Whisper STT)
    │       MP4 음성 → Whisper medium → 한국어 텍스트
    │       캐시: extracted_DB/Movie/{stem}_stt.txt
    │
    ├─── Step 3: 임베딩 생성 (e5-large)
    │       동적 가중치 버킷 배정 (9분위)
    │       양방향 청킹 (BLIP: 10개씩, STT: 400자/100자 오버랩)
    │       "passage: " 접두사 + e5-large → 1024d 벡터
    │       캐시: embedded_DB/Movie/{stem}_blip_embs.npy
    │             extracted_DB/Movie/{stem}_blip_chunks.json
    │             embedded_DB/Movie/{stem}_stt_embs.npy
    │             extracted_DB/Movie/{stem}_stt_chunks.json
    │
    └─── Step 4: 벡터DB 저장 (ChromaDB)
            청크별 metadata 포함 upsert
            컬렉션: embedded_DB/Movie/chroma.sqlite3
```

---

## 캐시 경로 규칙

| 파일 | 경로 | 설명 |
|------|------|------|
| BLIP 캡션 | `Data/extracted_DB/Movie/{stem}_captions.json` | list[str] |
| STT 텍스트 | `Data/extracted_DB/Movie/{stem}_stt.txt` | 평문 str |
| BLIP 청크 텍스트 | `Data/extracted_DB/Movie/{stem}_blip_chunks.json` | list[str] |
| STT 청크 텍스트 | `Data/extracted_DB/Movie/{stem}_stt_chunks.json` | list[str] |
| 동적 가중치 | `Data/extracted_DB/Movie/weight_buckets.json` | dict |
| BLIP 임베딩 벡터 | `Data/embedded_DB/Movie/{stem}_blip_embs.npy` | (N, 1024) float32 |
| STT 임베딩 벡터 | `Data/embedded_DB/Movie/{stem}_stt_embs.npy` | (M, 1024) float32 |
| ChromaDB | `Data/embedded_DB/Movie/` | PersistentClient |

---

## ChromaDB metadata (video)

```json
{
  "file_path":    "C:/Users/.../회의.mp4",
  "file_name":    "회의.mp4",
  "file_type":    "video",
  "folder_path":  "C:/Users/.../",
  "chunk_index":  0,
  "chunk_text":   "a woman in a red jacket is standing at a podium",
  "chunk_source": "blip",
  "blip_weight":  0.3,
  "stt_weight":   0.7
}
```

- `chunk_source`: `"blip"` (프레임 캡션) 또는 `""` (STT)

---

## 설정값 (변경 금지)

```python
FRAME_INTERVAL    = 30      # 매 30프레임마다 BLIP 캡션 1개
BLIP_GROUP_SIZE   = 10      # BLIP 캡션 청킹: 10개씩 묶기
STT_CHUNK_SIZE    = 400     # STT 청킹: 최대 400자
STT_CHUNK_OVERLAP = 100     # 청크 간 100자 오버랩
E5_MODEL_NAME     = "intfloat/multilingual-e5-large"
BLIP_MODEL_NAME   = "Salesforce/blip-image-captioning-base"
WHISPER_MODEL     = "medium"

# 동적 가중치 버킷 9단계
BUCKET_WEIGHTS = [
    (0.10, 0.90), (0.20, 0.80), (0.30, 0.70),
    (0.40, 0.60), (0.50, 0.50), (0.60, 0.40),
    (0.70, 0.30), (0.80, 0.20), (0.90, 0.10),
]
```

---

## 모델 정보

| 역할 | 모델 | 비고 |
|------|------|------|
| 프레임 캡셔닝 | `Salesforce/blip-image-captioning-base` | 영어 출력, GPU 권장 |
| STT | `faster-whisper medium` | 한국어, GPU 권장 |
| 텍스트 임베딩 | `intfloat/multilingual-e5-large` | 1024d, 한·영 동일 공간 |

---

## progress_cb 인터페이스

`embed(file_path, progress_cb)` 함수의 `progress_cb`는 `(step, total, detail) -> bool` 시그니처.
- `step`: 현재 단계 (1~4)
- `total`: 전체 단계 수 (4)
- `detail`: 단계 설명 문자열
- 반환값 `True`: 중단 요청 → embedder는 즉시 중단 후 `{"status": "skipped", "reason": "사용자 중단"}` 반환

---

## 검색 방식

- 쿼리 → `"query: {query}"` + e5-large 인코딩 (1024d, L2 정규화)
- ChromaDB에서 파일별 BLIP/STT 청크 벡터 조회
- 청크별 cosine 유사도(내적) 계산 → 파일별 max 값
- 최종 점수 = `blip_weight × blip_score + stt_weight × stt_score`
- 결과 snippet은 유사도가 가장 높은 청크 텍스트

---

## 핵심 설계 결정 요약

| 항목 | 결정 | 이유 |
|------|------|------|
| 이미지 저장 | ❌ 저장 안 함 | BLIP 캡션 텍스트만으로 충분. 용량 절약. |
| BLIP 출력 | 영어 캡션 | e5-large가 영·한 동일 공간에 매핑 → 한국어 쿼리로 영어 캡션 검색 가능 |
| 임베딩 모델 | multilingual-e5-large (1024d) | 한·영 비대칭 검색, passage/query 접두사로 인덱싱·검색 구분 |
| 양방향 청킹 | 순방향 + 역방향 합산 | 청크 경계에서 잘리는 내용 손실 방지 |
| 동적 가중치 | n_frames / (n_frames+stt_len) → 9분위 버킷 | 영상마다 STT량이 달라 일률 50:50 비효율 |
| max-pooling | 청크별 최대 유사도 | 평균 시 특정 내용 희석 방지 |
| 캐시 경로 분리 | extracted_DB ↔ embedded_DB | 텍스트 캐시와 벡터 캐시 역할 분리 명확화 |
| 4단계 progress | progress_cb(step, total, detail) | 프론트 UI에 실시간 단계별 진행 표시 |
