#!/usr/bin/env bash
# TRI-CHEF Admin UI 실행 (Linux/Mac)
#  1) 별도 venv 생성 (.venv-admin) -- 기존 백엔드 venv 와 완전 분리
#  2) 의존성 설치 (gradio + pandas + requests)
#  3) Gradio 서버 구동 (http://127.0.0.1:7860)
#
# 전제: main 백엔드가 127.0.0.1:5001 에서 구동 중이어야 함.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv-admin/bin/python" ]; then
    echo "[admin_ui] .venv-admin 생성 중..."
    python3 -m venv .venv-admin
    .venv-admin/bin/python -m pip install --upgrade pip
    .venv-admin/bin/python -m pip install -r requirements.txt
fi

echo "[admin_ui] http://127.0.0.1:7860 에서 실행 (백엔드: ${TRICHEF_BACKEND:-http://127.0.0.1:5001})"
exec .venv-admin/bin/python gradio_app.py
