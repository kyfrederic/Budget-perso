import sqlite3
from pathlib import Path

import pytest

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
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "SESSION_COOKIE_SECURE": False})
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute("UPDATE users SET password_hash = ?", (hash_password(PASSWORD),))
    conn.commit()
    conn.close()
    return app


@pytest.fixture
def client(app):
    return app.test_client()
