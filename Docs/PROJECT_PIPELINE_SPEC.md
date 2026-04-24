# PROJECT_PIPELINE_SPEC

이 문서는 `C:\Users\Administrator\Desktop\new_project` 저장소의 **현재 구현 코드**를 직접 읽고 정리한 설계/구현/재현 명세서다.  
목표는 다른 개발자가 이 문서만으로 핵심 기능을 거의 동일하게 재구현할 수 있게 하는 것이다.

---

## 1. 프로젝트 개요

- 프로젝트 목적: 오디오/텍스트 전사 데이터를 업로드하고, 키워드+임베딩 기반으로 검색 결과를 반환하는 시스템
- 핵심 목표: 점수 조작 없이 실제 계산값을 노출하고, 저신뢰 질의는 낮게 표시
- 전체 파이프라인 한 줄 요약:
  - `파일 업로드 -> (오디오면 STT) -> dataset.jsonl 저장 -> 인덱스 재구성 -> 검색 질의 -> BM25+임베딩 결합 -> Top1/Top5 반환 -> React 렌더링`
- 기술 스택 요약:
  - Backend: FastAPI, Pydantic, PyYAML
  - Search: `rank-bm25`, `sentence-transformers`, `numpy`
  - STT: `transformers` Whisper ASR pipeline, `librosa`, `torch`, `peft`
  - Frontend: React + TypeScript + Vite
  - Test: pytest, vitest

---

## 2. 전체 폴더 구조

```text
new_project/
  backend/
    app/
      api/main.py
      core/config_loader.py
      models/schemas.py
      services/dataset_store.py
      services/search_service.py
      search/keyword_search.py
      search/embedding_search.py
      search/score_fusion.py
      stt/stt_service.py
      stt/config_loader.py
      stt/model_loader.py
      stt/predictor.py
      stt/audio_loader.py
      stt/result_normalizer.py
      indexing/index_manager.py
      utils/snippet_extractor.py
    configs/app.yaml
    data/
      dataset.jsonl
      uploads/
      transcripts/
    tests/*.py
    requirements.txt
    .env
  frontend/
    src/
      pages/SearchPage.tsx
      services/api.ts
      types/search.ts
      types/upload.ts
      main.tsx
    package.json
    vite.config.ts
  README.md
```

역할 요약:
- `backend`: API, STT, 검색 인덱싱/스코어링, dataset 저장
- `frontend`: 업로드/검색 입력과 결과 렌더링
- `backend/configs/app.yaml`: 런타임 동작 파라미터
- `backend/data`: 업로드 파일, 전사 결과 파일, dataset 저장소
- `backend/tests`: 단위 테스트 + 스모크 스크립트

---

## 3. 전체 실행 흐름 (E2E)

1. 사용자가 UI(`SearchPage`)에서 파일을 업로드
2. 프론트가 `POST /upload`로 multipart 업로드
3. 백엔드가 파일을 `backend/data/uploads`에 저장
4. 파일 타입 분기:
   - `.txt`: 파일 본문을 `original_transcript`로 사용
   - `.csv`: 각 row의 `transcript/text`를 모아 한 문자열로 병합
   - `.json`: 단일 object에서 `transcript`/`stt_transcript` 추출
   - 기타(오디오): STT 수행
5. 오디오면 STT 결과를 `backend/data/transcripts/<stem>.stt.json`으로 저장
6. dataset에 1개 레코드 append (`dataset.jsonl`)
7. `rebuild_index_on_upload=true`면 즉시 전체 인덱스 재구성
8. 사용자가 검색 질의 입력 후 `POST /search` 호출
9. keyword 점수(BM25) 계산
10. embedding 점수(코사인 유사도) 계산
11. min-max 정규화 + 가중 결합 + raw signal 보정으로 최종 점수 산출
12. snippet 추출기로 preview 생성
13. Top1/Top5와 meta를 응답
14. UI가 Top1 카드 + Top5 리스트로 렌더링

---

## 4. 데이터 업로드 로직 상세

구현 파일: `backend/app/api/main.py` (`upload()`)

### 4-1. audio 업로드
- API: `POST /upload`
- 저장 위치: `backend/data/uploads/<filename>`
- 처리:
  - `stt_service.transcribe_audio()` 호출
  - 성공 시 `stt_transcript = stt.transcript`
  - 전사 JSON을 `backend/data/transcripts/<stem>.stt.json` 저장
- dataset 반영:
  - 레코드 1개 생성
  - `original_transcript=""`, `stt_transcript` 채움
- 제약:
  - STT 실패 시 HTTP 400 반환

### 4-2. txt 업로드
- API: `POST /upload`
- 저장 위치: `backend/data/uploads/<filename>`
- 처리:
  - 파일 내용을 `original_transcript`로 사용
  - `stt_transcript=""`
- dataset 반영:
  - 레코드 1개 생성

### 4-3. csv 업로드
- API: `POST /upload`
- 저장 위치: `backend/data/uploads/<filename>`
- 처리:
  - `csv.DictReader`로 row 순회
  - 각 row의 `transcript` 또는 `text`를 추출
  - 모든 row를 줄바꿈으로 병합해서 하나의 `original_transcript` 생성
- dataset 반영:
  - **현재는 1파일=1레코드** (행별 레코드 아님)
- 제약:
  - `id/title/category/stt_transcript/original_transcript` 컬럼 기반 다건 ingest 미지원

### 4-4. json 업로드
- API: `POST /upload`
- 저장 위치: `backend/data/uploads/<filename>`
- 처리:
  - `json.loads()` 후 object에서 `transcript`, `stt_transcript` 추출
- dataset 반영:
  - **현재는 단일 object 전제**
- 제약:
  - JSON array 다건 ingest 미지원

---

## 5. dataset 저장 구조

- 저장 파일: `backend/data/dataset.jsonl`
- 포맷: JSON Lines (한 줄 = 한 레코드)
- 스키마 (`backend/app/models/schemas.py`의 `DatasetRecord`)
  - `id` (필수)
  - `title` (필수)
  - `category` (기본 `"uncategorized"`)
  - `transcript`
  - `stt_transcript`
  - `original_transcript`
  - `source_path`
  - `created_at`
  - `updated_at`

필드 의미:
- `transcript`: 검색용 기본 텍스트(실제 저장 시 `stt_transcript or original_transcript`)
- `stt_transcript`: 오디오 STT 결과
- `original_transcript`: 파일 원문/주어진 전사

예시 (실제 파일 기반):
```json
{"id":"...","title":"pipeline_sample.wav","category":"uploaded","transcript":"...","stt_transcript":"...","original_transcript":"","source_path":"...uploads\\pipeline_sample.wav","created_at":"...","updated_at":"..."}
{"id":"...","title":"...LLM...wav","category":"uploaded","transcript":"...","stt_transcript":"...","original_transcript":"","source_path":"...uploads\\...wav","created_at":"...","updated_at":"..."}
{"id":"...","title":"...스쿼드...wav","category":"uploaded","transcript":"...","stt_transcript":"...","original_transcript":"","source_path":"...uploads\\...wav","created_at":"...","updated_at":"..."}
```

---

## 6. STT 파이프라인 상세

관련 파일:
- `backend/app/stt/stt_service.py`
- `backend/app/stt/config_loader.py`
- `backend/app/stt/audio_loader.py`
- `backend/app/stt/model_loader.py`
- `backend/app/stt/predictor.py`
- `backend/app/stt/result_normalizer.py`

엔트리:
- `STTService.transcribe_audio(file_path)`
- `STTService.batch_transcribe(files)`

흐름:
1. `transcribe_audio`가 파일 존재 확인
2. `audio_loader.load_audio`로 `librosa.load(..., sr=16000, mono=True)`
3. `STTPredictor.transcribe` 호출
4. `STTModelLoader.load`가 모델/프로세서/pipeline 준비
5. `transformers.pipeline("automatic-speech-recognition")` 추론
6. `normalize_stt_output`로 `STTResult` 표준화

반환 구조:
- `transcript`
- `language`
- `segments`
- `status`
- `error_message`
- `engine_name`

실패 처리:
- 파일 없음 -> `status="failed", error_message="audio file not found"`
- 예외 발생 -> `status="failed", error_message=str(exc)`
- 빈 transcript -> `status="failed", error_message="empty transcript from stt engine"`

빈 전사 처리:
- 정상 성공으로 숨기지 않고 실패로 반환

결론(중요):
- 현재 STT는 **“신규 STT 프로젝트 고유 엔진 직결”이 아니라**
- **일반 Hugging Face Whisper ASR pipeline 래퍼 구조**다.

---

## 7. 사용 STT 모델 상세

- `engine_name`: `new_stt_engine_wrapper` (`app.yaml`)
- `model_base_path`: `openai/whisper-large-v3-turbo`
- `engine_path`: `""` (기본 비어있음)
- `adapter_path`: `""` (기본 비어있음)
- `device`: `cpu`

모델 로드 로직 (`model_loader.py`):
- `model_path = engine_path or model_base_path`
- `AutoModelForSpeechSeq2Seq.from_pretrained(model_path, torch_dtype=...)`
- `AutoProcessor.from_pretrained(model_path)`
- `pipeline("automatic-speech-recognition", ...)`

경고 가능성 (실행 로그/코드 기준):
- `torch_dtype is deprecated! Use dtype instead!`
- `chunk_length_s is experimental with seq2seq models`
- suppress token logits processor 관련 경고

`chunk_length_s` 사용 여부:
- 사용 중 (`DecodeConfig.chunk_length_s=30`, predictor에서 전달)

long audio 처리:
- pipeline chunk 기반으로 분할 처리 시도
- 고품질 long-form 안정성은 확인 필요

장점:
- 구현 단순, 빠르게 동작 확인 가능

한계:
- 실제 신규 STT 엔진(별도 predictor/config/decode/model routing)과 동일하지 않음
- 어댑터 경로 미사용 시 도메인 적응 없음
- deprecated/experimental 경고가 남아 있음

---

## 8. 검색 파이프라인 상세

### 8-1. keyword search

- 파일: `backend/app/search/keyword_search.py`
- 방식: BM25 (`rank_bm25.BM25Okapi`)
- 입력: `(doc_id, text)` 목록
- build:
  - `_tokenize(text.lower().split())`
  - corpus로 BM25 인덱스 구성
- score:
  - 질의를 동일 tokenizer로 쪼개고 BM25 점수 산출
  - 각 `doc_id`에 float 점수 맵 반환

### 8-2. embedding search

- 파일: `backend/app/search/embedding_search.py`
- 모델: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- build:
  - 문서 텍스트 임베딩 생성 (`normalize_embeddings=True`)
  - `_doc_matrix`에 저장
- score:
  - 질의 임베딩 생성
  - `np.dot(doc_matrix, query_vec)`로 코사인 유사도 점수 계산

### 8-3. search_text_source

- 지원값: `stt_transcript`, `original_transcript`, `mixed` (`config_loader.py`)
- 선택 함수: `IndexManager._select_text()`
  - `original_transcript`: `original_transcript or transcript`
  - `mixed`: `stt_transcript + "\n" + original_transcript`
  - 기본: `stt_transcript or transcript or original_transcript`
- 기본값: `stt_transcript` (`app.yaml`)
- 현재 meta 반영:
  - `/search` 응답 `meta.search_text_source`는 실제 값이 아니라 `"configured"` 고정

---

## 9. 점수 계산 로직 상세

정규화 함수:
- 파일: `backend/app/search/score_fusion.py`
- `minmax_normalize(scores)`:
  - `norm = (v - min) / (max - min)`
  - `max == min`이면 모두 0.0

1차 결합:
- `fuse_scores(...)`:
  - `fused_norm[doc] = keyword_weight * k_norm + embedding_weight * e_norm`

최종 점수 (`search_service.py`):
- `keyword_signal = keyword_raw / (keyword_raw + 1.0)` (keyword_raw > 0)
- `embedding_signal = clamp((embedding_raw + 1.0)/2.0, 0, 1)`
- `raw_signal = keyword_weight*keyword_signal + embedding_weight*embedding_signal`
- `final_score = 0.6 * norm_score + 0.4 * raw_signal`

low confidence:
- `weak_evidence = (keyword_raw < 0.05) and (embedding_raw < 0.35)`
- `is_low_confidence = (score < low_confidence_threshold) or weak_evidence`

no reliable match:
- `no_reliable_match = (top1_score < no_reliable_match_threshold) or ((top1_keyword < 0.05) and (top1_embedding < 0.35))`

중요 평가:
- 특정 질의/카테고리/문서 가산점 하드코딩은 보이지 않음
- 그러나 아래 값은 config가 아니라 코드 고정:
  - `0.6 / 0.4`
  - `0.05 / 0.35`

---

## 10. snippet / preview 추출 로직

- 파일: `backend/app/utils/snippet_extractor.py`
- 입력:
  - 문서 텍스트
  - 검색 질의
  - `window_size`
- 알고리즘:
  - 문장 분리: 정규식 `(?<=[.!?])\s+|\n+`
  - 질의 토큰과 문장 포함 여부 overlap count 계산
  - overlap 최대 문장 선택
  - 길이 제한 `[:window_size]`

질문 복붙 금지 규칙 준수 여부:
- 코드상 preview는 항상 문서 텍스트 chunk에서 선택
- 질의를 그대로 preview로 반환하는 로직은 없음

UI 노출:
- `SearchPage.tsx`에서 Top1/Top5에 `preview` 그대로 표시

---

## 11. API 명세 (현재 구현 기준)

### 11-1. `GET /health`
- 응답: `{ "status": "ok", "app": "<app_name>" }`
- 내부: 단순 상태 반환

### 11-2. `POST /upload`
- 요청: multipart `file`
- 처리: 파일 저장 + 타입별 파싱 + (오디오면 STT) + dataset append + 옵션 인덱스 rebuild
- 성공 응답 예:
```json
{
  "status": "ok",
  "id": "uuid",
  "source_file": "C:\\...\\uploads\\sample.wav",
  "stt_transcript_file": "C:\\...\\transcripts\\sample.stt.json"
}
```
- 실패 예:
```json
{
  "detail": "STT failed: <error message>"
}
```
- 내부 호출:
  - `DatasetStore.add_record`
  - `STTService.transcribe_audio` (오디오)
  - `_safe_rebuild_index` (설정 true일 때)

### 11-3. `POST /index/rebuild`
- 요청 body: 없음
- 응답: `{ "status": "ok", "records": <count> }`
- 내부: dataset 전체 로드 후 `IndexManager.rebuild`

### 11-4. `POST /search`
- 요청:
```json
{ "query": "질문", "top_k": 5 }
```
- 응답(최소):
```json
{
  "query": "질문",
  "top1": {
    "rank": 1,
    "id": "...",
    "title": "...",
    "preview": "...",
    "score": 0.1104,
    "is_low_confidence": true
  },
  "top5": [...],
  "meta": {
    "keyword_weight": 0.5,
    "embedding_weight": 0.5,
    "search_text_source": "configured",
    "total_candidates": 1,
    "no_reliable_match": true
  }
}
```
- 내부:
  - 인덱스 미존재 시 `_safe_rebuild_index`
  - `SearchService.search`

### 11-5. `POST /stt/transcribe`
- 요청: multipart `file`
- 응답: `STTResult` 직접 반환
- 내부: 파일 저장 후 `STTService.transcribe_audio`

---

## 12. 프론트엔드 구조

핵심 파일:
- `frontend/src/main.tsx`: 앱 진입
- `frontend/src/pages/SearchPage.tsx`: 업로드+검색 단일 페이지
- `frontend/src/services/api.ts`: 백엔드 API 호출
- `frontend/src/types/search.ts`, `upload.ts`: 타입 정의

업로드 UI 흐름:
1. `파일 추가` 버튼 클릭
2. hidden file input 선택
3. `uploadFile()` 호출 (`POST /upload`)
4. 상태 텍스트 업데이트, 최근 업로드 결과 표시

검색 UI 흐름:
1. 질의 입력
2. `search()` 호출 (`POST /search`)
3. `top1` 카드 크게 표시
4. `top5` 리스트 표시
5. low confidence면 빨간 텍스트 표시

Top1 / Top5 렌더링:
- Top1: title, preview, score, low-confidence marker
- Top5: rank/title/score/preview 한 줄 리스트

---

## 13. 설정 파일 명세

파일: `backend/configs/app.yaml`

| key | 기본값 | 의미 | 영향 |
|---|---|---|---|
| `app_name` | `Honest Audio Search` | 앱 이름 | FastAPI title |
| `data_dir` | `./data` | 데이터 루트 | 간접(현재 직접 사용 적음) |
| `upload_dir` | `./data/uploads` | 업로드 파일 저장 위치 | `/upload`, `/stt/transcribe` |
| `dataset_path` | `./data/dataset.jsonl` | dataset 저장 파일 | `DatasetStore` |
| `search_text_source` | `stt_transcript` | 인덱싱 텍스트 선택 | `IndexManager._select_text` |
| `stt.engine_name` | `new_stt_engine_wrapper` | STT 엔진 라벨 | `STTResult.engine_name` |
| `stt.engine_path` | `""` | 대체 모델 경로 | `STTModelLoader` |
| `stt.model_base_path` | `openai/whisper-large-v3-turbo` | 기본 STT 모델명 | `STTModelLoader` |
| `stt.adapter_path` | `""` | LoRA adapter 경로 | `STTModelLoader` |
| `stt.device` | `cpu` | STT 실행 디바이스 | dtype/device 결정 |
| `search.keyword_model_type` | `bm25` | 키워드 검색 타입 | 현재 BM25 고정 구현 |
| `search.embedding_model_name` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 임베딩 모델 | `EmbeddingSearch` |
| `search.keyword_weight` | `0.5` | keyword 가중치 | fusion 계산 |
| `search.embedding_weight` | `0.5` | embedding 가중치 | fusion 계산 |
| `search.low_confidence_threshold` | `0.4` | low confidence 임계치 | `is_low_confidence` |
| `search.no_reliable_match_threshold` | `0.2` | no reliable 임계치 | `meta.no_reliable_match` |
| `search.snippet_window_size` | `220` | preview 최대 길이 | snippet 추출 |
| `indexing.rebuild_index_on_upload` | `true` | 업로드 후 인덱스 갱신 여부 | `/upload` |
| `indexing.batch_size` | `8` | 배치 크기 | 현재 실사용 미미/미사용 |

---

## 14. 테스트 구조

백엔드 테스트:
- `test_stt_service.py`: STT 실패 명시 처리
- `test_dataset_store.py`: dataset append 동작
- `test_score_fusion.py`: 점수 역전/강제 고점 방지 기본 검증
- `test_search_service.py`: 무관 질의 low confidence/no_reliable_match 검증
- `test_snippet_extractor.py`: preview가 질의 복붙이 아닌지 검증
- `test_api_schema.py`: `/search` 응답 스키마 최소 형태

프론트 테스트:
- `SearchPage.test.tsx`: 업로드/검색 입력 렌더링 확인

스모크 스크립트(정식 테스트와 별도):
- `stt_smoke_run.py`
- `e2e_audio_pipeline_run.py`
- `search_bad_query_run.py`

테스트 부족 영역:
- CSV/JSON ingest 상세 규칙 검증 부족
- `/upload` 타입별 edge case(깨진 JSON, 빈 CSV 등) 부족
- `search_text_source` meta 정확성 검증 없음(현재 고정값)
- CORS/API 네트워크 레벨 e2e 부족

회귀 테스트로 꼭 남겨야 할 항목:
- 무관 질의 고점 방지
- STT 실패 명시 노출
- preview 원문 기반 보장
- 업로드 후 인덱스 반영 여부

---

## 15. 현재 구현의 문제점 / 리스크 / 개선 필요점

1. **STT 엔진 실연결 문제**
   - 현재는 HF Whisper pipeline 래퍼
   - “신규 STT 프로젝트 고유 predictor/config/decode 엔진”을 직접 가져온 상태는 아님

2. **CSV/JSON ingest 한계**
   - CSV: 행별 레코드 생성이 아니라 한 레코드 병합
   - JSON: 배열 다건 처리 미지원 (단일 object 전제)

3. **검색 스코어 하드코딩 일부 존재**
   - `0.6/0.4`, `0.05/0.35`가 코드 상수
   - config로 완전히 분리되지 않음

4. **meta.search_text_source 부정확**
   - 실제 사용 source가 아니라 `"configured"` 문자열 고정

5. **low confidence 보수성 튜닝 여지**
   - 조건식은 있으나 threshold가 데이터셋 규모/도메인에 최적화됐는지 확인 필요

6. **UI 업로드 가시성 제한**
   - 레코드 생성 수, 반영된 dataset ID, ingest 상세가 UI에 없음
   - 업로드 결과 추적이 제한적

7. **README와 실제 구현 불일치**
   - README는 일부 확장 규칙/원칙 중심 설명이 많고, 현재 코드 현실(예: CSV/JSON 다건 미지원)과 차이 있음

8. **보안 리스크**
   - `.env`에 민감 토큰이 저장되어 있고 버전 관리 제외 여부 확인 필요 (확인 필요)

---

## 16. 다른 프로젝트에서 재구현하려면 필요한 핵심 규칙

1. 검색 모델은 2개만 유지:
   - 키워드 1개(BM25/TF-IDF 중 택1)
   - 임베딩 1개(sentence-transformers)
2. 특정 질의/카테고리/문서 하드코딩 가산점 금지
3. 무관 질의는 낮은 score + low confidence/no reliable match 표시
4. STT 실패를 숨기지 말고 `status/error_message`를 명시
5. 업로드 즉시 dataset 반영 후 인덱스 갱신 정책을 명확히 정의
6. Top1은 “정답”이 아니라 “가장 유사한 결과”로만 표현
7. preview는 질의 복붙이 아니라 원문 구간 기반으로 생성
8. config 중심으로 가중치/threshold/모델 경로를 분리

---

## 부록 A: 실제 구현 파일/함수 인덱스

- 업로드 진입: `app.api.main.upload`
- STT API: `app.api.main.transcribe`
- 검색 API: `app.api.main.search`
- 인덱스 리빌드: `app.api.main.rebuild_index`
- STT 서비스: `app.stt.stt_service.STTService`
- STT 추론: `app.stt.predictor.STTPredictor.transcribe`
- 모델 로드: `app.stt.model_loader.STTModelLoader.load`
- 데이터 저장: `app.services.dataset_store.DatasetStore.add_record`
- 텍스트 소스 선택: `app.indexing.index_manager.IndexManager._select_text`
- 키워드 검색: `app.search.keyword_search.KeywordSearch`
- 임베딩 검색: `app.search.embedding_search.EmbeddingSearch`
- 점수 결합: `app.search.score_fusion.fuse_scores`
- 최종 점수/신뢰도: `app.services.search_service.SearchService.search`
- snippet 추출: `app.utils.snippet_extractor.extract_best_snippet`

---

## 부록 B: 확인 필요 항목

- `.env` 파일이 git ignore 되어 있는지
- 운영에서 `engine_path`/`adapter_path`를 실제 체크포인트로 사용할 계획인지
- long-audio 품질 기준 및 허용 latency 기준
