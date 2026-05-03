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

    # [W5-4] Warmup — 기동 시 TriChefEngine 싱글턴 로드 + dummy 쿼리 1회 실행하여
    # SigLIP2 / BGE-M3 / DINOv2 / Qwen 을 선로딩. 첫 사용자 쿼리 430ms 지연 제거.
    try:
        import logging
        from routes.trichef import _get_engine
        _log = logging.getLogger(__name__)
        eng = _get_engine()
        # Doc/Img 워밍업 — SigLIP2 / BGE-M3 / DINOv2 / Qwen 선로딩
        for dom in ("image", "doc_page"):
            if dom in eng._cache:
                try:
                    eng.search("워밍업", dom, topk=1)
                    _log.info(f"[warmup] {dom} OK")
                    break
                except Exception as e:
                    _log.warning(f"[warmup] {dom} 실패: {e}")
        # AV 워밍업 — movie/music 캐시가 있을 때만 search_av 1회 실행
        for av_dom in ("music", "movie"):
            if av_dom in eng._cache:
                try:
                    eng.search_av("워밍업", av_dom, topk=1)
                    _log.info(f"[warmup] {av_dom} OK")
                except Exception as e:
                    _log.warning(f"[warmup] {av_dom} 실패: {e}")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[warmup] skip: {e}")

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

    # [P0 #D] Qwen-VL 캡션 모델 background prewarm.
    # 인덱싱 시작 시 첫 이미지 파일에서 발생하던 ~15-30s 모델 로드 지연을 제거.
    # 비동기 thread → 검색·UI 응답에는 무영향. 환경변수 OMC_DISABLE_QWEN_PREWARM=1 로 OFF.
    try:
        import os, threading, logging as _lg
        if os.environ.get("OMC_DISABLE_QWEN_PREWARM", "").strip().lower() not in ("1","true","yes"):
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
