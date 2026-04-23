@echo off
chcp 65001 >nul
REM TRI-CHEF Admin UI launcher (Windows)
REM  1) create .venv-admin (isolated)
REM  2) install gradio + pandas + requests
REM  3) launch Gradio at http://127.0.0.1:7860
REM Prerequisite: main backend running at 127.0.0.1:5001

setlocal
cd /d "%~dp0"

if not exist ".venv-admin\Scripts\python.exe" (
    echo [admin_ui] creating .venv-admin ...
    python -m venv .venv-admin
    if errorlevel 1 (
        echo [admin_ui] venv creation failed
        exit /b 1
    )
    .venv-admin\Scripts\python.exe -m pip install --upgrade pip
    .venv-admin\Scripts\python.exe -m pip install -r requirements.txt
)

if "%TRICHEF_BACKEND%"=="" set TRICHEF_BACKEND=http://127.0.0.1:5001
echo [admin_ui] launching http://127.0.0.1:7860  (backend: %TRICHEF_BACKEND%)
.venv-admin\Scripts\python.exe gradio_app.py

endlocal
