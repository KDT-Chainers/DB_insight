# DB_insight

로컬 파일(문서/영상/이미지/음성)을 자연어로 검색하는 AI 기반 데스크탑 앱.
**Tri-CHEF**(Complex-Hermitian Embedding Fusion) 멀티모달 검색
프레임워크의 reference 구현 저장소이다.

## 📄 Research Paper

> **Tri-CHEF: Complex-Hermitian Embedding Fusion for Korean Multimodal Retrieval**
> Young-Sang Song, Hwon Lee, Ju Yeon Jang, Young Jin Hwang, Tae Yoon Lee, Jeong Hye Gim
> *Team Chainers, Independent Researchers, Republic of Korea*, 2026
> 📃 arXiv: *(submission ID 추후 갱신)*

**핵심 기여:**
- 사전학습된 세 인코더(SigLIP2, BGE-M3, DINOv2)를 복소(complex)
  임베딩의 직교한 세 축에 배정하고, 가중합 대신 에르미트(Hermitian)형
  절대값으로 결합하여 어느 한 인코더가 점수를 독점하는 문제를 차단
- 도메인별 절대 임계값을 무작위 비매치 질의-문서 쌍에서 적합하고,
  $2{\times}/0.5{\times}$ 드리프트 가드로 증분 색인 중의 임계값 변동을 보호
- 단일 8\,GB 소비자용 GPU(RTX 4070)에서 4개 도메인(Doc/Img/Movie/Rec)
  파이프라인 동작; MIRACL-ko에서 nDCG@10 = 77.82\% (BGE-M3 dense 기준치
  대비 +7.92\,pp)

**인용 (BibTeX):**
```bibtex
@article{trichef2026,
  title   = {Tri-CHEF: Complex-Hermitian Embedding Fusion for Korean Multimodal Retrieval},
  author  = {Song, Young-Sang and Lee, Hwon and Jang, Ju Yeon and Hwang, Young Jin and Lee, Tae Yoon and Gim, Jeong Hye},
  journal = {arXiv preprint},
  year    = {2026}
}
```

`CITATION.cff` 파일을 통해 GitHub 우측 사이드바의
"Cite this repository" 버튼으로도 인용 정보를 확인할 수 있다.

## 📦 License

본 저장소의 코드, 캘리브레이션 데이터(`Data/embedded_DB/trichef_calibration.json`),
평가 스크립트는 **Apache License 2.0** 으로 공개된다 — `LICENSE` 파일 참조.

원본 in-house 코퍼스(Doc/Img/Movie/Rec raw)는 라이선스 제약으로
재배포되지 않으며, MIRACL-ko 기반 평가는 HuggingFace의
`miracl/miracl-corpus`(`ko` config)와 `miracl/miracl`(queries, `ko` config)을
참조한다.

구현 코드는 [`DI_TriCHEF/`](DI_TriCHEF/) (Doc/Img) 와
[`MR_TriCHEF/`](MR_TriCHEF/) (Movie/Rec, ~3,000 LOC) 에 있다.

---

## Architecture

본 프로젝트는 로컬 파일을 의미 기반으로 검색하기 위한 AI 시스템으로,
**실행(App) / 데이터(Data) / 지식(Docs)**을 명확히 분리한 구조를 가진다.

데이터는 다음의 3단계로 처리된다:

- **raw_DB**: (향후 확장용)
- **extracted_DB**: 텍스트/OCR/STT 등 추출된 콘텐츠 캐시
- **embedded_DB**: 임베딩 벡터 (ChromaDB) + .npy 캐시

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
│     └─ db/            ← SQLite 초기화 및 ChromaDB 인터페이스
├─ Data
│  ├─ raw_DB
│  ├─ extracted_DB      ← 텍스트 캐시 (captions, STT, chunks)
│  └─ embedded_DB       ← 벡터 캐시 (.npy) + ChromaDB
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
- Python 설치 (PATH에 등록)

---

### Step 1 — Electron 앱 빌드

```bash
cd App/frontend
npm install
rmdir /s /q out              # 이전 빌드 있을 경우
npm run dist
```

결과물: `App/frontend/out/DB_insight 0.1.0.exe`

> Flask 백엔드 별도 빌드 불필요. Electron이 실행 시 `python app.py`를 자동 실행한다.

---

### Step 2 — 앱 실행

`App/frontend/out/DB_insight 0.1.0.exe` 더블클릭

- Flask 백엔드 자동 시작 (포트 5001)
- React UI 자동 로드
- 별도 터미널 실행 불필요

---

### Step 3 — 배포

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
| `GET  /api/search?q=...` | 자연어 검색 (모든 타입 통합) |
| `POST /api/files/open` | OS로 파일 열기 |
| `POST /api/files/open-folder` | 탐색기로 폴더 열기 |
| `GET  /api/files/indexed` | 인덱싱된 파일 전체 목록 |
| `GET  /api/files/stats` | 타입별 파일/청크 수 통계 |
| `GET  /api/files/detail?path=` | 특정 파일 전체 청크 텍스트 |
| `POST /api/index/scan` | 폴더 스캔 |
| `POST /api/index/start` | 선택 파일 임베딩 시작 |
| `GET  /api/index/status/{job_id}` | 임베딩 진행 상태 |
| `POST /api/index/stop/{job_id}` | 임베딩 중단 |
| `GET  /api/auth/status` | 비밀번호 설정 여부 |
| `POST /api/auth/setup` | 최초 비밀번호 설정 |
| `POST /api/auth/verify` | 비밀번호 검증 |
| `POST /api/auth/reset` | 비밀번호 변경 |
| `GET  /api/history` | 검색 기록 조회 |
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
| `/data` | 데이터 관리 |
| `/data` → 인덱싱 탭 | 폴더 선택 및 파일 인덱싱 (임베딩 진행 모달) |
| `/data` → 데이터 소스 탭 | 인덱싱된 파일 목록 (타입별 통계 + 전체 목록) |
| `/data` → 벡터 저장소 탭 | ChromaDB 현황 (컬렉션별 파일/청크 수) |
