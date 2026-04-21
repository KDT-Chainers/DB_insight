import os
import threading
import uuid

from flask import Blueprint, jsonify, request

from embedders import doc, video, image, audio

index_bp = Blueprint("index", __name__, url_prefix="/api/index")

# ---------------------------------------------------------------------------
# 확장자 → 유형 매핑
# ---------------------------------------------------------------------------

EXT_TYPE_MAP: dict[str, str] = {}
for _ext in doc.SUPPORTED_EXTENSIONS:
    EXT_TYPE_MAP[_ext] = "doc"
for _ext in video.SUPPORTED_EXTENSIONS:
    EXT_TYPE_MAP[_ext] = "video"
for _ext in image.SUPPORTED_EXTENSIONS:
    EXT_TYPE_MAP[_ext] = "image"
for _ext in audio.SUPPORTED_EXTENSIONS:
    EXT_TYPE_MAP[_ext] = "audio"

EMBEDDERS = {
    "doc":   doc.embed,
    "video": video.embed,
    "image": image.embed,
    "audio": audio.embed,
}

# ---------------------------------------------------------------------------
# 인메모리 job 저장소 (서버 재시작 시 초기화)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_stop_flags: dict[str, bool] = {}   # job_id → True 이면 중단 요청됨


def _get_file_type(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    return EXT_TYPE_MAP.get(ext)


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------

@index_bp.post("/scan")
def scan():
    """
    POST /api/index/scan
    Body: { "path": "C:/Users/..." }

    폴더를 재귀 스캔하여 파일 목록 반환.
    Response:
    {
      "path": "...",
      "files": [ { "name", "path", "type", "size" }, ... ]
    }
    """
    data = request.get_json(silent=True) or {}
    folder_path = data.get("path", "").strip()

    if not folder_path:
        return jsonify({"error": "path is required"}), 400
    if not os.path.isdir(folder_path):
        return jsonify({"error": "Path not found"}), 404

    # 1단계만 반환 — 폴더/파일 구분
    items = []
    try:
        entries = list(os.scandir(folder_path))
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403

    for entry in sorted(entries, key=lambda e: (not e.is_dir(), e.name.lower())):
        try:
            if entry.is_dir(follow_symlinks=False):
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "kind": "folder",
                    "type": None,
                    "size": None,
                })
            else:
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "kind": "file",
                    "type": _get_file_type(entry.path),
                    "size": entry.stat().st_size,
                })
        except OSError:
            continue

    return jsonify({"path": folder_path, "items": items})


@index_bp.post("/start")
def start():
    """
    POST /api/index/start
    Body: { "files": ["C:/…/a.pdf", "C:/…/b.mp4"] }

    선택된 파일들의 임베딩을 백그라운드로 시작.
    Response: { "job_id": "abc123", "total": 2 }
    """
    data = request.get_json(silent=True) or {}
    file_paths = data.get("files", [])

    if not isinstance(file_paths, list) or not file_paths:
        return jsonify({"error": "No valid files provided"}), 400

    job_id = uuid.uuid4().hex
    results = [{"path": p, "status": "pending"} for p in file_paths]

    with _jobs_lock:
        _jobs[job_id] = {
            "job_id":  job_id,
            "status":  "running",
            "total":   len(file_paths),
            "done":    0,
            "skipped": 0,
            "errors":  0,
            "results": results,
        }

    with _jobs_lock:
        _stop_flags[job_id] = False

    thread = threading.Thread(target=_run_job, args=(job_id, file_paths, results), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "total": len(file_paths)})


@index_bp.post("/stop/<job_id>")
def stop(job_id: str):
    """
    POST /api/index/stop/{job_id}
    진행 중인 인덱싱 작업을 중단 요청.
    """
    with _jobs_lock:
        if job_id not in _jobs:
            return jsonify({"error": "Job not found"}), 404
        _stop_flags[job_id] = True
        _jobs[job_id]["stopping"] = True
    return jsonify({"ok": True})


@index_bp.get("/status/<job_id>")
def status(job_id: str):
    """
    GET /api/index/status/{job_id}

    인덱싱 진행 상태 조회.
    Response:
    {
      "job_id": "...", "status": "running|done|error",
      "total": 2, "done": 1, "errors": 0,
      "results": [ { "path": "...", "status": "done|running|pending|error" }, ... ]
    }
    """
    with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(job)


# ---------------------------------------------------------------------------
# 백그라운드 임베딩 실행
# ---------------------------------------------------------------------------

def _is_stopped(job_id: str) -> bool:
    with _jobs_lock:
        return _stop_flags.get(job_id, False)


def _run_job(job_id: str, file_paths: list[str], results: list[dict]) -> None:
    done = 0
    skipped = 0
    errors = 0

    for i, path in enumerate(file_paths):
        # 중단 요청 확인
        if _is_stopped(job_id):
            # 남은 파일들을 skipped 처리
            for j in range(i, len(file_paths)):
                if results[j]["status"] == "pending":
                    results[j]["status"] = "skipped"
                    results[j]["reason"] = "사용자 중단"
                    skipped += 1
            _update_job(job_id, done, skipped, errors, "stopped")
            return

        results[i]["status"] = "running"
        _update_job(job_id, done, skipped, errors, "running")

        file_type = _get_file_type(path)
        embedder = EMBEDDERS.get(file_type) if file_type else None

        if embedder is None:
            # 지원하지 않는 확장자
            results[i]["status"] = "skipped"
            results[i]["reason"] = "지원하지 않는 파일 형식"
            skipped += 1
        else:
            try:
                # 단계별 진행 콜백 (video embedder만 사용)
                # stop_flag 를 반환하면 embedder가 중단 처리
                def _make_cb(_i, _job_id):
                    def _cb(step, total, detail):
                        results[_i]["step"]       = step
                        results[_i]["step_total"]  = total
                        results[_i]["step_detail"] = detail
                        return _is_stopped(_job_id)  # True 이면 중단 신호
                    return _cb

                kwargs = {"progress_cb": _make_cb(i, job_id)} if file_type == "video" else {}
                result = embedder(path, **kwargs)
                status = result.get("status", "error")
                if status == "done":
                    results[i]["status"] = "done"
                    done += 1
                elif status == "skipped":
                    results[i]["status"] = "skipped"
                    results[i]["reason"] = result.get("reason", "")
                    skipped += 1
                else:
                    reason = result.get("reason") or f"status={status}"
                    results[i]["status"] = "error"
                    results[i]["reason"] = reason
                    errors += 1
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                msg = str(e) or type(e).__name__
                results[i]["status"] = "error"
                results[i]["reason"] = f"{type(e).__name__}: {msg}"
                # 서버 로그에도 전체 스택 출력
                print(f"[ERROR] {path}\n{tb}", flush=True)
                errors += 1

        _update_job(job_id, done, skipped, errors, "running")

    # 최종 상태 결정
    if _is_stopped(job_id):
        final_status = "stopped"
    elif errors == len(file_paths):
        final_status = "error"
    else:
        final_status = "done"
    _update_job(job_id, done, skipped, errors, final_status)


def _update_job(job_id: str, done: int, skipped: int, errors: int, status: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["done"] = done
            _jobs[job_id]["skipped"] = skipped
            _jobs[job_id]["errors"] = errors
            _jobs[job_id]["status"] = status
