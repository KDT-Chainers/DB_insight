"""scripts/_time_flask_startup.py — Flask /api/health 응답까지 걸리는 시간 측정."""
import subprocess, sys, time, urllib.request, os
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"
env["TRICHEF_USE_RERANKER"] = "1"

print("Flask 기동 중...", flush=True)
t0 = time.time()
proc = subprocess.Popen(
    [sys.executable, "app.py"], cwd=str(BACKEND), env=env,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008,
)
deadline = t0 + 60
ok = False
while time.time() < deadline:
    try:
        urllib.request.urlopen("http://127.0.0.1:5001/api/health", timeout=2)
        elapsed = time.time() - t0
        print(f"\n[OK] /api/health 응답 - {elapsed:.2f}s", flush=True)
        ok = True
        break
    except Exception:
        time.sleep(0.2)

if not ok:
    print("[FAIL] TIMEOUT (>60s)", flush=True)

# 첫 검색도 측정 (워밍업 백그라운드 진행 영향 보기)
if ok:
    print("\n첫 검색 측정 (워밍업 영향 확인)...", flush=True)
    t1 = time.time()
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:5001/api/search?q=%EA%B3%A0%EC%96%91%EC%9D%B4&top_k=3&type=image",
            timeout=120
        )
        print(f"  첫 검색: {time.time() - t1:.2f}s", flush=True)
    except Exception as e:
        print(f"  실패: {e}", flush=True)

# cleanup
import signal
try:
    proc.terminate()
    proc.wait(timeout=5)
except Exception:
    proc.kill()
