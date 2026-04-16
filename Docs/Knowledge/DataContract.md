# Data Contract

## 공통 키
- `file_id`: 파일 식별자
- `chunk_id`: 청크 식별자

## raw_DB
- path, type, size, hash, indexing_status

## extracted_DB
- text, ocr_text, stt_text, chunks, preview

## embedded_DB
- chunk_id, file_id, embedding, metadata
