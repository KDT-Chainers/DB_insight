@echo off
chcp 65001 >nul
REM ─────────────────────────────────────────────────────────────────────
REM  TRI-CHEF Admin HTML 원-클릭 런처 (Windows) — 진단 강화판
REM    1) python / curl 존재 확인
REM    2) 백엔드(127.0.0.1:5001) health-check
REM    3) 미구동이면 별도 콘솔에서 `python app.py` 자동 기동
REM    4) /api/admin/domains 가 200 응답할 때까지 polling (최대 90초)
REM    5) admin.html 을 기본 브라우저로 오픈
REM
REM  실패 시 콘솔이 닫히지 않도록 모든 종료 경로에 pause.
REM ─────────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "BACKEND_URL=http://127.0.0.1:5001"
set "HEALTH_PATH=/api/admin/domains"
set "BACKEND_DIR=%~dp0..\backend"
set "ADMIN_HTML=%~dp0admin.html"
set "MAX_WAIT_SEC=90"

echo ======================================================================
echo  TRI-CHEF Admin Launcher
echo  backend dir : %BACKEND_DIR%
echo  admin html  : %ADMIN_HTML%
echo  health url  : %BACKEND_URL%%HEALTH_PATH%
echo ======================================================================

REM ── 0) python / curl 존재 확인 ──────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [admin] ERROR: 'python' not in PATH.
    echo         Python 설치 여부 및 환경변수 PATH 확인 필요.
    pause
    exit /b 10
)

set "HAS_CURL=0"
where curl >nul 2>&1
if not errorlevel 1 set "HAS_CURL=1"
if "%HAS_CURL%"=="1" (
    echo [admin] curl available.
) else (
    echo [admin] curl missing — using PowerShell fallback for health-check.
)

REM ── 1) 이미 떠 있으면 skip ──────────────────────────────────────────
echo [admin] step 1: health-check (skip startup if backend already up)
call :HEALTH_ONCE
if !HEALTH_OK!==1 (
    echo [admin] backend already running — skip startup
    goto OPEN_BROWSER
)

REM ── 2) 백엔드 자동 기동 (별도 콘솔) ─────────────────────────────────
if not exist "%BACKEND_DIR%\app.py" (
    echo [admin] ERROR: backend not found at "%BACKEND_DIR%\app.py"
    pause
    exit /b 11
)

echo [admin] step 2: starting backend in new console window...
start "TRI-CHEF backend" cmd /k "cd /d ""%BACKEND_DIR%"" && python app.py"

REM ── 3) Health-check polling ─────────────────────────────────────────
echo [admin] step 3: waiting backend to become ready (max %MAX_WAIT_SEC%s)
set /a "WAITED=0"
:WAIT_LOOP
timeout /t 3 /nobreak >nul
set /a "WAITED+=3"
call :HEALTH_ONCE
if !HEALTH_OK!==1 (
    echo [admin] backend ready after !WAITED!s
    goto OPEN_BROWSER
)
if !WAITED! GEQ %MAX_WAIT_SEC% (
    echo.
    echo [admin] ERROR: backend did not respond within %MAX_WAIT_SEC%s
    echo         새로 열린 [TRI-CHEF backend] 콘솔의 에러 메시지를 확인하세요.
    echo         (모델 로딩이 90초보다 오래 걸리는 환경이면 MAX_WAIT_SEC 상향 필요)
    pause
    exit /b 12
)
echo [admin]   ... waiting (!WAITED!s / %MAX_WAIT_SEC%s)
goto WAIT_LOOP

REM ── 4) 브라우저 오픈 ────────────────────────────────────────────────
:OPEN_BROWSER
echo [admin] step 4: opening %ADMIN_HTML%
start "" "%ADMIN_HTML%"
echo [admin] done.
timeout /t 2 /nobreak >nul
endlocal
exit /b 0

REM ── Helper: health-check 1회 → !HEALTH_OK! = 1 (OK) or 0 (fail) ─────
:HEALTH_ONCE
set "HEALTH_OK=0"
set "HTTP_CODE="
if "%HAS_CURL%"=="1" (
    for /f "delims=" %%c in ('curl -s -o nul -w "%%{http_code}" --max-time 5 "%BACKEND_URL%%HEALTH_PATH%" 2^>nul') do set "HTTP_CODE=%%c"
) else (
    for /f "delims=" %%c in ('powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri '%BACKEND_URL%%HEALTH_PATH%' -UseBasicParsing -TimeoutSec 5).StatusCode } catch { 0 }"') do set "HTTP_CODE=%%c"
)
if "!HTTP_CODE!"=="200" set "HEALTH_OK=1"
exit /b 0
