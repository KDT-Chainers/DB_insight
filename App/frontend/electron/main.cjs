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

async function startBackend() {
  if (isDev) return

  await freePort(5001)  // 이전 인스턴스가 포트를 쥐고 있으면 먼저 해제

  const backendExe = path.join(process.resourcesPath, 'backend', 'backend.exe')

  // ML 패키지(torch, transformers 등)가 필요하므로 항상 Python 소스 직접 실행
  // backend.exe 는 ML 라이브러리를 포함하지 않아 임베딩 불가
  _startPythonBackend()
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
  // app.getPath('exe') = 실행된 exe의 실제 경로 (portable 포함)
  const exeDir = path.dirname(app.getPath('exe'))
  const candidates = [
    path.join(exeDir, '..', '..', 'backend'),                     // portable: out/ → App/backend
    path.join(exeDir, '..', '..', '..', 'backend'),               // win-unpacked: out/win-unpacked/ → App/backend
    path.resolve(__dirname, '..', '..', 'backend'),                // 개발 모드 (소스에서 실행 시)
    path.join(exeDir, 'backend'),                                  // exe 옆 backend/
  ]
  const cwd = candidates.find(d => {
    try { return fs.existsSync(path.join(d, 'app.py')) } catch { return false }
  }) || candidates[1]

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
  // shell:true 로 spawn 하면 python.exe 는 cmd.exe 의 자식이므로
  // /T 플래그로 프로세스 트리 전체를 종료해야 한다.
  if (backendProcess && backendProcess.pid) {
    try {
      execSync(`taskkill /F /T /PID ${backendProcess.pid}`, { shell: true, stdio: 'pipe' })
    } catch (_) {}
    backendProcess = null
  }
  // 혹시 남아있을 경우 포트 점유 프로세스도 강제 종료 (동기)
  try {
    const out = execSync(
      'netstat -ano | findstr LISTENING | findstr :5001',
      { shell: true, stdio: 'pipe' }
    ).toString()
    out.trim().split('\n').forEach(line => {
      const parts = line.trim().split(/\s+/)
      if (parts.length >= 5 && parts[1].endsWith(':5001')) {
        try { execSync(`taskkill /F /PID ${parts[4]}`, { shell: true, stdio: 'pipe' }) } catch (_) {}
      }
    })
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// 백엔드 준비 대기 (최대 15초, 300ms 간격 폴링)
// ---------------------------------------------------------------------------

// maxRetries=300, interval=600ms → 최대 3분 대기 (ML 모델 로딩 포함)
function waitForBackend(maxRetries = 300, interval = 600) {
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

      // 진행 단계별 메시지
      let statusMsg
      if (tries <= 5)       statusMsg = `백엔드 시작 중 <span class="dots"><span>.</span><span>.</span><span>.</span></span>`
      else if (tries <= 30) statusMsg = `AI 모델 로딩 중 <span class="dots"><span>.</span><span>.</span><span>.</span></span>`
      else if (tries <= 80) statusMsg = `SigLIP2 / BGE-M3 초기화 중 <span class="dots"><span>.</span><span>.</span><span>.</span></span>`
      else                  statusMsg = `거의 다 됐습니다 <span class="dots"><span>.</span><span>.</span><span>.</span></span>`
      updateSplash(statusMsg)

      const req = http.get('http://127.0.0.1:5001/api/auth/status', (res) => {
        updateSplash('백엔드 준비 완료 ✓')
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
body{background:linear-gradient(90deg,#3d69a2 0%,#284a8f 22%,#1e3a7a 50%,#284a8f 78%,#3d69a2 100%),
  radial-gradient(ellipse 120% 100% at 50% 100%,rgba(15,30,70,.45) 0%,transparent 55%);
  color:#e8eefc;font-family:'Segoe UI',sans-serif;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  height:100vh;overflow:hidden;user-select:none;-webkit-app-region:drag}
.glow{position:fixed;width:280px;height:280px;border-radius:50%;
  background:radial-gradient(circle,rgba(100,150,220,.12) 0%,transparent 70%);
  top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:20px}
.logo-img{width:40px;height:40px;object-fit:contain;display:block;filter:drop-shadow(0 1px 2px rgba(0,0,0,.25))}
.logo-fallback{width:40px;height:40px;border-radius:8px;background:rgba(255,255,255,.12);
  display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:800;color:#e8eefc}
.name{font-size:19px;font-weight:900;letter-spacing:-.5px;color:#e8eefc}
.status{font-size:11px;color:rgba(232,238,252,.72);letter-spacing:.15em;text-transform:uppercase;margin-bottom:18px;text-align:center}
.dots span{animation:blink 1.2s infinite;color:#9ec0f0}
.dots span:nth-child(2){animation-delay:.2s}
.dots span:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,80%,100%{opacity:.2}40%{opacity:1}}
.bar-wrap{width:200px;height:3px;background:rgba(255,255,255,.12);border-radius:2px;overflow:hidden;margin-bottom:8px}
.bar{height:100%;width:40%;background:linear-gradient(90deg,#3d69a2,#7aa3e0,#3d69a2);
  animation:slide 1.4s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(350%)}}
#lo-bar{height:100%;width:0%;background:linear-gradient(90deg,#3d69a2,#9ec0f0);
  border-radius:2px;transition:width .4s ease;display:none}
#lo-detail{font-size:9px;color:rgba(232,238,252,.45);margin-top:4px;text-align:center;max-width:260px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none}
.ver{position:fixed;bottom:12px;font-size:9px;color:rgba(232,238,252,.28);letter-spacing:.1em}
</style></head><body>
<div class="glow"></div>
<div class="logo">${logoImg}<span class="name">DB_insight</span></div>
<p id="splash-status" class="status">앱 실행 중입니다 <span class="dots"><span>.</span><span>.</span><span>.</span></span></p>
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
    width: 340,
    height: 200,
    frame: false,
    resizable: false,
    center: true,
    alwaysOnTop: true,
    backgroundColor: '#1e3a7a',
    show: true,                 // 생성 즉시 표시
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  })

  splashWindow.loadFile(tmpPath)
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
