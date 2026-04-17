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

    max_depth = 3   # 하위 폴더 탐색 최대 깊이
    max_files = 500  # 최대 파일 수 제한
    base_depth = folder_path.rstrip("/\\").count(os.sep)

    files = []
    for root, _dirs, filenames in os.walk(folder_path):
        current_depth = root.count(os.sep) - base_depth
        if current_depth >= max_depth:
            _dirs.clear()  # 더 깊이 내려가지 않음
            continue
        for filename in filenames:
            if len(files) >= max_files:
                break
            full_path = os.path.join(root, filename)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                size = 0
            files.append({
                "name": filename,
                "path": full_path,
                "type": _get_file_type(full_path),
                "size": size,
            })
        if len(files) >= max_files:
            break

    return jsonify({"path": folder_path, "files": files})


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
            "job_id": job_id,
            "status": "running",
            "total":  len(file_paths),
            "done":   0,
            "errors": 0,
            "results": results,
        }

    thread = threading.Thread(target=_run_job, args=(job_id, file_paths, results), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "total": len(file_paths)})


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

def _run_job(job_id: str, file_paths: list[str], results: list[dict]) -> None:
    done = 0
    errors = 0

    for i, path in enumerate(file_paths):
        results[i]["status"] = "running"
        _update_job(job_id, done, errors, "running")

        file_type = _get_file_type(path)
        embedder = EMBEDDERS.get(file_type) if file_type else None

        if embedder is None:
            results[i]["status"] = "error"
            errors += 1
        else:
            try:
                result = embedder(path)
                if result.get("status") == "done":
                    results[i]["status"] = "done"
                    done += 1
                else:
                    results[i]["status"] = "error"
                    errors += 1
            except Exception:
                results[i]["status"] = "error"
                errors += 1

    final_status = "error" if errors == len(file_paths) else "done"
    _update_job(job_id, done, errors, final_status)


def _update_job(job_id: str, done: int, errors: int, status: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["done"] = done
            _jobs[job_id]["errors"] = errors
            _jobs[job_id]["status"] = status
