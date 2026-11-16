from pathlib import Path

import os

import pytest

from budget import db as dbmod
from budget import create_app
from budget.auth import hash_password
from budget.settings import load_settings

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "un-mot-de-passe-solide"


@pytest.fixture
def settings():
    return load_settings(ROOT / "config" / "settings.toml")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDGET_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    # TEST_DATABASE_URL=postgresql://… rejoue toute la suite sur Postgres (base vidée à chaque test).
    url = os.environ.get("TEST_DATABASE_URL")
    dbmod.reset_shared()
    if url:
        admin = dbmod.connect(url)
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")
        admin.commit()
        admin.close()
        monkeypatch.setenv("DATABASE_URL", url)
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "SESSION_COOKIE_SECURE": False})
    conn = dbmod.connect(app.config["DATABASE"])
    conn.execute("UPDATE users SET password_hash = ?", (hash_password(PASSWORD),))
    conn.commit()
    conn.close()
    return app


@pytest.fixture
def client(app):
    return app.test_client()
