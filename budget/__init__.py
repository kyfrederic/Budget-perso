"""Application de budget personnel (V1)."""
from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask

from . import db as dbmod
from .money import date_fr, format_eur, format_input, month_label
from .settings import load_settings

ROOT = Path(__file__).resolve().parent.parent


def _secret_key(instance: Path) -> str:
    env = os.environ.get("BUDGET_SECRET_KEY")
    if env:
        return env
    f = instance / "secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip()


def create_app(test_config: dict | None = None) -> Flask:
    instance = Path(os.environ.get("BUDGET_DATA_DIR", ROOT / "instance"))
    app = Flask(__name__, instance_path=str(instance))
    instance.mkdir(parents=True, exist_ok=True)
    app.config.update(
        DATABASE=str(instance / "budget.sqlite"),
        SETTINGS_FILE=os.environ.get("BUDGET_SETTINGS", str(ROOT / "config" / "settings.toml")),
        MODELE_FILE=os.environ.get("BUDGET_MODELE", str(ROOT / "config" / "modele.toml")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # En production (HTTPS) le cookie n'est jamais envoyé en clair.
        # BUDGET_DEV=1 uniquement pour un essai local en http://localhost.
        SESSION_COOKIE_SECURE=os.environ.get("BUDGET_DEV") != "1",
        SESSION_COOKIE_NAME="budget_session",
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _secret_key(instance)

    settings = load_settings(app.config["SETTINGS_FILE"])
    app.config["SETTINGS"] = settings
    app.permanent_session_lifetime = timedelta(hours=settings.duree_session_heures)

    if os.environ.get("BUDGET_BEHIND_PROXY") == "1":
        # Derrière Caddy : la vraie adresse du client est dans X-Forwarded-For.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    conn = dbmod.connect(app.config["DATABASE"])
    dbmod.init_schema(conn)
    user_id = dbmod.ensure_user(conn)
    dbmod.sync_accounts(conn, user_id, settings)
    conn.close()

    app.teardown_appcontext(dbmod.close_db)
    app.jinja_env.filters["eur"] = format_eur
    app.jinja_env.filters["saisie"] = format_input
    app.jinja_env.filters["datefr"] = date_fr
    app.jinja_env.globals["month_label"] = month_label

    from . import auth, cli, views
    app.jinja_env.globals["csrf_token"] = auth.csrf_token
    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    cli.register(app)
    return app
