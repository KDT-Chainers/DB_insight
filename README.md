# DB_insight

로컬 파일(문서/영상/이미지/음성)을 자연어로 검색하는 AI 기반 데스크탑 앱.

---

## Architecture

본 프로젝트는 로컬 파일을 의미 기반으로 검색하기 위한 AI 시스템으로,
**실행(App) / 데이터(Data) / 지식(Docs)**을 명확히 분리한 구조를 가진다.

데이터는 다음의 3단계로 처리된다:

- **raw_DB**: 파일 메타데이터 저장
- **extracted_DB**: 텍스트/OCR/STT 등 추출된 콘텐츠
- **embedded_DB**: 임베딩 벡터 (ChromaDB)

AI 협업을 위해 **3계층 구조**를 적용한다:

- **Constitution (1계층)**: 전체 시스템의 공통 규칙
- **Agents (2계층)**: 역할별 전문 코딩 에이전트
- **Knowledge (3계층)**: 에이전트 간 충돌 방지를 위한 최소 스펙

---

## Project Structure

```
DB_insight
├─ App
│  ├─ frontend          ← React + Vite + Electron
│  │  ├─ electron/      ← Electron main/preload
│  │  ├─ src/           ← React 소스
│  │  └─ out/           ← 빌드 결과물 (DB_insight 0.1.0.exe)
│  └─ backend           ← Flask 백엔드
│     ├─ routes/        ← API 엔드포인트
│     ├─ embedders/     ← 파일 유형별 임베더
│     ├─ db/            ← SQLite 초기화
│     └─ dist/          ← PyInstaller 빌드 결과물 (backend.exe)
├─ Data
│  ├─ raw_DB
│  ├─ extracted_DB
│  └─ embedded_DB
└─ Docs
   ├─ Agents/
   ├─ Knowledge/        ← API.md, DataContract.md, ...
   └─ deploy.md         ← 배포 가이드
```

---

## 데스크탑 앱 빌드 및 실행

> 전체 배포 가이드는 `Docs/deploy.md` 참고

### 사전 조건

- Node.js 설치
- Python 설치
- **Windows 개발자 모드 활성화** (필수)
  - `설정 → 개인 정보 및 보안 → 개발자용 → 개발자 모드 ON`

---

### Step 1 — Flask 백엔드 exe 빌드

```bash
cd App/backend
pip install pyinstaller
pyinstaller app.py --onefile --name backend
```

결과물: `App/backend/dist/backend.exe`

---

### Step 2 — Electron 앱 빌드

```bash
cd App/frontend
npm install
rmdir /s /q out              # 이전 빌드 있을 경우
set CSC_IDENTITY_AUTO_DISCOVERY=false && npm run dist
```

결과물: `App/frontend/out/DB_insight 0.1.0.exe`

---

### Step 3 — 앱 실행

`App/frontend/out/DB_insight 0.1.0.exe` 더블클릭

- Flask 백엔드 자동 시작 (포트 5001)
- React UI 자동 로드
- 별도 터미널 실행 불필요

---

### Step 4 — 배포

`App/frontend/out/DB_insight 0.1.0.exe` 파일 하나만 팀원에게 전달.
설치 없이 바로 실행 가능.

---

## 개발 모드 실행 (소스코드 수정 시)

터미널 2개 필요.

```bash
# 터미널 1 — Flask 백엔드
cd App/backend
pip install -r requirements.txt
python app.py
# → http://127.0.0.1:5001 에서 실행

# 터미널 2 — React + Electron
cd App/frontend
npm install
npm run electron:dev
```

---

## API 엔드포인트 요약

| 경로 | 설명 |
|------|------|
| `GET /api/search?q=...` | 자연어 검색 (doc/video/image/audio) |
| `GET /api/files/{id}` | 파일 상세 조회 |
| `POST /api/files/{id}/open` | OS로 파일 열기 |
| `POST /api/files/{id}/open-folder` | 탐색기로 폴더 열기 |
| `POST /api/index/scan` | 폴더 스캔 |
| `POST /api/index/start` | 선택 파일 임베딩 시작 |
| `GET /api/index/status/{job_id}` | 임베딩 진행 상태 |
| `GET /api/auth/status` | 비밀번호 설정 여부 |
| `POST /api/auth/setup` | 최초 비밀번호 설정 |
| `POST /api/auth/verify` | 비밀번호 검증 |
| `POST /api/auth/reset` | 비밀번호 변경 |
| `GET /api/history` | 검색 기록 조회 |
| `DELETE /api/history` | 전체 검색 기록 삭제 |

전체 스펙: `Docs/Knowledge/API.md`

---

## 페이지 구조

| 경로 | 설명 |
|------|------|
| `/` | 로그인 |
| `/setup` | 초기 마스터 비밀번호 설정 |
| `/search` | 자연어 검색 메인 |
| `/ai` | AI 모드 |
| `/settings` | 설정 (비밀번호 변경 등) |
| `/data` | 폴더 선택 및 파일 인덱싱 |
