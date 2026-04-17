# Indexing Spec

## 인덱싱 파이프라인

1. 스캔 (`POST /api/index/scan`) — 폴더 재귀 탐색, 파일 유형 분류
2. 선택 — 프론트에서 체크박스로 파일 선택
3. 시작 (`POST /api/index/start`) — 선택된 파일 경로 목록 전달
4. 추출 — embedder가 파일에서 텍스트 추출 (OCR / STT / 파싱)
5. 청크 — 의미 단위로 분할
6. 임베딩 — 벡터 생성
7. 저장 — ChromaDB 유형별 컬렉션에 저장

## 파일 유형 분류 기준 (확장자)

| type | 확장자 |
|------|--------|
| doc | .pdf .docx .txt .hwp .pptx .xlsx |
| video | .mp4 .avi .mov .mkv .wmv |
| image | .jpg .jpeg .png .webp .bmp .gif .tiff |
| audio | .mp3 .wav .m4a .aac .flac .ogg |
| null | 위 외 모든 확장자 (인덱싱 불가) |

## Embedder 인터페이스

- 위치: `App/backend/embedders/{type}.py`
- 함수 시그니처: `embed(file_path: str) -> dict`
- 반환값:
  - `{"status": "done"}` — 성공
  - `{"status": "skipped", "reason": str}` — 미구현
  - `{"status": "error", "reason": str}` — 실패

## 업데이트 정책

- 파일 hash 변경 시 재인덱싱
- 삭제 파일은 soft-delete 후 정리

## 진행 상태 관리

- `POST /api/index/start` 호출 시 `job_id` 발급
- 프론트는 `GET /api/index/status/{job_id}` 폴링으로 진행 상황 확인
- job 상태: `running` / `done` / `error`
