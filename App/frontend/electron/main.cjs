const { app, BrowserWindow, ipcMain, dialog, protocol } = require('electron')
const path = require('path')
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
  backendProcess = spawn(backendExe, [], { stdio: 'ignore', detached: false })
  backendProcess.on('error', err => console.error('Backend failed to start:', err))
}

function killBackend() {
  if (backendProcess) {
    try { backendProcess.kill('SIGKILL') } catch (_) {}
    backendProcess = null
  }
  // 혹시 남아있을 경우 포트로 한 번 더 정리
  try { freePort(5001) } catch (_) {}
}

// ---------------------------------------------------------------------------
// 백엔드 준비 대기 (최대 15초, 300ms 간격 폴링)
// ---------------------------------------------------------------------------

function waitForBackend(maxRetries = 50, interval = 300) {
  return new Promise((resolve) => {
    if (isDev) return resolve()

    const http = require('http')
    let tries = 0

    const check = () => {
      tries++
      const req = http.get('http://127.0.0.1:5001/api/auth/status', (res) => {
        resolve()
      })
      req.on('error', () => {
        if (tries < maxRetries) setTimeout(check, interval)
        else resolve()
      })
      req.setTimeout(300, () => {
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

const SPLASH_HTML = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#070d1f;color:#dfe4fe;font-family:'Segoe UI',sans-serif;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  height:100vh;overflow:hidden;user-select:none;-webkit-app-region:drag}
.glow{position:fixed;width:280px;height:280px;border-radius:50%;
  background:radial-gradient(circle,rgba(133,173,255,.15) 0%,transparent 70%);
  top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:20px}
.icon{width:34px;height:34px;border-radius:8px;
  background:linear-gradient(135deg,#85adff,#ac8aff);
  display:flex;align-items:center;justify-content:center;font-size:16px}
.name{font-size:19px;font-weight:900;letter-spacing:-.5px;color:#85adff}
.status{font-size:11px;color:#a5aac2;letter-spacing:.15em;text-transform:uppercase;margin-bottom:18px}
.dots span{animation:blink 1.2s infinite;color:#85adff}
.dots span:nth-child(2){animation-delay:.2s}
.dots span:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,80%,100%{opacity:.2}40%{opacity:1}}
.bar-wrap{width:150px;height:2px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden}
.bar{height:100%;width:40%;background:linear-gradient(90deg,#85adff,#ac8aff);
  animation:slide 1.4s ease-in-out infinite}
@keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(350%)}}
.ver{position:fixed;bottom:12px;font-size:9px;color:rgba(165,170,194,.3);letter-spacing:.1em}
</style></head><body>
<div class="glow"></div>
<div class="logo"><div class="icon">⬡</div><span class="name">DB_insight</span></div>
<p class="status">앱 실행 중입니다 <span class="dots"><span>.</span><span>.</span><span>.</span></span></p>
<div class="bar-wrap"><div class="bar"></div></div>
<span class="ver">v0.1.0</span>
</body></html>`

function createSplash() {
  const tmpPath = path.join(os.tmpdir(), 'dbinsight_splash.html')
  try { fs.writeFileSync(tmpPath, SPLASH_HTML, 'utf8') } catch (_) {}

  splashWindow = new BrowserWindow({
    width: 340,
    height: 200,
    frame: false,
    resizable: false,
    center: true,
    alwaysOnTop: true,
    backgroundColor: '#070d1f', // HTML 로드 전 즉시 이 색으로 표시
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
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
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

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})
