@echo off
REM ======================================================================
REM  TRI-CHEF Admin HTML one-click launcher (Windows)
REM    1) Verify python / curl on PATH
REM    2) Health-check backend at 127.0.0.1:5001
REM    3) If down, start `python app.py` in new console
REM    4) Poll /api/admin/domains until 200 OK (max 90s)
REM    5) Open admin.html in default browser
REM
REM  NOTE: ASCII-only on purpose. cmd.exe parses .bat as CP949 by default;
REM        any UTF-8 multi-byte char (Korean / box-drawing) will desync the
REM        line stream and make subsequent commands unrecognized.
REM ======================================================================

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

REM --- 0) python / curl presence ----------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [admin] ERROR: 'python' not on PATH.
    echo         Install Python and add it to PATH, or activate the venv first.
    pause
    exit /b 10
)

set "HAS_CURL=0"
where curl >nul 2>&1
if not errorlevel 1 set "HAS_CURL=1"
if "%HAS_CURL%"=="1" (
    echo [admin] curl available.
) else (
    echo [admin] curl missing - using PowerShell fallback for health-check.
)

REM --- 1) Skip startup if backend already running -----------------------
echo [admin] step 1: health-check
call :HEALTH_ONCE
if !HEALTH_OK!==1 (
    echo [admin] backend already running - skip startup
    goto OPEN_BROWSER
)

REM --- 2) Auto-start backend in a separate console window ---------------
if not exist "%BACKEND_DIR%\app.py" (
    echo [admin] ERROR: backend not found at "%BACKEND_DIR%\app.py"
    pause
    exit /b 11
)

echo [admin] step 2: starting backend in new console window...
start "TRI-CHEF backend" cmd /k "cd /d ""%BACKEND_DIR%"" && python app.py"

REM --- 3) Poll backend until ready --------------------------------------
echo [admin] step 3: waiting for backend (max %MAX_WAIT_SEC%s)
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
    echo         Check the [TRI-CHEF backend] console for errors.
    echo         (If model loading takes longer, raise MAX_WAIT_SEC.)
    pause
    exit /b 12
)
echo [admin]   ... waiting (!WAITED!s / %MAX_WAIT_SEC%s)
goto WAIT_LOOP

REM --- 4) Open browser --------------------------------------------------
:OPEN_BROWSER
echo [admin] step 4: opening %ADMIN_HTML%
start "" "%ADMIN_HTML%"
echo [admin] done.
timeout /t 2 /nobreak >nul
endlocal
exit /b 0

REM --- Helper: one health probe -> !HEALTH_OK! = 1 (OK) or 0 (fail) -----
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
