# 배포 가이드 (Deploy Guide)

## 개요

DB_insight는 React(Vite) 프론트엔드 + Flask 백엔드를 Electron으로 감싼 데스크탑 앱이다.
배포 시 Flask를 `.exe`로 패키징하고, Electron이 앱 실행 시 자동으로 띄운다.

---

## 사전 조건

- Node.js 설치
- Python 설치
- **Windows 개발자 모드 활성화** (필수)
  - 설정 → 개인 정보 및 보안 → 개발자용 → 개발자 모드 ON
  - 미활성화 시 winCodeSign 심볼릭 링크 오류로 빌드 실패

---

## Step 1 — Flask 백엔드 `.exe` 패키징

```bash
cd App/backend
pip install pyinstaller
pyinstaller app.py --onefile --name backend
```

- 결과물: `App/backend/dist/backend.exe`
- 이 파일이 `App/frontend/package.json`의 `extraResources`에서 참조됨

---

## Step 2 — React + Electron 빌드

```bash
cd App/frontend
npm install
set CSC_IDENTITY_AUTO_DISCOVERY=false && npm run dist
```

- 결과물: `App/frontend/out/DB_insight 0.1.0.exe`
- 이 단일 파일을 팀원에게 배포

---

## 주의사항 및 시행착오

### 1. Windows 개발자 모드 필수
winCodeSign이 macOS용 심볼릭 링크를 생성할 때 권한 오류 발생.
개발자 모드를 켜야 해결된다.

```
ERROR: Cannot create symbolic link : 클라이언트에 필요한 권한을 보유하고 있지 않습니다.
→ 해결: Windows 개발자 모드 활성화 후 cmd 재시작
```

### 2. CSC_IDENTITY_AUTO_DISCOVERY=false 필수
코드 서명 인증서 없이 빌드하려면 반드시 설정해야 한다.
`npm run dist` 단독 실행 시 signing 오류 발생.

```bash
# 반드시 이렇게 실행
set CSC_IDENTITY_AUTO_DISCOVERY=false && npm run dist
```

### 3. 이전 빌드 out 폴더 삭제 후 재빌드
이전 빌드의 `out` 폴더가 남아있으면 `app.asar` 파일 잠금 오류 발생.
재빌드 전 반드시 삭제.

```bash
rmdir /s /q out
set CSC_IDENTITY_AUTO_DISCOVERY=false && npm run dist
```

단, 다른 Electron 앱(Claude, Slack 등)이 해당 폴더를 잠근 경우
삭제가 안 될 수 있다. 이 경우 **PC 재시작** 후 다시 시도.

### 4. target은 portable 사용
- `nsis`: 인스톨러 생성, winCodeSign 심볼릭 링크 오류 발생
- `dir`: 폴더만 생성, 단일 exe 미생성
- `portable`: 단일 exe 생성, 개발자 모드 활성화 시 정상 동작 ✅

---

## package.json 핵심 설정

```json
{
  "main": "electron/main.cjs",
  "scripts": {
    "dist": "npm run build && electron-builder"
  },
  "build": {
    "appId": "com.dbinsight.app",
    "productName": "DB_insight",
    "directories": { "output": "out" },
    "files": ["dist/**/*", "electron/main.cjs", "electron/preload.cjs"],
    "extraResources": [
      { "from": "../backend/dist/backend.exe", "to": "backend/backend.exe" }
    ],
    "win": {
      "target": "portable",
      "signingHashAlgorithms": null,
      "sign": null
    }
  }
}
```

---

## 전체 순서 요약

```
1. Windows 개발자 모드 ON
2. cd App/backend → pyinstaller app.py --onefile --name backend
3. cd App/frontend → npm install
4. rmdir /s /q out  (이전 빌드 있을 경우)
5. set CSC_IDENTITY_AUTO_DISCOVERY=false && npm run dist
6. out/DB_insight 0.1.0.exe 배포
```
