"""Réglages faits depuis l'appli : second facteur, import des fichiers Excel, sauvegarde.

Ces écrans remplacent les commandes `flask …` là où aucune commande ne peut être lancée (Vercel).
"""
from __future__ import annotations

import io
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

from . import importer, totp
from .auth import security_row
from .db import get_db

bp = Blueprint("admin", __name__)

# Tables sauvegardées, dans l'ordre où elles se recréent (les parents d'abord).
# Les identifiants de connexion ne sont ni exportés ni écrasés : une restauration ne peut pas t'enfermer dehors.
BACKUP_TABLES = ["accounts", "postes", "months", "lines", "cheques", "credits", "credit_balances",
                 "proposal_decisions", "transfers_done", "purchases"]
NAME = re.compile(r"[a-z_]+")
MAX_FILES, MAX_FILE_BYTES = 24, 2 * 1024 * 1024


def _check_password() -> None:
    row = get_db().execute("SELECT password_hash FROM users WHERE id = ?", (g.user_id,)).fetchone()
    if not check_password_hash(row["password_hash"] or "", request.form.get("password", "")):
        abort(400, "Mot de passe incorrect.")


def _has_data(db) -> bool:
    return db.execute("SELECT COUNT(*) FROM postes WHERE user_id = ?", (g.user_id,)).fetchone()[0] > 0


@bp.route("/reglages")
def settings_home():
    db = get_db()
    sec = security_row(db, g.user_id)
    return render_template(
        "settings.html", totp_on=bool(sec and sec["totp_enabled"]), has_data=_has_data(db),
        recovery_left=len([h for h in (sec["recovery"] if sec else "").split(",") if h]),
        n_photos=db.execute("SELECT COUNT(*) FROM ticket_photos").fetchone()[0],
    )


# ---------------------------------------------------------------- second facteur


def _qr_svg(text: str) -> str:
    import segno

    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=5, border=2, xmldecl=False, svgns=True,
                                     dark="#22301F", light="#FFFFFF")
    return out.getvalue().decode()


@bp.route("/securite", methods=["GET", "POST"])
def security():
    db = get_db()
    sec = security_row(db, g.user_id)
    enabled = bool(sec and sec["totp_enabled"])
    if request.method == "POST":
        action = request.form.get("action")
        if action == "start" and not enabled:
            secret = totp.new_secret()
            db.execute(
                "INSERT INTO user_security (user_id, totp_secret) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET totp_secret = excluded.totp_secret, totp_enabled = 0",
                (g.user_id, secret),
            )
            db.commit()
        elif action == "confirm" and sec and not enabled:
            step = totp.verify(sec["totp_secret"], request.form.get("code", ""))
            if step is None:
                flash("Code incorrect : vérifie l'heure de ton téléphone et réessaie.")
            else:
                codes = totp.new_recovery_codes()
                db.execute(
                    "UPDATE user_security SET totp_enabled = 1, totp_last_step = ?, recovery = ? WHERE user_id = ?",
                    (step, ",".join(totp.hash_recovery(c) for c in codes), g.user_id),
                )
                db.commit()
                # Affichés une seule fois : seules leurs empreintes sont gardées.
                return render_template("security.html", enabled=True, new_codes=codes)
        elif action == "disable" and enabled:
            _check_password()
            if totp.verify(sec["totp_secret"], request.form.get("code", ""), sec["totp_last_step"]) is None:
                abort(400, "Code incorrect.")
            db.execute("DELETE FROM user_security WHERE user_id = ?", (g.user_id,))
            db.commit()
            flash("Second facteur désactivé.")
        return redirect(url_for("admin.security"))
    pending = sec["totp_secret"] if sec and not enabled and sec["totp_secret"] else None
    return render_template(
        "security.html", enabled=enabled, pending=pending,
        qr=_qr_svg(totp.uri(pending)) if pending else None,
        recovery_left=len([h for h in (sec["recovery"] if sec else "").split(",") if h]),
    )


# ------------------------------------------------------------------ import Excel


def _stored_files(db) -> list:
    return db.execute("SELECT name, data FROM import_files ORDER BY name").fetchall()


def _read_stored(db, year: int):
    """Relit les fichiers déposés et prépare l'import (sans rien écrire dans le budget)."""
    config = importer.load_config(current_app.config["SETTINGS_FILE"])
    settings = current_app.config["SETTINGS"]
    with tempfile.TemporaryDirectory() as tmp:
        for f in _stored_files(db):
            (Path(tmp) / f["name"]).write_bytes(bytes(f["data"]))
        months = importer.read_folder(tmp, year, config)
    postes = importer.build_postes(months, config, {c.nom for c in settings.comptes})
    return months, postes


@bp.route("/import", methods=["GET", "POST"])
def import_excel():
    db = get_db()
    if _has_data(db):
        return render_template("import.html", blocked=True)
    error = report = None
    year = request.form.get("year", type=int) or session.get("import_year") or datetime.now().year
    if request.method == "POST":
        action = request.form.get("action")
        if action == "upload":
            files = [f for f in request.files.getlist("files") if f.filename]
            if not files or len(files) > MAX_FILES:
                abort(400, "Choisis entre 1 et 24 fichiers .xlsx.")
            db.execute("DELETE FROM import_files")
            for f in files:
                name = Path(f.filename).name
                data = f.read(MAX_FILE_BYTES + 1)
                if not re.fullmatch(r"[\w .\-]+\.xlsx", name) or len(data) > MAX_FILE_BYTES or data[:2] != b"PK":
                    abort(400, f"« {name} » n'est pas un fichier Excel .xlsx acceptable (2 Mo au plus).")
                db.execute("INSERT INTO import_files (name, data) VALUES (?, ?) "
                           "ON CONFLICT(name) DO UPDATE SET data = excluded.data", (name, data))
            db.commit()
            session["import_year"] = year
        elif action == "cancel":
            db.execute("DELETE FROM import_files")
            db.commit()
            return redirect(url_for("admin.import_excel"))
        elif action == "confirm":
            try:
                months, postes = _read_stored(db, year)
                importer.apply(db, g.user_id, months, postes)
            except ValueError as exc:
                db.rollback()
                abort(400, str(exc))
            db.execute("DELETE FROM import_files")
            db.commit()
            flash(f"Import terminé : {len(months)} mois, {len(postes)} postes.")
            return redirect(url_for("views.home"))
    stored = _stored_files(db)
    if stored:
        try:
            months, postes = _read_stored(db, year)
            report = importer.report(months, postes)
        except ValueError as exc:
            error = str(exc)
        except Exception:                      # classeur illisible ou d'une autre structure
            error = "Un des fichiers n'a pas pu être lu. Vérifie que ce sont bien tes fichiers MOIS_SOLO.xlsx."
    return render_template("import.html", blocked=False, stored=[f["name"] for f in stored],
                           report=report, error=error, year=year)


# --------------------------------------------------------------------- sauvegarde


@bp.route("/sauvegarde")
def backup():
    """Télécharge toutes les données du budget dans un fichier JSON (sans les photos des tickets)."""
    db = get_db()
    dump = {"format": "budget-sauvegarde", "version": 1, "date": datetime.now().isoformat(timespec="seconds"),
            "tables": {}}
    for table in BACKUP_TABLES:
        rows = db.execute(f"SELECT * FROM {table}").fetchall()
        dump["tables"][table] = [{k: r[k] for k in r.keys()} for r in rows]
    body = json.dumps(dump, ensure_ascii=False, indent=1)
    name = f"budget-sauvegarde-{datetime.now():%Y-%m-%d}.json"
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.route("/restaurer", methods=["POST"])
def restore():
    """Remplace toutes les données du budget par celles d'une sauvegarde. Mot de passe exigé."""
    _check_password()
    f = request.files.get("file")
    try:
        dump = json.loads(f.read(4 * 1024 * 1024).decode("utf-8")) if f else None
    except (ValueError, UnicodeDecodeError):
        dump = None
    if not isinstance(dump, dict) or dump.get("format") != "budget-sauvegarde" or not isinstance(dump.get("tables"), dict):
        abort(400, "Ce fichier n'est pas une sauvegarde de l'appli.")
    tables = dump["tables"]
    db = get_db()
    try:
        for table in reversed(BACKUP_TABLES):
            db.execute(f"DELETE FROM {table}")
        for table in BACKUP_TABLES:
            for row in tables.get(table, []):
                cols = list(row)
                if not cols or not all(NAME.fullmatch(c) for c in cols):
                    raise ValueError("colonne inattendue")
                if "user_id" in row:
                    row["user_id"] = g.user_id
                if table == "purchases":
                    row["photo"] = None             # les photos ne sont pas dans la sauvegarde
                db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                           [row[c] for c in cols])
        if db.postgres:
            # Les identifiants ont été repris tels quels : on recale les compteurs.
            for table in BACKUP_TABLES:
                if table not in ("credit_balances", "transfers_done"):
                    db.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                               f"COALESCE((SELECT MAX(id) FROM {table}), 1))")
        db.execute("DELETE FROM ticket_photos")
        db.commit()
    except Exception:
        db.rollback()                               # tout ou rien : les données d'avant restent en place
        abort(400, "La sauvegarde n'a pas pu être restaurée : rien n'a été modifié.")
    flash(f"Sauvegarde du {str(dump.get('date', ''))[:10]} restaurée.")
    return redirect(url_for("views.home"))
