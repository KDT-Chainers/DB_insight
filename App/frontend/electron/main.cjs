const { app, BrowserWindow, ipcMain, dialog, protocol } = require('electron')
const path = require('path')
const { spawn } = require('child_process')

// file:// 에서 Google Fonts 등 외부 리소스 로드 허용
protocol.registerSchemesAsPrivileged([
  { scheme: 'file', privileges: { standard: true, secure: true, corsEnabled: true } }
])

const isDev = !app.isPackaged
const DEV_URL = 'http://localhost:3000'

let backendProcess = null

// ---------------------------------------------------------------------------
// Flask 백엔드 실행
// ---------------------------------------------------------------------------

function startBackend() {
  if (isDev) return

  const backendExe = path.join(process.resourcesPath, 'backend', 'backend.exe')

  backendProcess = spawn(backendExe, [], {
    stdio: 'ignore',
    detached: false,
  })

  backendProcess.on('error', (err) => {
    console.error('Backend failed to start:', err)
  })
}

function killBackend() {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
}

// ---------------------------------------------------------------------------
// 백엔드 준비 대기 (최대 15초, 500ms 간격 폴링)
// ---------------------------------------------------------------------------

function waitForBackend(maxRetries = 30, interval = 500) {
  return new Promise((resolve) => {
    if (isDev) return resolve()  // 개발 중엔 스킵

    const http = require('http')
    let tries = 0

    const check = () => {
      tries++
      const req = http.get('http://localhost:5001/api/auth/status', (res) => {
        resolve()  // 응답 오면 준비 완료
      })
      req.on('error', () => {
        if (tries < maxRetries) setTimeout(check, interval)
        else resolve()  // 타임아웃 → 그냥 진행
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
// 윈도우 생성
// ---------------------------------------------------------------------------

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    frame: false,          // 기본 타이틀바 제거 (Windows: titleBarStyle 불필요)
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

  win.once('ready-to-show', () => win.show())
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

// 윈도우 컨트롤
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
  startBackend()
  await waitForBackend()  // 백엔드 준비될 때까지 대기
  createWindow()
})

app.on('window-all-closed', () => {
  killBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})
