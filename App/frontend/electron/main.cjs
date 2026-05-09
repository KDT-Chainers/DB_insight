const { app, BrowserWindow, ipcMain, dialog, protocol } = require('electron')
const path = require('path')
const { pathToFileURL } = require('url')
const { spawn, execSync } = require('child_process')
const os = require('os')
const fs = require('fs')

// 불필요한 백그라운드 체크 비활성화 → 시작 속도 약간 개선
app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion')
app.commandLine.appendSwitch('disable-background-timer-throttling')
app.commandLine.appendSwitch('disable-renderer-backgrounding')

// file:// 에서 외부 리소스 로드 허용
protocol.registerSchemesAsPrivileged([
  { scheme: 'file', privileges: { standard: true, secure: true, corsEnabled: true } }
])

const isDev = !app.isPackaged
const DEV_URL = 'http://localhost:3000'

let backendProcess = null
let splashWindow = null

// ---------------------------------------------------------------------------
// 포트 5001 을 점유한 프로세스 강제 종료 (재시작 시 포트 충돌 방지)
// ---------------------------------------------------------------------------

function freePort(port) {
  try {
    const out = execSync(
      `netstat -ano | findstr LISTENING | findstr :${port}`,
      { shell: true, stdio: 'pipe' }
    ).toString()
    const pids = new Set()
    out.trim().split('\n').forEach(line => {
      const parts = line.trim().split(/\s+/)
      // 로컬 주소가 :5001 로 끝나는 행의 PID
      if (parts.length >= 5 && parts[1].endsWith(`:${port}`)) pids.add(parts[4])
    })
    pids.forEach(pid => {
      try { execSync(`taskkill /F /PID ${pid}`, { shell: true, stdio: 'pipe' }) } catch (_) {}
    })
    if (pids.size > 0) return new Promise(r => setTimeout(r, 400)) // 포트 해제 대기
  } catch (_) {}
  return Promise.resolve()
}

// ---------------------------------------------------------------------------
// Flask 백엔드 실행
// ---------------------------------------------------------------------------

// 5001 포트가 이미 살아있는 백엔드(외부 detached 또는 이전 세션) 인지 확인.
// 정상 응답 시 freePort + spawn python 스킵 → 부팅 30~60s 단축.
//
// [v9 자동복구] timeout 5s + retry 2회. 백엔드가 Ollama 추론 / 인덱싱 등
//   잠시 busy 한 경우(GIL 점유) 1.5s 로는 false 판정 → 멀쩡한 백엔드 죽이고
//   30~60s 재시작하는 부작용. 5s 로 충분히 대기 + 1회 재시도하여 진짜 죽은
//   경우만 spawn 트리거.
function _checkBackendAlive(port = 5001) {
  const http = require('http')
  const tryOnce = () => new Promise((resolve) => {
    // [v9] /api/health (초경량) 사용 — 인덱싱/Qwen 추론으로 busy 한 백엔드도
    //   Flask 라우터만 거치므로 즉시 응답. /api/search 는 ChromaDB+reranker
    //   걸쳐 busy 시 5s 도 timeout → 멀쩡한 백엔드 죽이는 부작용.
    const req = http.request({
      host: '127.0.0.1', port, path: '/api/health',
      method: 'GET', timeout: 3000,
    }, (res) => {
      resolve(res.statusCode >= 200 && res.statusCode < 500)
      res.resume()
    })
    req.on('error', () => resolve(false))
    req.on('timeout', () => { req.destroy(); resolve(false) })
    req.end()
  })
  return new Promise(async (resolve) => {
    if (await tryOnce()) return resolve(true)
    // busy 가능성 — 1초 후 1회 재시도
    await new Promise((r) => setTimeout(r, 1000))
    resolve(await tryOnce())
  })
}

async function startBackend() {
  if (isDev) return

  // [v11 하이브리드] 백엔드 재사용 + 코드 변경 자동 감지.
  //   v9 : 살아있으면 무조건 재사용 → stale .py 코드 부작용
  //   v10: 매번 강제 종료 → 매 실행 30~60s 모델 로딩 부담
  //   v11: 살아있고 + 코드 unchanged 면 재사용, 코드 변경됐으면 kill+respawn.
  //        marker file (flask_started.marker) mtime 과 backend/*.py mtime 비교.
  if (await _checkBackendAlive(5001)) {
    if (_isBackendCodeNewer()) {
      console.log('[startBackend] 백엔드 코드 변경 감지 → 재시작 (30~60s)')
      await freePort(5001)
      _startPythonBackend()
    } else {
      console.log('[startBackend] port 5001 응답 OK + 코드 unchanged → 재사용 (즉시)')
    }
    return
  }

  await freePort(5001)  // 응답 없는 stale 점유자만 해제
  _startPythonBackend()
}

// 백엔드 디렉터리(app.py 가 있는 곳) 검색 — _startPythonBackend 와 동일 로직
function _findBackendDir() {
  const exeDir = path.dirname(app.getPath('exe'))
  // PORTABLE_EXECUTABLE_DIR: 포터블 exe 실행 시 electron-builder 가 설정하는
  // 환경변수. exe 압축 해제 위치(임시폴더)가 아닌 실제 .exe 파일이 있는 폴더를 가리킴.
  const portableDir = process.env.PORTABLE_EXECUTABLE_DIR || ''
  const candidates = [
    // 포터블 exe 우선: PORTABLE_EXECUTABLE_DIR 기준 상대경로
    portableDir && path.join(portableDir, '..', '..', 'backend'),   // out/ → App/backend
    portableDir && path.join(portableDir, 'backend'),                // exe 옆 backend/
    // 일반(non-portable) exe: app.getPath('exe') 기준
    path.join(exeDir, '..', '..', 'backend'),
    path.join(exeDir, '..', '..', '..', 'backend'),
    path.resolve(__dirname, '..', '..', 'backend'),
    path.join(exeDir, 'backend'),
  ].filter(Boolean)
  return candidates.find(d => {
    try { return fs.existsSync(path.join(d, 'app.py')) } catch { return false }
  })
}

// marker 파일 경로 — Flask spawn 시각 기록.
const FLASK_MARKER_FILE = () => path.join(app.getPath('userData'), 'flask_started.marker')

// backend/*.py 가 marker 보다 최근에 수정됐는지 검사.
// marker 없으면 unknown → true (안전하게 재시작).
function _isBackendCodeNewer() {
  try {
    const marker = FLASK_MARKER_FILE()
    if (!fs.existsSync(marker)) return true
    const markerMs = fs.statSync(marker).mtimeMs

    const backendDir = _findBackendDir()
    if (!backendDir) return false  // backend 못 찾으면 살아있는 것 그대로 사용

    // 감시 대상: app.py / config.py / routes/ / services/ / embedders/
    const watchTargets = [
      path.join(backendDir, 'app.py'),
      path.join(backendDir, 'config.py'),
      path.join(backendDir, 'routes'),
      path.join(backendDir, 'services'),
      path.join(backendDir, 'embedders'),
    ]
    for (const target of watchTargets) {
      if (!fs.existsSync(target)) continue
      const stat = fs.statSync(target)
      if (stat.isFile() && target.endsWith('.py')) {
        if (stat.mtimeMs > markerMs) return true
      } else if (stat.isDirectory()) {
        if (_dirHasNewerPy(target, markerMs)) return true
      }
    }
    return false
  } catch (_) {
    return true  // 검사 실패 시 안전하게 재시작
  }
}

// 디렉터리 재귀 순회 — .py mtime > markerMs 인 파일이 있으면 true 반환 (early exit).
function _dirHasNewerPy(dir, markerMs) {
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
    for (const e of entries) {
      // __pycache__ / 숨김 디렉터리 스킵
      if (e.name.startsWith('.') || e.name === '__pycache__') continue
      const fp = path.join(dir, e.name)
      if (e.isDirectory()) {
        if (_dirHasNewerPy(fp, markerMs)) return true
      } else if (e.isFile() && e.name.endsWith('.py')) {
        try {
          if (fs.statSync(fp).mtimeMs > markerMs) return true
        } catch (_) {}
      }
    }
  } catch (_) {}
  return false
}

function _startPythonBackend() {
  // 로그: app.getPath('userData') — 항상 쓰기 가능 (C:\Users\...\AppData\Roaming\DB_insight)
  const logDir  = app.getPath('userData')
  const logPath = path.join(logDir, 'backend.log')
  let logStream
  try {
    fs.mkdirSync(logDir, { recursive: true })
    logStream = fs.openSync(logPath, 'w')
  } catch (_) { logStream = 'ignore' }

  // 백엔드 소스 경로 후보
  // PORTABLE_EXECUTABLE_DIR: 포터블 exe 실행 시 실제 .exe 위치 (임시폴더 X)
  const exeDir = path.dirname(app.getPath('exe'))
  const portableDir = process.env.PORTABLE_EXECUTABLE_DIR || ''
  const candidates = [
    portableDir && path.join(portableDir, '..', '..', 'backend'),  // portable: out/ → App/backend
    portableDir && path.join(portableDir, 'backend'),               // exe 옆 backend/
    path.join(exeDir, '..', '..', 'backend'),                      // non-portable: out/ → App/backend
    path.join(exeDir, '..', '..', '..', 'backend'),                // win-unpacked: out/win-unpacked/ → App/backend
    path.resolve(__dirname, '..', '..', 'backend'),                 // 개발 모드 (소스에서 실행 시)
    path.join(exeDir, 'backend'),                                   // exe 옆 backend/
  ].filter(Boolean)
  const cwd = candidates.find(d => {
    try { return fs.existsSync(path.join(d, 'app.py')) } catch { return false }
  }) || candidates[2]

  // Python 실행 파일 후보 (절대경로 우선 → PATH fallback)
  const pythonCandidates = [
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python311', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python310', 'python.exe'),
    path.join(process.env.USERPROFILE  || '', 'anaconda3', 'python.exe'),
    path.join(process.env.USERPROFILE  || '', 'miniconda3', 'python.exe'),
    path.join(process.env.USERPROFILE  || '', 'AppData', 'Local', 'anaconda3', 'python.exe'),
    'python',
    'python3',
    'py',
  ]

  // 로그 헤더
  const header = `[DB_insight backend log] ${new Date().toISOString()}\ncwd: ${cwd}\nlogPath: ${logPath}\n\n`
  try { if (typeof logStream === 'number') fs.writeSync(logStream, header) } catch (_) {}

  let started = false
  for (const py of pythonCandidates) {
    // 절대경로인 경우 파일 존재 여부 먼저 확인
    if (path.isAbsolute(py) && !fs.existsSync(py)) continue
    try {
      backendProcess = spawn(py, ['app.py'], {
        cwd,
        stdio: ['ignore', logStream, logStream],
        detached: false,
        shell: true,              // PATH 기반 해석을 위해 shell 사용
        windowsHide: true,        // CMD 창 숨김
        env: {
          ...process.env,
          // Cross-encoder rerank 활성화 — services/rerank_adapter.py:28 가
          // 이 변수를 truthy 로 판정하면 GPU bf16 으로 BGE-reranker-v2-m3 를
          // lazy 로딩하여 /api/search 결과를 재정렬한다. 첫 호출 ~1s 추가.
          TRICHEF_USE_RERANKER: '1',
          // [Electron P1] __pycache__ 디스크 쓰기 방지 → I/O 경쟁 감소.
          PYTHONDONTWRITEBYTECODE: '1',
          // 진행률·에러 로그 즉시 flush → 디버깅 가시성 ↑ (헤드리스 spawn 환경 필수).
          PYTHONUNBUFFERED:        '1',
        },
      })
      backendProcess.on('error', (err) => {
        try { if (typeof logStream === 'number') fs.writeSync(logStream, `\n[spawn error] ${err.message}\n`) } catch (_) {}
      })
      started = true
      // [v11] Flask spawn 시각을 marker 파일에 기록 → 다음 실행 시 코드 변경 감지에 사용.
      try {
        const marker = FLASK_MARKER_FILE()
        fs.mkdirSync(path.dirname(marker), { recursive: true })
        fs.writeFileSync(marker, new Date().toISOString())
      } catch (_) {}
      console.log(`Backend started via: ${py} app.py (cwd: ${cwd}) log: ${logPath}`)
      break
    } catch (_) {}
  }
  if (!started) {
    const msg = `Python backend could not be started. Checked:\n${pythonCandidates.join('\n')}`
    console.error(msg)
    try { if (typeof logStream === 'number') fs.writeSync(logStream, msg) } catch (_) {}
  }
}

function killBackend() {
  // [v11 하이브리드] 앱 종료 시 자기 자식 백엔드만 종료. 외부 detached 백엔드는 보존.
  //   다음 실행 시 startBackend() 가 코드 변경 여부를 확인하여
  //   - unchanged: 살아있는 백엔드 재사용 (즉시 시작)
  //   - changed:   freePort + 새 spawn (30~60s)
  //
  //   v9 동작 복귀 + startBackend 의 _isBackendCodeNewer 로 stale 코드 문제 해결.
  if (backendProcess && backendProcess.pid) {
    try {
      execSync(`taskkill /F /T /PID ${backendProcess.pid}`, { shell: true, stdio: 'pipe' })
    } catch (_) {}
    backendProcess = null
  }
}

// ---------------------------------------------------------------------------
// 백엔드 준비 대기 (최대 15초, 300ms 간격 폴링)
// ---------------------------------------------------------------------------

// [startup-speedup] interval 600ms → 250ms (Flask listener 가 /api/health 에 ~2초
// 만에 응답하므로 빠르게 폴링하면 splash 통과 시간 단축).
// maxRetries=600, interval=250ms → 최대 2.5분 대기 (워밍업 포함 안전 버퍼).
function waitForBackend(maxRetries = 600, interval = 250) {
  return new Promise((resolve) => {
    if (isDev) return resolve()

    const http = require('http')
    let tries = 0

    // 스플래시 창에 상태 텍스트 전달
    const updateSplash = (msg) => {
      try {
        if (splashWindow && !splashWindow.isDestroyed()) {
          splashWindow.webContents.executeJavaScript(
            `(function(){
               var s = document.getElementById('splash-status');
               if (s) s.innerHTML = ${JSON.stringify(msg)};
             })()`
          ).catch(() => {})
        }
      } catch (_) {}
    }

    const check = () => {
      tries++

      updateSplash('Loading <span class="dots"><span>.</span><span>.</span><span>.</span></span>')

      // [startup-speedup] /api/auth/status → /api/health (초경량, 백엔드 listener
      // 시작 즉시 응답). 22초→2초 단축. 모델 워밍업은 background thread 가 진행하며
      // SplashOrb 가 /api/warmup-status 를 polling 하여 진행률 표시.
      const req = http.get('http://127.0.0.1:5001/api/health', (res) => {
        updateSplash('Loading <span class="dots"><span>.</span><span>.</span><span>.</span></span>')
        resolve()
      })
      req.on('error', () => {
        if (tries < maxRetries) setTimeout(check, interval)
        else resolve()
      })
      req.setTimeout(400, () => {
        req.destroy()
        if (tries < maxRetries) setTimeout(check, interval)
        else resolve()
      })
    }

    check()
  })
}

// ---------------------------------------------------------------------------
// 스플래시 창
// ---------------------------------------------------------------------------

/** 배포(dist) 또는 개발(public)에서 teamlogo.png 경로 */
function resolveSplashLogoPath() {
  const candidates = [
    path.join(__dirname, '..', 'dist', 'teamlogo.png'),
    path.join(__dirname, '..', 'public', 'teamlogo.png'),
    path.join(__dirname, '..', 'src', 'assets', 'teamlogo.png'),
  ]
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) return p
    } catch (_) {}
  }
  return null
}

function buildSplashHtml(logoFileUrl) {
  const logoImg = logoFileUrl
    ? `<img class="logo-img" src="${logoFileUrl}" alt="" width="40" height="40" />`
    : `<div class="logo-fallback" aria-hidden="true">DB</div>`
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  background:
    radial-gradient(ellipse 148% 120% at -12% -16%, rgba(22,62,198,.42) 0%, rgba(22,62,198,.16) 46%, transparent 84%),
    radial-gradient(ellipse 134% 114% at 114% 118%, rgba(56,40,124,.36) 0%, rgba(56,40,124,.12) 48%, transparent 86%),
    radial-gradient(ellipse 130% 95% at 50% 118%, rgba(0,0,0,.88) 0%, transparent 56%),
    linear-gradient(165deg,#0a0a0c 0%,#050507 42%,#030304 100%);
  color:#e8eefc;font-family:'Segoe UI',sans-serif;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  height:100vh;overflow:hidden;user-select:none;-webkit-app-region:drag
}
.orb-wrap{
  position:relative;width:172px;height:172px;margin-bottom:18px;
  animation:floatY 3.6s ease-in-out infinite;
  filter:drop-shadow(0 16px 46px rgba(139,92,246,.34))
}
.orb{
  position:absolute;inset:0;border-radius:50%;
  background:
    radial-gradient(circle at 34% 26%, rgba(242,232,255,.82) 0%, rgba(206,175,255,.46) 22%, rgba(139,92,246,.34) 46%, rgba(58,30,98,.62) 70%, rgba(16,10,32,.78) 100%),
    conic-gradient(from 0deg, rgba(167,139,250,.52), rgba(124,58,237,.12), rgba(236,72,153,.26), rgba(99,102,241,.24), rgba(167,139,250,.52));
  border:1px solid rgba(255,255,255,.22);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.34), inset 0 -1px 0 rgba(255,255,255,.08), 0 0 58px rgba(139,92,246,.28);
  animation:orbSpin 8.8s linear infinite;
}
.orb-particles{
  position:absolute;inset:9%;border-radius:50%;pointer-events:none;
  background:
    radial-gradient(circle, rgba(255,255,255,.55) 0 1px, transparent 1.6px);
  background-size:12px 12px;
  mix-blend-mode:screen;
  opacity:.38;
  animation:orbSpin 11.6s linear infinite reverse;
}
.orb::before{
  content:'';position:absolute;inset:-12px;border-radius:50%;
  border:1px solid rgba(167,139,250,.32);
  box-shadow:0 0 30px rgba(139,92,246,.22), inset 0 1px 0 rgba(255,255,255,.18);
  animation:orbSpin 16s linear infinite;
}
.orb::after{
  content:'';position:absolute;left:20%;top:14%;width:44%;height:28%;
  border-radius:50%;
  background:radial-gradient(ellipse at center, rgba(255,255,255,.86) 0%, rgba(255,255,255,.32) 48%, rgba(255,255,255,0) 100%);
  transform:rotate(-12deg)
}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.logo-img{width:34px;height:34px;object-fit:contain;display:block;filter:drop-shadow(0 1px 2px rgba(0,0,0,.25))}
.logo-fallback{width:34px;height:34px;border-radius:8px;background:rgba(255,255,255,.12);
  display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;color:#e8eefc}
.name{font-size:27px;font-weight:900;letter-spacing:-.5px;color:#f2f6ff}
.status{font-size:14px;color:rgba(232,238,252,.86);letter-spacing:.05em;margin-bottom:16px;text-align:center;font-weight:600}
.dots span{animation:blink 1.2s infinite;color:#9ec0f0}
.dots span:nth-child(2){animation-delay:.2s}
.dots span:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,80%,100%{opacity:.2}40%{opacity:1}}
.bar-wrap{width:320px;height:4px;background:rgba(255,255,255,.14);border-radius:8px;overflow:hidden;margin-bottom:8px}
.bar{height:100%;width:40%;background:linear-gradient(90deg,#020510,#07112a,#020510);
  animation:slide 1.4s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(350%)}}
#lo-bar{height:100%;width:0%;background:linear-gradient(90deg,#3d69a2,#9ec0f0);
  border-radius:2px;transition:width .4s ease;display:none}
#lo-detail{font-size:10px;color:rgba(232,238,252,.55);margin-top:4px;text-align:center;max-width:260px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none}
.ver{position:fixed;bottom:14px;font-size:10px;color:rgba(232,238,252,.34);letter-spacing:.1em}
@keyframes orbSpin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
@keyframes floatY{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
</style></head><body>
<div class="orb-wrap"><div class="orb"></div><div class="orb-particles"></div></div>
<div class="logo">${logoImg}<span class="name">DB insight</span></div>
<p id="splash-status" class="status">Loading <span class="dots"><span>.</span><span>.</span><span>.</span></span></p>
<div class="bar-wrap">
  <div class="bar" id="boot-bar"></div>
  <div id="lo-bar"></div>
</div>
<p id="lo-detail"></p>
<span class="ver">v0.1.0</span>
</body></html>`
}

function createSplash() {
  const logoPath = resolveSplashLogoPath()
  const logoHref = logoPath ? pathToFileURL(logoPath).href : ''
  const html = buildSplashHtml(logoHref)

  const tmpPath = path.join(os.tmpdir(), 'dbinsight_splash.html')
  try { fs.writeFileSync(tmpPath, html, 'utf8') } catch (_) {}

  splashWindow = new BrowserWindow({
    width: 500,
    height: 330,
    frame: false,
    resizable: false,
    center: true,
    alwaysOnTop: true,
    backgroundColor: '#050507',
    show: true,                 // 생성 즉시 표시
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  })

  // 스플래시도 React 라우트(/splash)를 사용해 메인 UI의 실제 Orb 컴포넌트를 재사용한다.
  if (isDev) {
    splashWindow
      .loadURL(`${DEV_URL}#/splash`)
      .catch(() => splashWindow && splashWindow.loadFile(tmpPath))
  } else {
    splashWindow
      .loadFile(path.join(__dirname, '..', 'dist', 'index.html'), { hash: '/splash' })
      .catch(() => splashWindow && splashWindow.loadFile(tmpPath))
  }
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close()
    splashWindow = null
  }
}

// ---------------------------------------------------------------------------
// 메인 윈도우 생성
// ---------------------------------------------------------------------------

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    backgroundColor: '#020510', /* index.css --app-bg-top 과 동일 */
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      // [Electron P1] 인덱싱 중 백그라운드 탭/창 throttle 비활성 → 진행률 즉시 갱신.
      backgroundThrottling: false,
      // 검색·인덱싱 UI 에는 맞춤법 검사 불필요 (한국어 dict 로딩 + IPC 부담 제거).
      spellcheck: false,
    },
    show: false,
  })

  if (isDev) {
    win.loadURL(DEV_URL)
  } else {
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }

  win.once('ready-to-show', () => {
    closeSplash()
    win.show()
  })
}

// ---------------------------------------------------------------------------
// IPC
// ---------------------------------------------------------------------------

ipcMain.handle('select-folder', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    properties: ['openDirectory'],
    title: '인덱싱할 폴더 선택',
  })
  if (canceled || filePaths.length === 0) return null
  return filePaths[0]
})

// LibreOffice MSI 설치 — Electron(GUI 프로세스)에서 직접 실행해야 UAC 팝업이 정상 작동
ipcMain.handle('install-libreoffice', async () => {
  const msiPath    = 'C:\\Program Files\\DB_insight\\LibreOffice_26.2.2_Win_x86-64.msi'
  const installDir = 'C:\\Program Files\\DB_insight\\Data\\LibreOffice\\'

  // MSI 파일 존재 확인
  if (!fs.existsSync(msiPath)) {
    return { success: false, error: 'MSI 파일을 찾을 수 없습니다: ' + msiPath }
  }

  return new Promise((resolve) => {
    // /passive : UAC 팝업 + 진행 창 표시, 사용자 입력 불필요
    const proc = spawn(
      'msiexec',
      ['/i', msiPath, '/passive', '/norestart', `INSTALLDIR=${installDir}`],
      { shell: true, windowsHide: false }
    )
    proc.on('close', (code) => {
      resolve({ success: code === 0 || code === 3010, code })
    })
    proc.on('error', (err) => {
      resolve({ success: false, error: err.message })
    })
  })
})

ipcMain.on('window-minimize', () => BrowserWindow.getFocusedWindow()?.minimize())
ipcMain.on('window-maximize', () => {
  const win = BrowserWindow.getFocusedWindow()
  if (!win) return
  win.isMaximized() ? win.unmaximize() : win.maximize()
})
ipcMain.on('window-close', () => BrowserWindow.getFocusedWindow()?.close())

// ---------------------------------------------------------------------------
// 앱 생명주기
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  // ── 진단 로그 (userData/startup.log — 항상 쓰기 가능) ──
  try {
    const diagDir  = app.getPath('userData')
    const diagPath = path.join(diagDir, 'startup.log')
    fs.mkdirSync(diagDir, { recursive: true })
    fs.writeFileSync(diagPath,
      `isPackaged=${app.isPackaged} isDev=${isDev}\n` +
      `exe=${app.getPath('exe')}\n` +
      `exeDir=${path.dirname(app.getPath('exe'))}\n` +
      `userData=${app.getPath('userData')}\n` +
      `__dirname=${__dirname}\n` +
      `resourcesPath=${process.resourcesPath}\n` +
      `argv=${process.argv.join(' ')}\n` +
      `time=${new Date().toISOString()}\n`, 'utf8')
  } catch (_) {}
  // ──────────────────────────────────────────────────────────

  createSplash()          // app.whenReady() 직후 즉시 표시
  await startBackend()    // 포트 정리 후 백엔드 시작 (await로 포트 해제 대기)
  await Promise.all([
    waitForBackend(),                                  // 백엔드 응답 대기
    new Promise(r => setTimeout(r, 1500)),             // 최소 1.5초 스플래시 유지
  ])
  createWindow()
})

app.on('window-all-closed', () => {
  killBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  killBackend()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})
