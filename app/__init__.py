from flask import Flask

from .config import Config
from .repository import InMemoryRepository, PostgresRepository
from .services import DatabaseConnectionError


def create_app(config_object=None, repository=None):
    app = Flask(__name__)
    app.config.from_object(config_object or Config)

    if repository is None:
        repository = PostgresRepository(app.config["DATABASE_URL"])

    app.extensions["repository"] = repository

    from .auth import auth_bp
    from .routes import ui_bp
    from .api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(ui_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.errorhandler(DatabaseConnectionError)
    def handle_database_connection_error(error):
        from flask import jsonify, render_template, request

        message = str(error)
        if request.path.startswith("/api/"):
            return jsonify({"error": message}), 503
        return render_template("database_error.html", error_message=message), 503

    @app.context_processor
    def inject_globals():
        from .security import current_user

        return {"current_user": current_user(), "user_roles": ("ADMIN", "MANAGER", "WAREHOUSE")}

    return app


__all__ = ["create_app", "InMemoryRepository"]
