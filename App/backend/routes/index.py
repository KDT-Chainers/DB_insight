import os
import threading
import uuid

from flask import Blueprint, jsonify, request

from embedders.trichef.incremental_runner import (
    embed_image_file, embed_doc_file,
    IMAGE_EMBED_EXTS, DOC_EMBED_EXTS,
)
from embedders.trichef.av_embed import (
    embed_movie_file, embed_music_file,
    MOVIE_EXTS, MUSIC_EXTS,
)

index_bp = Blueprint("index", __name__, url_prefix="/api/index")

# ---------------------------------------------------------------------------
# 확장자 → 유형 매핑
# ---------------------------------------------------------------------------

EXT_TYPE_MAP: dict[str, str] = {}
# video / audio: MR_TriCHEF TRI-CHEF 파이프라인
for _ext in MOVIE_EXTS:
    EXT_TYPE_MAP[_ext] = "video"
for _ext in MUSIC_EXTS:
    EXT_TYPE_MAP[_ext] = "audio"
# image / doc: DI_TriCHEF TRI-CHEF 단일 파일 함수
for _ext in IMAGE_EMBED_EXTS:
    EXT_TYPE_MAP[_ext] = "image"
for _ext in DOC_EMBED_EXTS:
    EXT_TYPE_MAP[_ext] = "doc"

# 활성 임베더 — 전 타입 TRI-CHEF 파이프라인 사용
EMBEDDERS = {
    "video": embed_movie_file,
    "audio": embed_music_file,
    "image": embed_image_file,
    "doc":   embed_doc_file,
}

# 인덱싱 가능한 타입 (UI 파일 트리에서 활성 표시)
ACTIVE_TYPES = {"video", "audio", "image", "doc"}

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


@index_bp.post("/estimate")
def estimate():
    """
    POST /api/index/estimate
    Body:     { "files": ["C:/...", "..."] }
    Response: { total_seconds, skipped_count, new_count, unsupported, by_type }

    선택된 파일들의 예상 총 인덱싱 시간을 즉시 반환 (디스크 read 만, embedding X).
    UI 가 "선택됨 N개 — 예상 5분 23초" 표시용.
    """
    data = request.get_json(silent=True) or {}
    files = data.get("files", [])
    if not isinstance(files, list):
        return jsonify({"error": "files must be a list"}), 400
    if len(files) > 20000:
        return jsonify({"error": "too many files (max 20000)"}), 400
    try:
        from services.index_estimator import estimate as _est
        return jsonify(_est(files))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

    # 인덱싱 시작 전 stale 캐시 정리 (이전 강제 종료로 누적된 임시 폴더 GC).
    # 1시간 미사용 폴더만 정리 → 동시 실행 작업 영향 없음.
    try:
        from services.cache_janitor import cleanup_stale_caches
        gc_stats = cleanup_stale_caches()
        if gc_stats["removed"]:
            print(f"[cache_janitor] cleaned {gc_stats['removed']} stale dirs "
                  f"({gc_stats['freed_bytes']:,} bytes)", flush=True)
    except Exception as _e:
        pass

    job_id = uuid.uuid4().hex
    results = [{"path": p, "status": "pending"} for p in file_paths]

    import time as _t
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id":     job_id,
            "status":     "running",
            "total":      len(file_paths),
            "done":       0,
            "skipped":    0,
            "errors":     0,
            "results":    results,
            # [ETA] 모달이 닫혔다 다시 열려도 ETA가 리셋되지 않도록 backend 가
            # 작업 시작 시각 보유. epoch seconds (UTC).
            "started_at": _t.time(),
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

    1) stop_flag 를 True 로 설정 (단계 간 폴링 지점에서 감지)
    2) ffmpeg 등 blocking child 프로세스를 OS 시그널로 종료
       → embedder 의 subprocess.run 이 즉시 예외 반환 → 단계 종료 → flag 감지
    """
    with _jobs_lock:
        if job_id not in _jobs:
            return jsonify({"error": "Job not found"}), 404
        _stop_flags[job_id] = True
        _jobs[job_id]["stopping"] = True

    # blocking 자식 프로세스 즉시 종료 (UX critical — 사용자가 무한 대기 X)
    killed = 0
    try:
        from services.job_control import kill_indexing_subprocesses
        killed = kill_indexing_subprocesses()
    except Exception:
        pass
    return jsonify({"ok": True, "subprocesses_killed": killed})


@index_bp.get("/stream/<job_id>")
def stream(job_id: str):
    """
    GET /api/index/stream/{job_id}
    Server-Sent Events 스트림. 1초 폴링 → push 모델로 전환.
    상태 변화 시에만 data 이벤트 송신, 변화 없으면 15초 keepalive.
    job 종료(done/error/stopped) 시 스트림 자동 종료.
    """
    import json as _json
    import time as _time
    from flask import Response, stream_with_context

    @stream_with_context
    def gen():
        last_payload = None
        last_keepalive = _time.time()
        # 일관성 있게 종료하기 위한 max iteration 한도 (안전망).
        max_iter = 60 * 60 * 4   # 4시간 한도 (0.25s tick) — 거의 무한
        for _ in range(max_iter):
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None:
                    yield "event: error\ndata: {\"error\":\"Job not found\"}\n\n"
                    return
                snap = _json.dumps(job)
                status_now = job.get("status")
            if snap != last_payload:
                yield f"data: {snap}\n\n"
                last_payload = snap
                last_keepalive = _time.time()
            elif _time.time() - last_keepalive > 15.0:
                yield ": keepalive\n\n"
                last_keepalive = _time.time()
            if status_now in ("done", "error", "stopped"):
                return
            _time.sleep(0.25)

    return Response(gen(), mimetype="text/event-stream",
                    headers={
                        "X-Accel-Buffering": "no",
                        "Cache-Control":     "no-cache",
                        "Connection":        "keep-alive",
                    })


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
    import time as _t
    done = 0
    skipped = 0
    errors = 0

    # [P0 #A,B] 배치 종료 시 lexical rebuild 1회 + reload_engine 1회 적용용 추적.
    # 파일마다 호출되던 비싼 후처리(파일×N 비용)를 배치 끝에 1회 처리(고정 비용)로 통합.
    domains_dirty: set[str] = set()

    # [옵션 B] 주기적 reload — 긴 배치 진행 중에도 새로 commit 된 파일이
    # 검색에 반영되도록 매 RELOAD_EVERY_DONE 개 완료 또는 RELOAD_EVERY_SEC 초마다
    # 백그라운드 thread 에서 reload_engine() 호출.
    RELOAD_EVERY_DONE = 3
    RELOAD_EVERY_SEC  = 60.0
    _last_reload_at = _t.time()
    _done_since_reload = 0
    def _bg_reload_engine():
        try:
            from routes.trichef import reload_engine as _re
            _re()
        except Exception:
            pass

    # [Electron P2] GC threshold 완화 — 임베딩 중 numpy/torch 임시 객체 다수 발생.
    # 기본 (700,10,10) 은 너무 자주 트리거 → 짧은 정지 누적. 작업 후 명시 collect.
    import gc as _gc
    _gc_orig = _gc.get_threshold()
    try:
        _gc.set_threshold(100000, 50, 50)
    except Exception:
        _gc_orig = None

    stopped_early = False
    for i, path in enumerate(file_paths):
        # [#3] 중단 요청 확인 — 조기 return 대신 break → finalize 블록 실행 보장.
        # 이전: return 으로 빠지면서 chroma_drain / lexical_rebuild / reload_engine 누락 →
        # 이미 등록된 파일들이 검색 캐시에 반영 안 되는 race condition 발생.
        if _is_stopped(job_id):
            for j in range(i, len(file_paths)):
                if results[j]["status"] == "pending":
                    results[j]["status"] = "skipped"
                    results[j]["reason"] = "사용자 중단"
                    skipped += 1
            stopped_early = True
            break

        results[i]["status"] = "running"
        _update_job(job_id, done, skipped, errors, "running")

        file_type = _get_file_type(path)
        embedder = EMBEDDERS.get(file_type) if file_type else None

        if file_type is None:
            # 인식 불가 확장자
            results[i]["status"] = "skipped"
            results[i]["reason"] = "지원하지 않는 파일 형식"
            skipped += 1
        elif file_type not in ACTIVE_TYPES:
            # 인식은 되지만 현재 임베더 미활성
            results[i]["status"] = "skipped"
            results[i]["reason"] = f"{file_type} 타입 임베더 미활성"
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

                # progress_cb: 전 타입 지원 (video=5단계, audio=4단계, image/doc=3단계)
                kwargs = {"progress_cb": _make_cb(i, job_id)}
                # [P0 #B] image/doc 은 lexical rebuild 지연 → 배치 끝에 1회.
                # av_embed(movie/music) 는 lexical_rebuild 미사용이므로 적용 X.
                if file_type in ("image", "doc"):
                    kwargs["defer_lexical_rebuild"] = True
                result = embedder(path, **kwargs)
                if result.get("status") == "done":
                    domains_dirty.add(file_type)
                    _done_since_reload += 1
                    # [옵션 B] 주기적 reload 트리거 (3개 완료 또는 60초마다)
                    if _done_since_reload >= RELOAD_EVERY_DONE \
                       or (_t.time() - _last_reload_at) >= RELOAD_EVERY_SEC:
                        threading.Thread(target=_bg_reload_engine,
                                         name="periodic-reload-engine",
                                         daemon=True).start()
                        _last_reload_at = _t.time()
                        _done_since_reload = 0
                # [P0 #VRAM] 임계값 초과 시에만 empty_cache (대부분 noop, 비용 ~0)
                try:
                    from services.vram_janitor import cleanup_if_above
                    cleanup_if_above(threshold_mb=6000.0)
                except Exception:
                    pass
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

    # ── [P0 #A,B] 배치 종료 후 후처리 (이전: 파일×N → 현재: 1회) ──────────────
    # image/doc 도메인 lexical 인덱스 1회 재구축, 검색 엔진 캐시 1회 reload.
    # 9개 신규 파일 처리 시 약 30~60초 절감.
    # [Sprint C] ChromaDB 비동기 큐 드레인 → reload_engine 정합성 확보.
    try:
        from services.chroma_async import drain_and_wait as _chroma_drain
        if not _chroma_drain(timeout=180.0):
            print("[batch] chroma_async drain timeout — 일부 upsert 미완료 가능", flush=True)
    except Exception as _e:
        pass

    if domains_dirty:
        try:
            from services.trichef import lexical_rebuild as _lex
            if "image" in domains_dirty:
                try: _lex.rebuild_image_lexical()
                except Exception as e: print(f"[batch] image lexical rebuild 실패: {e}", flush=True)
            if "doc" in domains_dirty:
                try: _lex.rebuild_doc_lexical()
                except Exception as e: print(f"[batch] doc lexical rebuild 실패: {e}", flush=True)
        except Exception as e:
            print(f"[batch] lexical_rebuild import 실패: {e}", flush=True)
        try:
            from routes.trichef import reload_engine
            reload_engine()
        except Exception as e:
            print(f"[batch] reload_engine 실패: {e}", flush=True)
        # 배치 종료 후 VRAM 정리 — 다음 검색 호출 대비.
        try:
            from services.vram_janitor import cleanup, vram_summary
            r = cleanup()
            print(f"[batch] {vram_summary()} freed={r.get('freed_mb')}MB", flush=True)
        except Exception:
            pass

    # GC threshold 복원 + 명시 collect (임베딩 중 누적된 객체 한 번에 회수).
    try:
        if _gc_orig is not None:
            _gc.set_threshold(*_gc_orig)
        _gc.collect()
    except Exception:
        pass

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
