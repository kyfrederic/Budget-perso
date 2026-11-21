"""Connexion (mot de passe puis code à 6 chiffres), mise en route, jeton CSRF,
limitation des tentatives, en-têtes de sécurité."""
from __future__ import annotations

import hmac
import os
import secrets
import time

from flask import (Blueprint, abort, current_app, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import totp
from .db import get_db

bp = Blueprint("auth", __name__)

LONGUEUR_MIN_MOT_DE_PASSE = 14
PUBLIC_ENDPOINTS = {"auth.login", "auth.login_code", "auth.setup", "static", "views.sante"}
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


def security_row(db, user_id: int):
    return db.execute("SELECT * FROM user_security WHERE user_id = ?", (user_id,)).fetchone()


def _open_session(user_id: int) -> None:
    session.clear()
    session.permanent = True
    session["user_id"] = user_id
    csrf_token()


def _fail(db, ip: str) -> None:
    db.execute("INSERT INTO login_attempts (ip, ts) VALUES (?, ?)", (ip, time.time()))
    db.commit()


@bp.after_app_request
def security_headers(resp):
    resp.headers.setdefault(
        "Content-Security-Policy",
        # wasm-unsafe-eval et worker-src : moteur de lecture des tickets (tesseract.js, servi par l'appli).
        # blob: pour l'aperçu de la photo avant envoi. Aucune source extérieure n'est autorisée.
        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; "
        "img-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    )
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.is_secure:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.endpoint not in ("static", "views.ticket_photo"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/connexion", methods=["GET", "POST"])
def login():
    if g.user_id is not None:
        return redirect(url_for("views.home"))
    db = get_db()
    user = db.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
    stored = user["password_hash"] if user and user["password_hash"] else None
    if stored is None and request.method == "GET":
        return redirect(url_for("auth.setup"))        # première ouverture : mise en route
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if _too_many_attempts(db, ip):
            db.commit()
            error = "Trop de tentatives. Réessaie dans quelques minutes."
        else:
            ok = check_password_hash(stored or _DUMMY_HASH, request.form.get("password", ""))
            if ok and stored:
                sec = security_row(db, user["id"])
                if sec and sec["totp_enabled"]:
                    # Mot de passe juste : il reste le code à 6 chiffres. Pas encore connecté.
                    db.commit()
                    session.clear()
                    session["pending_user"] = user["id"]
                    session["pending_at"] = time.time()
                    csrf_token()
                    return redirect(url_for("auth.login_code"))
                db.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
                db.commit()
                _open_session(user["id"])
                return redirect(url_for("views.home"))
            _fail(db, ip)
            error = "Mot de passe incorrect."
    return render_template("login.html", error=error), (401 if error else 200)


@bp.route("/connexion/code", methods=["GET", "POST"])
def login_code():
    """Deuxième étape : code de l'appli d'authentification, ou code de secours."""
    user_id = session.get("pending_user")
    if user_id is None or time.time() - session.get("pending_at", 0) > 300:
        session.pop("pending_user", None)
        return redirect(url_for("auth.login"))
    error = None
    if request.method == "POST":
        db = get_db()
        ip = request.remote_addr or "?"
        sec = security_row(db, user_id)
        if _too_many_attempts(db, ip):
            db.commit()
            error = "Trop de tentatives. Réessaie dans quelques minutes."
        elif sec is None or not sec["totp_enabled"]:
            return redirect(url_for("auth.login"))
        else:
            code = request.form.get("code", "").strip()
            step = totp.verify(sec["totp_secret"], code, sec["totp_last_step"])
            remaining = [h for h in sec["recovery"].split(",") if h]
            used = totp.hash_recovery(code) if "-" in code else None
            if step is not None:
                db.execute("UPDATE user_security SET totp_last_step = ? WHERE user_id = ?", (step, user_id))
            elif used in remaining:
                remaining.remove(used)                 # un code de secours ne sert qu'une fois
                db.execute("UPDATE user_security SET recovery = ? WHERE user_id = ?", (",".join(remaining), user_id))
            else:
                _fail(db, ip)
                error = "Code incorrect."
            if error is None:
                db.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
                db.commit()
                _open_session(user_id)
                return redirect(url_for("views.home"))
    return render_template("login_code.html", error=error), (401 if error else 200)


@bp.route("/mise-en-route", methods=["GET", "POST"])
def setup():
    """Première ouverture : définir le mot de passe, sur présentation du code de mise en route.

    Le code est la variable BUDGET_SETUP_CODE (réglages de l'hébergeur). L'écran se ferme
    définitivement dès qu'un mot de passe existe.
    """
    db = get_db()
    user = db.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
    if user is None or user["password_hash"]:
        return redirect(url_for("auth.login"))
    expected = os.environ.get("BUDGET_SETUP_CODE", "")
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        password = request.form.get("password", "")
        if _too_many_attempts(db, ip):
            db.commit()
            error = "Trop de tentatives. Réessaie dans quelques minutes."
        elif not expected or not hmac.compare_digest(request.form.get("setup_code", "").encode(), expected.encode()):
            _fail(db, ip)
            error = "Code de mise en route incorrect."
        elif password != request.form.get("confirm", ""):
            error = "Les deux mots de passe ne sont pas identiques."
        else:
            try:
                hashed = hash_password(password)
            except ValueError as exc:
                error = str(exc)
            else:
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hashed, user["id"]))
                db.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
                db.commit()
                _open_session(user["id"])
                return redirect(url_for("admin.security"))
    return render_template("setup.html", error=error, configured=bool(expected),
                           min_len=LONGUEUR_MIN_MOT_DE_PASSE), (400 if error else 200)


@bp.route("/deconnexion", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
