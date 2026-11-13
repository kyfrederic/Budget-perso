"""Connexion par mot de passe, jeton CSRF, limitation des tentatives, en-têtes de sécurité."""
from __future__ import annotations

import hmac
import secrets
import time

from flask import (Blueprint, abort, current_app, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

bp = Blueprint("auth", __name__)

LONGUEUR_MIN_MOT_DE_PASSE = 14
PUBLIC_ENDPOINTS = {"auth.login", "static", "views.sante"}
# Hachage factice : même temps de calcul quand aucun mot de passe n'est défini.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


def hash_password(password: str) -> str:
    if len(password) < LONGUEUR_MIN_MOT_DE_PASSE:
        raise ValueError(f"Mot de passe trop court ({LONGUEUR_MIN_MOT_DE_PASSE} caractères minimum).")
    return generate_password_hash(password, method="scrypt")


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def _too_many_attempts(db, ip: str) -> bool:
    s = current_app.config["SETTINGS"]
    since = time.time() - s.fenetre_tentatives_minutes * 60
    db.execute("DELETE FROM login_attempts WHERE ts < ?", (since,))
    n = db.execute("SELECT COUNT(*) FROM login_attempts WHERE ip = ?", (ip,)).fetchone()[0]
    return n >= s.tentatives_max


@bp.before_app_request
def protect():
    g.user_id = session.get("user_id")
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not hmac.compare_digest(sent, session.get("csrf", "")) or not sent:
            abort(400, "Jeton de formulaire invalide ou expiré. Recharge la page.")
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if g.user_id is None:
        return redirect(url_for("auth.login"))
    return None


@bp.after_app_request
def security_headers(resp):
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'",
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.is_secure:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.endpoint != "static":
        resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/connexion", methods=["GET", "POST"])
def login():
    if g.user_id is not None:
        return redirect(url_for("views.home"))
    error = None
    if request.method == "POST":
        db = get_db()
        ip = request.remote_addr or "?"
        if _too_many_attempts(db, ip):
            db.commit()
            error = "Trop de tentatives. Réessaie dans quelques minutes."
        else:
            user = db.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
            stored = user["password_hash"] if user and user["password_hash"] else None
            ok = check_password_hash(stored or _DUMMY_HASH, request.form.get("password", ""))
            if ok and stored:
                db.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
                db.commit()
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                csrf_token()
                return redirect(url_for("views.home"))
            db.execute("INSERT INTO login_attempts (ip, ts) VALUES (?, ?)", (ip, time.time()))
            db.commit()
            error = "Mot de passe incorrect."
    return render_template("login.html", error=error), (401 if error else 200)


@bp.route("/deconnexion", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
