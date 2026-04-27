# Indexing Spec

## 인덱싱 파이프라인

1. 스캔 (`POST /api/index/scan`) — 폴더 1단계 탐색, 파일/폴더 구분
2. 선택 — 프론트에서 체크박스로 파일 선택
3. 시작 (`POST /api/index/start`) — 선택된 파일 경로 목록 전달 → `job_id` 발급
4. 추출 — embedder가 파일에서 텍스트 추출 (OCR / STT / 파싱)
5. 청크 — 의미 단위로 분할
6. 임베딩 — 벡터 생성
7. 저장 — ChromaDB 유형별 컬렉션에 upsert

## 파일 유형 분류 기준 (확장자)

| type  | 확장자 |
|-------|--------|
| doc   | .pdf .docx .txt .hwp .pptx .xlsx |
| video | .mp4 .avi .mov .mkv .wmv |
| image | .jpg .jpeg .png .webp .bmp .gif .tiff |
| audio | .mp3 .wav .m4a .aac .flac .ogg |
| null  | 위 외 모든 확장자 (인덱싱 불가) |

## Embedder 인터페이스

- 위치: `App/backend/embedders/{type}.py`
- 함수 시그니처: `embed(file_path: str, progress_cb=None) -> dict`
  - `progress_cb`는 video embedder만 사용 (`(step, total, detail) -> bool`)
  - callback 반환값이 `True`이면 중단 신호 → embedder는 `{"status": "skipped", "reason": "사용자 중단"}` 반환
- 반환값:
  - `{"status": "done"}` — 성공
  - `{"status": "skipped", "reason": str}` — 미구현 또는 사용자 중단
  - `{"status": "error", "reason": str}` — 실패

## 동영상(video) 임베딩 4단계

video embedder는 파일 하나를 처리할 때 progress_cb로 단계별 진행 상황을 보고한다.

| step | total | detail |
|------|-------|--------|
| 1    | 4     | 프레임 캡셔닝 중... |
| 2    | 4     | 음성 텍스트 변환 중... |
| 3    | 4     | 임베딩 생성 중... |
| 4    | 4     | 벡터DB 저장 중... |

단계 사이마다 `progress_cb` 반환값을 확인하고 `True`이면 즉시 중단한다.

## 중단(Stop) 메커니즘

- `POST /api/index/stop/{job_id}` 호출 시 `_stop_flags[job_id] = True`로 설정
- `_run_job`은 각 파일 처리 전에 stop flag 확인
  - `True`이면 남은 파일 전부 `"skipped"`, 이유 `"사용자 중단"` 처리 후 종료
- video embedder: 각 단계 사이에 progress_cb를 호출하고 반환값이 `True`이면 즉시 중단

## 업데이트 정책

- 같은 file_path로 재인덱싱 시 ChromaDB에 upsert (덮어쓰기)
- 파일 삭제 시 별도 정리 없음 (수동 또는 향후 구현)

## 진행 상태 관리

- `POST /api/index/start` 호출 시 `job_id` 발급
- 프론트는 `GET /api/index/status/{job_id}` 폴링으로 진행 상황 확인
- job 최종 상태:
  - `"done"` — 모든 파일 완료 (일부 skipped/error 포함 가능)
  - `"error"` — 모든 파일 오류
  - `"stopped"` — 사용자가 중단 요청

## 캐시 재사용 (video)

- `extracted_DB/Movie/{stem}_captions.json` 있으면 BLIP 캡셔닝 건너뜀
- `extracted_DB/Movie/{stem}_stt.txt` 있으면 Whisper STT 건너뜀
- `embedded_DB/Movie/{stem}_blip_embs.npy` 있으면 임베딩 생성 건너뜀
