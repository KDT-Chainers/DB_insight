#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
#  TRI-CHEF Admin HTML 원-클릭 런처 (Linux / macOS)
#    1) 백엔드(127.0.0.1:5001) health-check
#    2) 미구동이면 백그라운드로 `python app.py` 자동 기동
#    3) /api/admin/domains 가 200 응답할 때까지 polling (최대 90초)
#    4) admin.html 을 기본 브라우저로 오픈
#
#  사용:  ./start_admin_html.sh
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_URL="http://127.0.0.1:5001"
HEALTH_PATH="/api/admin/domains"
BACKEND_DIR="${SCRIPT_DIR}/../backend"
ADMIN_HTML="${SCRIPT_DIR}/admin.html"
MAX_WAIT_SEC=90
LOG_FILE="${SCRIPT_DIR}/.backend.log"

health_once() {
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 \
                 "${BACKEND_URL}${HEALTH_PATH}" 2>/dev/null || echo "000")
    [ "$code" = "200" ]
}

open_browser() {
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$ADMIN_HTML" >/dev/null 2>&1 &
    elif command -v open >/dev/null 2>&1; then
        open "$ADMIN_HTML"
    else
        echo "[admin] could not auto-open browser. Open manually: $ADMIN_HTML"
    fi
}

echo "[admin] backend health-check: ${BACKEND_URL}${HEALTH_PATH}"

if health_once; then
    echo "[admin] backend already running — skip startup"
    open_browser
    exit 0
fi

if [ ! -f "${BACKEND_DIR}/app.py" ]; then
    echo "[admin] ERROR: backend not found at ${BACKEND_DIR}/app.py"
    exit 1
fi

echo "[admin] starting backend (logs: ${LOG_FILE})"
( cd "$BACKEND_DIR" && nohup python app.py > "$LOG_FILE" 2>&1 & )

waited=0
while [ "$waited" -lt "$MAX_WAIT_SEC" ]; do
    sleep 3
    waited=$((waited + 3))
    if health_once; then
        echo "[admin] backend ready after ${waited}s"
        open_browser
        echo "[admin] done — admin UI launched."
        exit 0
    fi
    echo "[admin] waiting for backend... (${waited}s / ${MAX_WAIT_SEC}s)"
done

echo "[admin] ERROR: backend did not respond within ${MAX_WAIT_SEC}s"
echo "        check log: ${LOG_FILE}"
exit 2
