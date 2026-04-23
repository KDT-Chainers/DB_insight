@echo off
REM TRI-CHEF Admin UI 실행 (Windows)
REM  1) 별도 venv 생성 (.venv-admin) -- 기존 백엔드 venv 와 완전 분리
REM  2) 의존성 설치 (gradio + pandas + requests)
REM  3) Gradio 서버 구동 (http://127.0.0.1:7860)
REM
REM 전제: main 백엔드가 127.0.0.1:5001 에서 구동 중이어야 함.

setlocal
cd /d "%~dp0"

if not exist ".venv-admin\Scripts\python.exe" (
    echo [admin_ui] .venv-admin 생성 중...
    python -m venv .venv-admin
    if errorlevel 1 (
        echo [admin_ui] venv 생성 실패
        exit /b 1
    )
    .venv-admin\Scripts\python.exe -m pip install --upgrade pip
    .venv-admin\Scripts\python.exe -m pip install -r requirements.txt
)

echo [admin_ui] http://127.0.0.1:7860 에서 실행 (백엔드: %TRICHEF_BACKEND%)
.venv-admin\Scripts\python.exe gradio_app.py

endlocal
