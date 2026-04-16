# Constitution

## 목적
- 프로젝트 전체의 공통 규칙을 정의한다.

## 코드 작성 규칙
- 기능 단위로 모듈을 분리한다.
- 변경은 작은 단위로 수행하고 검증한다.

## 폴더 구조 규칙
- 실행 코드: `App`
- 데이터 저장: `Data`
- 협업 문서: `Docs`

## 데이터 흐름 기준
1. raw_DB 저장
2. extracted_DB 저장
3. embedded_DB 저장

## 네이밍 규칙
- file_id, chunk_id를 기준 키로 사용한다.
- 파일/폴더는 snake_case 또는 kebab-case를 유지한다.
