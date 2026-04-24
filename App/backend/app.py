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

    return app


app = create_app()


if __name__ == "__main__":
    # 127.0.0.1 → 로컬호스트 전용, Windows 방화벽 팝업 안 뜸
    app.run(host="127.0.0.1", port=5001)
