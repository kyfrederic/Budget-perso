"""Accès SQLite."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def ensure_user(conn: sqlite3.Connection, name: str = "fred") -> int:
    row = conn.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO users (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def sync_accounts(conn: sqlite3.Connection, user_id: int, settings) -> None:
    """Crée les comptes déclarés dans settings.toml et met à jour leur ordre."""
    for i, c in enumerate(settings.comptes):
        conn.execute(
            "INSERT INTO accounts (user_id, name, sort) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, name) DO UPDATE SET sort = excluded.sort",
            (user_id, c.nom, i),
        )
    conn.commit()


def backup_to(src_path: str, dest_path: str) -> None:
    """Copie cohérente de la base (API de sauvegarde SQLite, sûre pendant l'utilisation)."""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dest_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
