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


def create_app() -> Flask:
    app = Flask(__name__)
    # 개발(localhost:3000) + 패키징 앱(file://) 모두 허용
    CORS(app, resources={r"/api/*": {"origins": "*"}},
         supports_credentials=False)

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
