# 다른 PC 에서 DB_insight 실행 가이드

> **목적**: GitHub 에서 코드를 pull 받은 다른 PC 에서 검색이 정상 작동하도록 환경 구성.

---

## 📋 필요한 것

| 항목 | 출처 | 크기 |
|---|---|---|
| 1. 코드 (`git pull`) | GitHub `feature/trichef-port` 또는 `main` | ~5 MB |
| 2. 메타 JSON (`registry`, `vocab`, `token_sets`, `segments`) | git pull 에 포함 | ~50 MB |
| 3. **임베딩 캐시 (`.npy` + `chroma.sqlite3`)** | GitHub Releases zip | **~2 GB** |
| 4. **raw_DB 원본 데이터** | 팀원과 로컬 공유 | (USB / 클라우드) |

---

## 1️⃣ 코드 + 메타 JSON 받기

```powershell
git clone https://github.com/KDT-Chainers/DB_insight.git
cd DB_insight
git pull origin main
```

`Data/embedded_DB/` 의 다음 파일이 함께 받아집니다:
- `Doc/registry.json` (443 PDF 메타)
- `Img/registry.json` (2381 이미지 메타)
- `Movie/registry.json`, `Rec/registry.json`
- `Doc/auto_vocab.json`, `Doc/asf_token_sets.json` (ASF lexical)
- `Img/caption_3stage.json` (BLIP 3-stage 캡션)
- `Movie/segments.json`, `Rec/segments.json` (AV STT)
- 기타 `*_ids.json`, `vocab_*.json`

---

## 2️⃣ 임베딩 캐시 다운로드 (필수)

GitHub Releases 에서 `embedded_DB.zip` 다운로드:
```
https://github.com/KDT-Chainers/DB_insight/releases
→ 최신 release 의 embedded_DB.zip
```

압축 해제:
```powershell
# 다운로드한 zip 을 Data/embedded_DB/ 에 풀기
# 각 도메인별 .npy 파일 + ChromaDB 가 추가됨
```

해제 후 구조:
```
Data/embedded_DB/
├─ Doc/
│  ├─ cache_doc_page_Re.npy
│  ├─ cache_doc_page_Im.npy
│  ├─ cache_doc_page_Im_body.npy
│  ├─ cache_doc_page_Z.npy
│  └─ ... (메타 JSON 은 git pull 로 이미 있음)
├─ Img/
│  ├─ cache_img_Re_siglip2.npy
│  ├─ cache_img_Im_e5cap.npy
│  ├─ cache_img_Im_L1/L2/L3.npy
│  └─ cache_img_Z_dinov2.npy
├─ Movie/cache_movie_*.npy
├─ Rec/cache_music_*.npy
└─ trichef/chroma.sqlite3
```

---

## 3️⃣ raw_DB 데이터 배치

팀원에게 받은 raw_DB 폴더를 다음 위치에 두세요:

```
DB_insight/Data/raw_DB/
├─ Doc/
│  ├─ SPRI_AI브리프/...pdf
│  ├─ SPRI_SW중심사회/...pdf
│  └─ ...
├─ Img/
│  ├─ YS_1차/...jpg
│  └─ 영진_1차/...jpg
├─ Movie/
│  ├─ YS_다큐_1차/...mp4
│  └─ 훤_youtube_1차/...mp4
└─ Rec/
   ├─ YS_1차/...wav
   └─ 태윤_1차/...wav
```

---

## 4️⃣ Registry 경로 정규화 (필수)

`registry.json` 의 `abs` 필드는 이전 PC 의 절대경로 (`C:/yssong/...`) 로 저장됨.  
다른 PC 에서는 무효 → 검색 결과 클릭 시 파일 미존재.

```powershell
cd DB_insight
python scripts/normalize_registry_paths.py
```

**결과**: 모든 도메인의 `abs` 를 현재 PC 의 `Data/raw_DB/<domain>/<key>` 로 자동 갱신.

확인:
```
✓ Doc: abs 갱신 443, 디스크 미존재 0
✓ Img: abs 갱신 2381, 디스크 미존재 0
✓ Movie: abs 갱신 204, 디스크 미존재 0
✓ Rec: abs 갱신 117, 디스크 미존재 0
```

⚠️ "디스크 미존재" 가 있으면 raw_DB 데이터 배치를 다시 확인.

---

## 5️⃣ 의존성 설치

### Backend (Python)
```powershell
cd App/backend
pip install -r requirements.txt
```

### Frontend (Node.js)
```powershell
cd App/frontend
npm install
```

---

## 6️⃣ 앱 실행

### 옵션 A: Portable exe (권장)
GitHub Releases 또는 빌드 후:
```
App/frontend/out/DB_insight 0.1.0.exe
```
→ 더블클릭으로 실행.

### 옵션 B: 개발 모드
```powershell
cd App/frontend
npm run electron:dev
```

### 옵션 C: 직접 빌드
```powershell
cd App/frontend
npm run dist
# 결과: App/frontend/out/DB_insight 0.1.0.exe
```

---

## ✅ 검증

앱 실행 후:
1. 검색창에 "박태웅 의장" 입력
2. 음성 탭에 박태웅 본인 음성 다수 매칭 확인
3. 결과 클릭 시 파일 정상 열림

자동 평가:
```powershell
python scripts/test_search_quality_v2.py --direct --top-k 10 --type-filter --json md/quality_check.json
```

---

## 🔧 문제 해결

### 검색 결과 0건
- `Data/embedded_DB/<domain>/cache_*.npy` 가 있는지 확인 (Releases zip 풀었는지)
- `python scripts/verify_fusion_active.py` 로 모든 채널 활성 검증

### 결과 클릭 시 "파일 없음"
- `python scripts/normalize_registry_paths.py` 다시 실행
- raw_DB 위치 확인 (`Data/raw_DB/`)

### 정합성 검증
```powershell
python scripts/diagnose_consistency.py
```
→ 4 도메인 모두 `✓` 면 OK.

---

## 📦 임베딩 캐시 zip 생성 (관리자용)

다른 팀원과 공유할 zip 만들기:
```powershell
cd DB_insight/Data
# .npy + ChromaDB 만 압축
7z a embedded_DB_v1.0.zip "embedded_DB/*/cache_*.npy" "embedded_DB/trichef/" -xr!*.bak.*
```

또는 PowerShell:
```powershell
Compress-Archive -Path Data/embedded_DB/Doc/cache_*.npy, `
                       Data/embedded_DB/Img/cache_*.npy, `
                       Data/embedded_DB/Movie/cache_*.npy, `
                       Data/embedded_DB/Rec/cache_*.npy, `
                       Data/embedded_DB/trichef `
                 -DestinationPath embedded_DB_v1.0.zip
```

→ GitHub Releases 에 첨부 후 다른 PC 에서 다운로드.

---

## 요약

```
[PC A — 인덱싱 완료한 PC]
  1. embedded_DB 의 .npy + chroma 압축 → zip
  2. zip 을 GitHub Releases 에 첨부
  3. git push (메타 JSON 자동 포함)

[PC B — 다른 팀원 PC]
  1. git pull
  2. Releases 에서 embedded_DB.zip 다운로드 → Data/embedded_DB/ 에 풀기
  3. raw_DB 데이터 받아 Data/raw_DB/ 에 배치
  4. python scripts/normalize_registry_paths.py
  5. 앱 실행 → 검색 동일 작동 ✓
```
