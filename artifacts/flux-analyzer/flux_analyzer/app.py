"""Flask app factory. Local run: python app.py."""
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request, session, render_template
from jsonschema import ValidationError
from werkzeug.exceptions import HTTPException
from config import prepare_workspace, WORKSPACE

def create_app(test_config: dict | None = None) -> Flask:
    """Build the Jinja application and register focused blueprints."""
    prepare_workspace()
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        # Local-only random secret persists over restarts; never a hardcoded key.
        secret_file = WORKSPACE / ".session_secret"
        if not secret_file.exists():
            secret_file.write_text(secrets.token_hex(32))
            secret_file.chmod(0o600)
        secret = secret_file.read_text()
    app.config.update(SECRET_KEY=secret, MAX_CONTENT_LENGTH=600 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true")
    if test_config:
        app.config.update(test_config)
    from web.routes_sources import bp as sources
    from web.routes_config import bp as configuration
    from web.routes_presets import bp as presets
    from web.routes_run import bp as runs
    from web.routes_docs import bp as docs
    from web.routes_journey import bp as journey
    from web.routes_setups import bp as setups
    from web.state import get_project, public_state, save_project, csrf_token
    app.register_blueprint(sources)
    app.register_blueprint(configuration)
    app.register_blueprint(presets)
    app.register_blueprint(runs)
    app.register_blueprint(docs)
    app.register_blueprint(journey)
    app.register_blueprint(setups)
    from web.terms import client_meta
    app.jinja_env.globals.update(journey_meta=client_meta)

    @app.before_request
    def protect_mutations() -> object:
        """Reject cross-site writes; credentials remain only in backend."""
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            expected = session.get("csrf_token")
            received = request.headers.get("X-CSRF-Token", "")
            if not expected or not secrets.compare_digest(expected, received):
                return jsonify({"error": "Your session needs refreshing. Reload the page and try again."}), 403
        return None

    @app.after_request
    def privacy_headers(response: object) -> object:
        """Private financial data must not be cached by proxies or browsers."""
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    # Advanced steps and Simple stages map onto each other so old links keep working.
    step_to_stage = {"sources": "upload", "flux": "path", "columns": "data", "comparison": "compare", "scope": "include", "classification": "group", "rules": "important", "review": "review", "results": "results"}
    stage_to_step = {"upload": "sources", "path": "sources", "data": "columns", "compare": "comparison", "include": "scope", "group": "classification", "important": "rules", "explain": "rules", "review": "review", "results": "results", "save": "review"}

    @app.get("/")
    def home() -> object:
        state = get_project()
        step = state.get("step", "sources")
        return render_template("index.html", initial=public_state(state), step=step, stage=state.get("stage") or step_to_stage.get(step, "upload"))

    @app.get("/review", defaults={"step": "review"})
    @app.get("/step/<step>")
    def step_page(step: str) -> object:
        if step not in step_to_stage:
            return jsonify({"error": "Step not found."}), 404
        state = get_project()
        state["step"] = step
        state["stage"] = step_to_stage[step]
        save_project(state)
        return render_template("index.html", initial=public_state(state), step=step, stage=step_to_stage[step])

    @app.get("/flow/<stage>")
    def flow_page(stage: str) -> object:
        if stage not in stage_to_step:
            return jsonify({"error": "Page not found."}), 404
        state = get_project()
        state["stage"], state["step"] = stage, stage_to_step[stage]
        save_project(state)
        return render_template("index.html", initial=public_state(state), step=state["step"], stage=stage)

    @app.get("/healthz")
    def health() -> object:
        return jsonify({"status": "ok", "engine": "python", "storage": "local workspace"})

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.errorhandler(ValueError)
    @app.errorhandler(KeyError)
    @app.errorhandler(ValidationError)
    def invalid(error: Exception) -> object:
        message = error.message if isinstance(error, ValidationError) else str(error)
        return jsonify({"error": message}), 400

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> object:
        return jsonify({"error": error.description}), error.code

    @app.errorhandler(Exception)
    def unexpected(error: Exception) -> object:
        # Never echo API headers, filesystem paths or unexpected request details.
        app.logger.error("Operation failed: %s", type(error).__name__)
        return jsonify({"error": "This operation could not complete. Check your file and configuration, then try again."}), 500
    return app

app = create_app()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False, threaded=True)
