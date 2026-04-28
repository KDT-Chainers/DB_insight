const { app, BrowserWindow, ipcMain } = require('electron')
const { spawn, spawnSync } = require('child_process')
const path = require('path')
const fs   = require('fs')

// ── 경로 상수 ─────────────────────────────────────────────────────────
const PATHS = {
  msi:         'C:\\Honey\\DB_insight\\LibreOffice_26.2.2_Win_x86-64.msi',
  installDir:  'C:\\Honey\\DB_insight\\Data\\LibreOffice\\',
  soffice:     'C:\\Honey\\DB_insight\\Data\\LibreOffice\\program\\soffice.exe',
  sofficeFallback: 'C:\\Program Files\\LibreOffice\\program\\soffice.exe',
  requirements:'C:\\Honey\\DB_insight\\App\\backend\\requirements.txt',
  mainApp:     'C:\\Honey\\DB_insight\\App\\frontend\\out\\DB_insight 0.1.0.exe',
  backendDir:  'C:\\Honey\\DB_insight\\App\\backend',
}

// ── 상태 확인 ─────────────────────────────────────────────────────────
function checkLibreOffice() {
  return fs.existsSync(PATHS.soffice) || fs.existsSync(PATHS.sofficeFallback)
}

function checkMainApp() {
  return fs.existsSync(PATHS.mainApp)
}

function findPython() {
  const candidates = [
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python311', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python310', 'python.exe'),
    path.join(process.env.USERPROFILE  || '', 'anaconda3', 'python.exe'),
    path.join(process.env.USERPROFILE  || '', 'miniconda3', 'python.exe'),
    path.join(process.env.USERPROFILE  || '', 'AppData', 'Local', 'anaconda3', 'python.exe'),
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  try {
    const r = spawnSync('python', ['--version'], { shell: true, encoding: 'utf8' })
    if (r.status === 0) return 'python'
  } catch (_) {}
  return null
}

// ── 관리자 권한 확인 ──────────────────────────────────────────────────
function isAdmin() {
  try {
    spawnSync('net', ['session'], { shell: true, stdio: 'pipe' })
    return true
  } catch { return false }
}

// ── 창 ───────────────────────────────────────────────────────────────
let win

app.whenReady().then(() => {
  win = new BrowserWindow({
    width: 520, height: 620,
    resizable: false,
    frame: false,
    center: true,
    backgroundColor: '#070d1f',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  win.loadFile(path.join(__dirname, 'index.html'))
})

app.on('window-all-closed', () => app.quit())
ipcMain.on('window-close', () => app.quit())

// ── IPC 핸들러 ────────────────────────────────────────────────────────

ipcMain.handle('check-status', () => ({
  libreoffice:  checkLibreOffice(),
  requirements: fs.existsSync(PATHS.requirements),
  mainApp:      checkMainApp(),
  python:       !!findPython(),
  msiExists:    fs.existsSync(PATHS.msi),
}))

// LibreOffice 설치
ipcMain.handle('install-libreoffice', () => {
  if (checkLibreOffice()) return { success: true, skipped: true }
  if (!fs.existsSync(PATHS.msi)) {
    return { success: false, error: 'MSI 파일 없음: ' + PATHS.msi }
  }
  try { fs.mkdirSync(PATHS.installDir, { recursive: true }) } catch (_) {}

  const installDir = PATHS.installDir.endsWith('\\') ? PATHS.installDir : PATHS.installDir + '\\'
  const msiArgs    = `/i "${PATHS.msi}" /passive /norestart INSTALLDIR="${installDir}"`

  return new Promise((resolve) => {
    // PowerShell Start-Process -Verb RunAs → UAC 팝업 후 관리자 권한으로 msiexec 실행
    const ps = `$p = Start-Process msiexec -ArgumentList '${msiArgs}' -Verb RunAs -Wait -PassThru; $p.ExitCode`
    const proc = spawn(
      'powershell',
      ['-NonInteractive', '-Command', ps],
      { shell: true, windowsHide: false }
    )
    let output = ''
    proc.stdout?.on('data', d => output += d)
    proc.on('close', () => {
      const code = parseInt(output.trim().split('\n').pop()) || 0
      resolve({ success: code === 0 || code === 3010, code })
    })
    proc.on('error', err => resolve({ success: false, error: err.message }))
  })
})

// Python 패키지 설치
ipcMain.handle('install-requirements', () => {
  const py = findPython()
  if (!py) return { success: false, error: 'Python을 찾을 수 없습니다.' }
  if (!fs.existsSync(PATHS.requirements)) {
    return { success: false, error: 'requirements.txt 없음: ' + PATHS.requirements }
  }
  return new Promise((resolve) => {
    const proc = spawn(
      py,
      ['-m', 'pip', 'install', '-r', PATHS.requirements, '--quiet'],
      { shell: true, windowsHide: true, cwd: PATHS.backendDir }
    )
    proc.on('close', (code) => resolve({ success: code === 0, code }))
    proc.on('error', (err) => resolve({ success: false, error: err.message }))
  })
})

// 바로가기 생성 (바탕화면 + 시작 메뉴)
ipcMain.handle('create-shortcut', () => {
  if (!fs.existsSync(PATHS.mainApp)) {
    return { success: false, error: '앱 실행 파일 없음: ' + PATHS.mainApp }
  }
  const desktop   = path.join(process.env.USERPROFILE || '', 'Desktop', 'DB_insight.lnk')
  const startMenu = path.join(
    process.env.APPDATA || '', 'Microsoft', 'Windows', 'Start Menu',
    'Programs', 'DB_insight.lnk'
  )
  const ps = `
    $WshShell = New-Object -ComObject WScript.Shell
    foreach ($target in @('${desktop.replace(/'/g, "''")}', '${startMenu.replace(/'/g, "''")}')) {
      $link = $WshShell.CreateShortcut($target)
      $link.TargetPath = '${PATHS.mainApp.replace(/'/g, "''")}'
      $link.WorkingDirectory = '${path.dirname(PATHS.mainApp).replace(/'/g, "''")}'
      $link.Description = 'DB_insight'
      $link.Save()
    }
  `
  try {
    spawnSync('powershell', ['-NonInteractive', '-Command', ps], { shell: true })
    return { success: true }
  } catch (e) {
    return { success: false, error: e.message }
  }
})

// 앱 실행
ipcMain.handle('launch-app', () => {
  if (!fs.existsSync(PATHS.mainApp)) return { success: false }
  try {
    spawn(PATHS.mainApp, [], { detached: true, shell: false, stdio: 'ignore' }).unref()
    setTimeout(() => app.quit(), 500)
    return { success: true }
  } catch (e) {
    return { success: false, error: e.message }
  }
})
