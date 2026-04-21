# 배포 가이드 (Deploy Guide)

## 개요

DB_insight는 React(Vite) 프론트엔드 + Flask 백엔드를 Electron으로 감싼 데스크탑 앱이다.
Electron main 프로세스(`electron/main.cjs`)가 앱 실행 시 `python app.py`를 자동으로 띄우므로
별도 `.exe` 패키징이 필요 없다.

---

## 사전 조건

- Node.js 설치
- Python 설치 (PATH에 등록)
- `cd App/frontend && npm install` 로 node_modules 준비

---

## Step 1 — Electron 앱 빌드

```bash
cd App/frontend
npm install           # 처음 또는 의존성 변경 시
rmdir /s /q out       # 이전 빌드 있을 경우
npm run dist
```

- 결과물: `App/frontend/out/DB_insight 0.1.0.exe`
- 이 단일 파일을 팀원에게 배포
- Flask 백엔드 별도 빌드 **불필요** — Electron이 실행 시 `python app.py` 자동 실행

---

## Step 2 — 앱 실행

`App/frontend/out/DB_insight 0.1.0.exe` 더블클릭

- Flask 백엔드 자동 시작 (포트 5001)
- React UI 자동 로드
- 별도 터미널 실행 불필요

---

## 주의사항 및 시행착오

### 1. 이전 빌드 `out` 폴더 삭제 후 재빌드
이전 빌드의 `out` 폴더가 남아있으면 `app.asar` 파일 잠금 오류 발생.
재빌드 전 반드시 삭제.

```bash
rmdir /s /q out
npm run dist
```

다른 Electron 앱(Claude, Slack 등)이 해당 폴더를 잠근 경우
삭제가 안 될 수 있다. 이 경우 **PC 재시작** 후 다시 시도.

### 2. `ERR_ELECTRON_BUILDER_CANNOT_EXECUTE` 오류
electron-builder 캐시(`%LOCALAPPDATA%\electron-builder\Cache`)가 삭제된 경우
app-builder.exe가 Electron 아카이브를 찾지 못해 `UnpackElectron` 단계에서 오류 발생.

**해결**: `package.json`의 `build` 설정에 `"electronDist"` 추가 → 로컬 설치본 재사용.

```json
"build": {
  "electronDist": "node_modules/electron/dist",
  ...
}
```

### 3. winCodeSign macOS 심볼릭 링크 오류
`portable` 타겟 빌드 시 winCodeSign 아카이브에 macOS용 `.dylib` 심볼릭 링크가 포함됨.
관리자 권한 없이는 Windows에서 심볼릭 링크 생성 실패.

**해결**: `electronDist` 설정만으로도 이 문제가 함께 해결됨.
(캐시 재다운로드가 발생하지 않아 심볼릭 링크 오류 자체가 우회됨)

캐시를 수동 복구해야 할 경우:
```bash
# 7za로 심볼릭 링크 무시하고 압축 해제 후 빈 플레이스홀더 생성
7za x winCodeSign-2.6.0.7z -o"%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0" -y
echo. > "%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0\darwin\10.12\lib\libcrypto.dylib"
echo. > "%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0\darwin\10.12\lib\libssl.dylib"
```

### 4. `target`은 `portable` 사용
- `nsis`: 인스톨러 생성, 심볼릭 링크 오류 발생
- `dir`: 폴더만 생성, 단일 exe 미생성
- `portable`: 단일 exe 생성 ✅

---

## package.json 핵심 설정

```json
{
  "main": "electron/main.cjs",
  "scripts": {
    "dist": "npm run build && electron-builder"
  },
  "build": {
    "electronDist": "node_modules/electron/dist",
    "appId": "com.dbinsight.app",
    "productName": "DB_insight",
    "directories": { "output": "out" },
    "files": ["dist/**/*", "electron/main.cjs", "electron/preload.cjs"],
    "extraResources": [
      { "from": "../../", "to": "project", "filter": ["App/backend/**/*"] }
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
1. cd App/frontend
2. npm install
3. rmdir /s /q out   (이전 빌드 있을 경우)
4. npm run dist
5. out/DB_insight 0.1.0.exe 배포
```
