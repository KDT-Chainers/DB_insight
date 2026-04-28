@echo off
chcp 65001 >nul
REM ─────────────────────────────────────────────────────────────────────
REM  TRI-CHEF Admin HTML 원-클릭 런처 (Windows)
REM    1) 백엔드(127.0.0.1:5001) health-check
REM    2) 미구동이면 별도 콘솔에서 `python app.py` 자동 기동
REM    3) /api/admin/domains 가 200 응답할 때까지 polling (최대 90초)
REM    4) admin.html 을 기본 브라우저로 오픈
REM
REM  사용:  이 파일을 더블클릭하거나, cmd에서  start_admin_html.bat
REM ─────────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "BACKEND_URL=http://127.0.0.1:5001"
set "HEALTH_PATH=/api/admin/domains"
set "BACKEND_DIR=%~dp0..\backend"
set "ADMIN_HTML=%~dp0admin.html"
set "MAX_WAIT_SEC=90"

echo [admin] backend health-check: %BACKEND_URL%%HEALTH_PATH%

REM ── 1) 이미 떠 있으면 skip ──────────────────────────────────────────
call :HEALTH_ONCE
if !ERRORLEVEL! EQU 0 (
    echo [admin] backend already running — skip startup
    goto OPEN_BROWSER
)

REM ── 2) 백엔드 자동 기동 (별도 콘솔) ─────────────────────────────────
if not exist "%BACKEND_DIR%\app.py" (
    echo [admin] ERROR: backend not found at "%BACKEND_DIR%\app.py"
    echo         repo 루트에서 실행했는지 확인하세요.
    pause
    exit /b 1
)

echo [admin] starting backend in new console...
start "TRI-CHEF backend" cmd /k "cd /d ""%BACKEND_DIR%"" && python app.py"

REM ── 3) Health-check polling ─────────────────────────────────────────
set /a "WAITED=0"
:WAIT_LOOP
timeout /t 3 /nobreak >nul
set /a "WAITED+=3"
call :HEALTH_ONCE
if !ERRORLEVEL! EQU 0 (
    echo [admin] backend ready after !WAITED!s
    goto OPEN_BROWSER
)
if !WAITED! GEQ %MAX_WAIT_SEC% (
    echo [admin] ERROR: backend did not respond within %MAX_WAIT_SEC%s
    echo         새로 열린 [TRI-CHEF backend] 콘솔의 에러 메시지를 확인하세요.
    pause
    exit /b 2
)
echo [admin] waiting for backend... (!WAITED!s / %MAX_WAIT_SEC%s)
goto WAIT_LOOP

REM ── 4) 브라우저 오픈 ────────────────────────────────────────────────
:OPEN_BROWSER
echo [admin] opening %ADMIN_HTML%
start "" "%ADMIN_HTML%"
echo [admin] done — admin UI launched.
endlocal
exit /b 0

REM ── Helper: health-check 1회 (curl → powershell fallback) ───────────
:HEALTH_ONCE
where curl >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    curl -s -o nul -w "%%{http_code}" --max-time 3 "%BACKEND_URL%%HEALTH_PATH%" 2>nul | findstr /b "200" >nul
    exit /b %ERRORLEVEL%
)
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%BACKEND_URL%%HEALTH_PATH%' -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
exit /b %ERRORLEVEL%
