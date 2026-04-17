from flask import Flask
from flask_cors import CORS

from db.init_db import init_db
from routes.auth import auth_bp
from routes.history import history_bp
from routes.search import search_bp


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": ["http://localhost:3000"]}})

    init_db()

    app.register_blueprint(auth_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(search_bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
