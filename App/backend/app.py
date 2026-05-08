import time

from flask import Flask
from flask_cors import CORS

from db.init_db import init_db
from routes.auth import auth_bp
from routes.history import history_bp
from routes.search import search_bp
from routes.index import index_bp
from routes.files import files_bp
from routes.trichef import bp as trichef_bp
from routes.trichef_admin import bp_admin as trichef_admin_bp
from routes.setup_deps import setup_deps_bp
from routes.security_mask import security_mask_bp
from routes.ai_search import ai_search_bp
from routes.registry import registry_bp
from routes.bgm import bp as bgm_bp
from routes.aimode import aimode_bp
from routes.stt import stt_bp


def _auto_normalize_paths_if_mismatch() -> None:
    """다른 PC 에서 git pull 후 첫 실행 시 자동 경로 정규화.

    감지 로직: registry.json 의 첫 entry 의 abs 가 현재 RAW_DB 와 다른 prefix 라면
    PC 가 바뀐 것 → scripts/normalize_registry_paths.py 자동 실행.
    """
    try:
        import json, subprocess, sys
        from pathlib import Path
        from config import EMBEDDED_DB, RAW_DB

        # 5개 도메인 중 하나라도 mismatch 가 있으면 normalize 실행
        sample_paths = [
            (EMBEDDED_DB / "Doc"   / "registry.json",    "abs",  RAW_DB / "Doc"),
            (EMBEDDED_DB / "Img"   / "registry.json",    "abs",  RAW_DB / "Img"),
            (EMBEDDED_DB / "Movie" / "registry.json",    "abs",  RAW_DB / "Movie"),
            (EMBEDDED_DB / "Rec"   / "registry.json",    "abs",  RAW_DB / "Rec"),
            (EMBEDDED_DB / "Bgm"   / "audio_meta.json",  "path", RAW_DB / "Movie" / "정혜_BGM_1차"),
        ]
        mismatch = False
        cur_root = str(RAW_DB.resolve()).replace("\\", "/")
        for p, key, _expected_dir in sample_paths:
            if not p.is_file():
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            sample_val = ""
            if isinstance(d, dict):
                # registry: dict of {key: {"abs": ...}}
                first_v = next(iter(d.values()), None)
                if isinstance(first_v, dict):
                    sample_val = (first_v.get(key) or "").replace("\\", "/")
            elif isinstance(d, list) and d and isinstance(d[0], dict):
                # audio_meta.json: list of dicts
                sample_val = (d[0].get(key) or "").replace("\\", "/")
            if sample_val and not sample_val.startswith(cur_root):
                mismatch = True
                break

        if not mismatch:
            return  # 이미 정규화됨

        import logging as _lg
        _lg.getLogger(__name__).warning(
            "[auto-normalize] PC 경로 mismatch 감지 — normalize_registry_paths.py 자동 실행"
        )
        repo_root = Path(__file__).resolve().parents[2]
        script = repo_root / "scripts" / "normalize_registry_paths.py"
        if script.is_file():
            try:
                r = subprocess.run(
                    [sys.executable, str(script)],
                    cwd=str(repo_root), capture_output=True, text=True, timeout=120,
                )
                if r.returncode == 0:
                    _lg.getLogger(__name__).info("[auto-normalize] 완료")
                else:
                    _lg.getLogger(__name__).warning(
                        f"[auto-normalize] 실패 (rc={r.returncode}): {r.stderr[-300:]}"
                    )
            except Exception as e:
                _lg.getLogger(__name__).warning(f"[auto-normalize] 실행 실패: {e}")
    except Exception:
        # config 등 미사용 가능 → silent skip
        pass


def create_app() -> Flask:
    app = Flask(__name__)
    # 개발(localhost:3000) + 패키징 앱(file://) 모두 허용
    CORS(app, resources={r"/api/*": {"origins": "*"}},
         supports_credentials=False)

    # 다른 PC 에서 첫 실행 시 자동 경로 정규화
    _auto_normalize_paths_if_mismatch()

    init_db()

    app.register_blueprint(auth_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(index_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(trichef_bp)
    app.register_blueprint(trichef_admin_bp)
    app.register_blueprint(setup_deps_bp)
    app.register_blueprint(security_mask_bp)
    app.register_blueprint(ai_search_bp)
    app.register_blueprint(registry_bp)
    app.register_blueprint(bgm_bp)
    app.register_blueprint(aimode_bp)
    app.register_blueprint(stt_bp)

    # [v9 health endpoint] Electron 의 _checkBackendAlive() 가 호출하는 초경량
    # endpoint. /api/search 는 인덱싱 / Qwen 추론으로 busy 시 응답 지연되어
    # health check 실패 → 멀쩡한 백엔드 죽이고 재시작 → 인덱싱 lost 부작용.
    # /api/health 는 Flask 라우터만 거쳐 즉시 응답 → 인덱싱 중에도 health 통과.
    @app.route("/api/health")
    def _health():
        return {"ok": True}, 200

    # [W5-4 → async + focused] image 도메인만 사전 로드 → 워밍업 시간 ~14s → ~6s.
    # doc_page / AV / Qwen / CLAP 은 첫 사용 시 lazy 로드 (모듈 자체 _load 락으로 안전).
    # OMC_FULL_WARMUP=1 → 모든 도메인 사전 로드 (server 모드용).
    # OMC_SYNC_WARMUP=1 → 동기 워밍업 강제 (디버깅).
    import threading as _th_w
    _warmup_event = _th_w.Event()
    _warmup_progress = {"stage": "init", "started": time.time(), "done": False}
    app._warmup_event = _warmup_event           # type: ignore[attr-defined]
    app._warmup_progress = _warmup_progress     # type: ignore[attr-defined]

    def _warmup_engine():
        import logging as _lg
        import os as _os_we
        _log = _lg.getLogger(__name__)
        try:
            _warmup_progress["stage"] = "engine_load"
            from routes.trichef import _get_engine
            eng = _get_engine()
            _warmup_progress["stage"] = "image_search"
            if "image" in eng._cache:
                try:
                    eng.search("워밍업", "image", topk=1)
                    _log.info("[warmup] image OK (async)")
                except Exception as e:
                    _log.warning(f"[warmup] image 실패: {e}")
            # 전체 도메인 사전 로드 (선택)
            if _os_we.environ.get("OMC_FULL_WARMUP", "").strip() == "1":
                _warmup_progress["stage"] = "doc_search"
                if "doc_page" in eng._cache:
                    try:
                        eng.search("워밍업", "doc_page", topk=1)
                    except Exception:
                        pass
                _warmup_progress["stage"] = "av_search"
                for av_dom in ("music", "movie"):
                    if av_dom in eng._cache:
                        try:
                            eng.search_av("워밍업", av_dom, topk=1)
                        except Exception:
                            pass
        except Exception as e:
            _log.warning(f"[warmup] skip: {e}")
        finally:
            _warmup_progress["stage"] = "done"
            _warmup_progress["done"] = True
            _warmup_progress["elapsed"] = time.time() - _warmup_progress["started"]
            _warmup_event.set()

    @app.route("/api/warmup-status")
    def _warmup_status():
        return {
            "ready": _warmup_event.is_set(),
            "stage": _warmup_progress.get("stage", "init"),
            "elapsed": round(time.time() - _warmup_progress["started"], 2),
        }, 200

    import os as _os_w_outer
    if _os_w_outer.environ.get("OMC_SYNC_WARMUP", "").strip() == "1":
        _warmup_engine()
    else:
        try:
            _th_w.Thread(target=_warmup_engine, daemon=True, name="engine-warmup").start()
        except Exception:
            pass

    # [VRAM] PyTorch allocator 튜닝 — 8GB GPU 단편화 방지.
    # expandable_segments: 큰 텐서 alloc 시 reserved 영역을 늘리는 대신 새 segment 추가.
    # 모델 로드/언로드 반복 시 단편화로 인한 가짜-OOM 감소.
    try:
        import os
        cur = os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "")
        if "expandable_segments" not in cur:
            os.environ["PYTORCH_CUDA_ALLOC_CONF"] = (
                f"{cur},expandable_segments:True" if cur else "expandable_segments:True"
            )
    except Exception:
        pass

    # BGM CLAP 워밍업 — laion/clap-htsat-unfused GPU 선로딩 (첫 검색 ~3s 지연 제거)
    # background thread → 서버 기동 지연 없음. GPU(RTX 4070 Laptop) 우선 사용.
    try:
        import threading, logging as _lg
        def _prewarm_bgm():
            try:
                from services.bgm.search_engine import get_engine as _bgm_engine
                _e = _bgm_engine()
                if _e.is_ready():
                    _e.search("워밍업", top_k=1)
                    _lg.getLogger(__name__).info("[warmup] bgm CLAP OK (GPU)")
            except Exception as _ex:
                _lg.getLogger(__name__).warning(f"[warmup] bgm skip: {_ex}")
        threading.Thread(target=_prewarm_bgm, daemon=True, name="bgm-clap-prewarm").start()
    except Exception:
        pass

    # [P0 #D] Qwen-VL 캡션 모델 prewarm — 인덱싱 전용 (검색에는 영향 없음).
    # [startup-speedup] default 비활성. OMC_QWEN_PREWARM=1 일 때만 시작 시 적재.
    # 인덱싱 첫 호출 시 lazy 로 로드 (~15-30s 소요) — 검색만 사용하는 사용자는 부담 없음.
    try:
        import os, threading, logging as _lg
        if os.environ.get("OMC_QWEN_PREWARM", "").strip() == "1":
            def _prewarm_qwen():
                try:
                    from embedders.trichef.incremental_runner import _get_qwen_captioner
                    _get_qwen_captioner()
                    _lg.getLogger(__name__).info("[prewarm] Qwen-VL 캡션 모델 로드 완료")
                except Exception as _e:
                    _lg.getLogger(__name__).warning(f"[prewarm] Qwen-VL 실패: {_e}")
            threading.Thread(target=_prewarm_qwen, daemon=True, name="qwen-prewarm").start()
    except Exception:
        pass

    return app


app = create_app()


if __name__ == "__main__":
    # 127.0.0.1 → 로컬호스트 전용, Windows 방화벽 팝업 안 뜸
    # threaded=True → 인덱싱(긴 요청) 중에도 /search /status /estimate 응답 가능.
    # 단일 스레드 dev server 는 인덱싱 처리 중 모든 요청 큐에 대기 → UI 멈춤 체감.
    app.run(host="127.0.0.1", port=5001, threaded=True)
