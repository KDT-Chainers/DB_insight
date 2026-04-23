# TRI-CHEF Admin UI (Gradio)

관리자용 **전수 검사** 인터페이스. 메인 검색 UI 와 완전히 분리된 별도 프로세스
에서 동작하며, 기존 파일에 간섭하지 않는다.

## 아키텍처

```
┌───────────────────┐   HTTP /api/admin/*   ┌──────────────────────┐
│ Gradio (7860)     │─────────────────────▶ │ Flask 백엔드 (5001) │
│ .venv-admin       │                       │ (기존 venv)          │
│ ← gradio,         │                       │ ← TriChefEngine      │
│   pandas,         │                       │   (싱글턴 재사용)    │
│   requests        │                       └──────────────────────┘
└───────────────────┘
```

- Admin 프로세스는 gradio/pandas/requests 만 의존 (~150MB)
- 엔진은 백엔드 싱글턴을 HTTP 로 호출 → 이중 로딩/메모리 낭비 없음
- read-only 엔드포인트: `/api/admin/inspect`, `/api/admin/doc-text`,
  `/api/admin/file`, `/api/admin/domains`

## 실행

### 전제

메인 Flask 백엔드(`App/backend/app.py`)가 `127.0.0.1:5001` 에서 구동 중이어야
한다. 없으면 Gradio 시작 직후 "백엔드 연결 실패" 배너가 표시된다.

### Windows

```cmd
cd App\admin_ui
run_admin.bat
```

첫 실행 시 `.venv-admin/` 생성 + 의존성 설치 (~1분). 이후 실행은 바로 뜬다.

### Linux / macOS

```bash
cd App/admin_ui
./run_admin.sh
```

### 환경변수

- `TRICHEF_BACKEND` — 백엔드 주소 (기본 `http://127.0.0.1:5001`)

## 기능

1. **검색 실행** — 쿼리 + 도메인(image/doc_page) + top-N 슬라이더 + 채널 토글
2. **전수 결과 테이블** — rank / id / dense / lexical / asf / rrf / confidence /
   z_score (정렬/복사 가능)
3. **상세 패널** — 행 클릭 시 해당 페이지 원문 + 매칭 토큰 **형광 하이라이트**
4. **CSV 내보내기** — 결과 테이블 그대로 다운로드

## 용어 매핑

| UI 표시          | 내부 값                                     |
| ---------------- | ------------------------------------------- |
| 유사도 (dense)   | Hermitian(Re,Im,Z) 3축 복소 점수            |
| 어휘일치 (lexical) | BGE-M3 sparse 채널 점수                     |
| ASF              | auto_vocab 기반 쿼리 ∩ 문서 IDF 합산        |
| RRF              | 3 채널 reciprocal rank fusion               |
| 신뢰도 (confidence) | Φ((s − μ_null) / σ_null) — calibration 기반 |
| z_score          | (dense − μ_null) / σ_null                   |

## 디렉토리 구조

```
App/admin_ui/
├── gradio_app.py       ← 메인 엔트리포인트
├── requirements.txt
├── run_admin.bat
├── run_admin.sh
├── README.md
└── .venv-admin/        ← (자동 생성, gitignore 대상)
```

## 유지보수 원칙

- 메인 백엔드 / 프론트 파일을 **절대 건드리지 않는다**
- 신규 엔드포인트가 필요하면 `App/backend/routes/trichef_admin.py` 에만 추가
- Gradio 버전 업그레이드는 `requirements.txt` 상한만 수정 후 `.venv-admin/`
  삭제 → 재실행

## 제거

```bash
rm -rf App/admin_ui/
# backend 에 남은 trichef_admin 라우트도 제거하려면:
#   - App/backend/routes/trichef_admin.py 삭제
#   - App/backend/app.py 에서 import / register_blueprint 2줄 제거
```
