"""routes/setup_deps.py — 초기 설치 의존성 관리 (LibreOffice 등).

GET  /api/setup/check          → 의존성 설치 여부 확인
POST /api/setup/install-lo     → LibreOffice 자동 설치 시작 (백그라운드)
GET  /api/setup/install-status → 설치 진행 상태 폴링
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import urllib.request
from pathlib import Path

from flask import Blueprint, jsonify

setup_deps_bp = Blueprint("setup_deps", __name__, url_prefix="/api/setup")

# ── 커스텀 설치 경로 (앱 폴더 안 → 앱 삭제 시 함께 제거) ──────────────
_APP_ROOT        = r"C:\Program Files\DB_insight"
_LO_INSTALL_DIR  = _APP_ROOT + r"\Data\LibreOffice"
_LO_CUSTOM_EXE   = _APP_ROOT + r"\Data\LibreOffice\program\soffice.exe"

# 로컬에 번들된 MSI (최우선 사용) — 앱 루트에 위치
_LO_MSI_LOCAL = _APP_ROOT + r"\LibreOffice_26.2.2_Win_x86-64.msi"

# LibreOffice 경로 후보 — 커스텀 경로를 맨 앞에
_LO_PATHS = [
    _LO_CUSTOM_EXE,
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    r"C:\Program Files\LibreOffice 24\program\soffice.exe",
    r"C:\Program Files\LibreOffice 25\program\soffice.exe",
]

# 인터넷 다운로드 fallback URL
_LO_MSI_URL = (
    "https://download.documentfoundation.org/libreoffice/stable/"
    "25.2.2/win/x86_64/LibreOffice_25.2.2_Win_x86-64.msi"
)

# ── 설치 상태 (in-memory) ────────────────────────────────────────────
_status: dict = {"state": "idle", "progress": 0, "message": "", "error": ""}
_lock = threading.Lock()


def _find_soffice() -> str | None:
    env = os.environ.get("SOFFICE_PATH", "")
    if env and Path(env).exists():
        return env
    for p in _LO_PATHS:
        if Path(p).exists():
            return p
    try:
        r = subprocess.run(["where", "soffice"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            line = r.stdout.strip().split("\n")[0].strip()
            if line:
                return line
    except Exception:
        pass
    return None


# ── 엔드포인트 ────────────────────────────────────────────────────────

@setup_deps_bp.get("/check")
def check_deps():
    lo_path = _find_soffice()
    local_msi_exists = Path(_LO_MSI_LOCAL).exists()
    return jsonify({
        "libreoffice": {
            "installed": lo_path is not None,
            "path": lo_path,
        },
        "local_msi": {
            "exists": local_msi_exists,
            "path": _LO_MSI_LOCAL if local_msi_exists else None,
        },
    })


@setup_deps_bp.get("/install-status")
def install_status():
    with _lock:
        return jsonify(dict(_status))


@setup_deps_bp.post("/install-lo")
def install_lo():
    with _lock:
        if _status["state"] == "running":
            return jsonify({"error": "이미 설치 진행 중"}), 409
        _status.update(state="running", progress=0, message="설치 준비 중...", error="")
    threading.Thread(target=_do_install, daemon=True).start()
    return jsonify({"started": True})


# ── 설치 워커 ─────────────────────────────────────────────────────────

def _set(state=None, progress=None, message=None, error=None):
    with _lock:
        if state    is not None: _status["state"]    = state
        if progress is not None: _status["progress"] = progress
        if message  is not None: _status["message"]  = message
        if error    is not None: _status["error"]    = error


def _do_install():
    # 로컬 번들 MSI 만 사용 — 인터넷 연결 없음
    if not Path(_LO_MSI_LOCAL).exists():
        _set(state="error",
             error=f"번들 MSI 파일을 찾을 수 없습니다: {_LO_MSI_LOCAL}")
        return
    _set(progress=3, message=f"번들 MSI 설치 중...")
    _run_msi(_LO_MSI_LOCAL)


def _try_winget() -> bool:
    try:
        r = subprocess.run(
            ["winget", "--version"], capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return False
    except Exception:
        return False

    _set(progress=5, message="winget 으로 LibreOffice 설치 중...")
    try:
        proc = subprocess.Popen(
            [
                "winget", "install",
                "--id", "TheDocumentFoundation.LibreOffice",
                "--silent", "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        # 진행 표시 (winget은 % 출력 없으므로 단순 증가)
        step = 5
        for line in proc.stdout:
            step = min(step + 2, 90)
            _set(progress=step, message=line.strip()[:80] or f"설치 중... {step}%")
        proc.wait(timeout=600)
        if proc.returncode == 0:
            _set(state="done", progress=100, message="LibreOffice 설치 완료!")
            return True
        _set(state="error", error=f"winget 종료 코드 {proc.returncode}")
        return False
    except Exception as e:
        _set(state="error", error=f"winget 오류: {e}")
        return False


def _run_msi(msi_path: str) -> bool:
    """msiexec 를 PowerShell Start-Process -Verb RunAs 로 UAC 승격 후 실행.

    1603 오류 원인: Flask 프로세스가 일반 사용자 권한이라 Program Files
    또는 커스텀 INSTALLDIR 에 쓰기 불가. RunAs 로 관리자 권한 요청.
    """
    try:
        Path(_LO_INSTALL_DIR).mkdir(parents=True, exist_ok=True)

        # msiexec 인수 — INSTALLDIR 에 후행 역슬래시 포함 (LibreOffice MSI 규격)
        install_dir = _LO_INSTALL_DIR.rstrip("\\") + "\\"
        msi_args = f'/i "{msi_path}" /quiet /norestart INSTALLDIR="{install_dir}"'

        # PowerShell로 UAC 승격(RunAs) 후 msiexec 실행, 종료 코드 stdout 반환
        ps_cmd = (
            f"$p = Start-Process msiexec -ArgumentList '{msi_args}' "
            f"-Verb RunAs -Wait -PassThru; $p.ExitCode"
        )
        _set(progress=10, message="UAC 권한 요청 중 — 관리자 권한을 허용해 주세요...")
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=660,
        )
        exit_code_str = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        exit_code = int(exit_code_str) if exit_code_str.lstrip("-").isdigit() else result.returncode

        if exit_code in (0, 3010):  # 3010 = 재시작 필요(정상)
            _set(state="done", progress=100, message="LibreOffice 설치 완료!")
            return True
        _set(state="error", error=f"msiexec 종료 코드 {exit_code}")
        return False
    except Exception as e:
        _set(state="error", error=f"msiexec 오류: {str(e)[:200]}")
        return False


def _try_msi():
    tmp_path = None
    try:
        _set(progress=5, message="LibreOffice MSI 다운로드 중...")
        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, "LibreOffice.msi")

        def _reporthook(count, block, total):
            if total > 0:
                pct = int(count * block / total * 70)  # 0~70%
                _set(progress=min(pct, 70),
                     message=f"다운로드 중... {min(pct, 70)}%  ({count*block//1024//1024} MB)")

        urllib.request.urlretrieve(_LO_MSI_URL, tmp_path, _reporthook)
        _set(progress=75, message="다운로드 완료. 설치 중...")
        _run_msi(tmp_path)
    except Exception as e:
        _set(state="error", error=str(e)[:200])
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
