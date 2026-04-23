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

    return app


app = create_app()


if __name__ == "__main__":
    # 127.0.0.1 → 로컬호스트 전용, Windows 방화벽 팝업 안 뜸
    app.run(host="127.0.0.1", port=5001)
