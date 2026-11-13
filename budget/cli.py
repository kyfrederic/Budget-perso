"""Commandes d'administration : flask --app budget <commande>."""
from __future__ import annotations

import getpass
import sqlite3
import tomllib
from datetime import datetime
from pathlib import Path

import click
from flask import current_app

from . import db as dbmod
from .auth import hash_password
from .money import euros_to_cents, month_label


def _conn() -> sqlite3.Connection:
    return dbmod.connect(current_app.config["DATABASE"])


def register(app) -> None:
    @app.cli.command("set-password")
    def set_password():
        """Définit (ou change) le mot de passe de connexion."""
        pw = getpass.getpass("Nouveau mot de passe : ")
        if pw != getpass.getpass("Confirmation : "):
            raise click.ClickException("Les deux saisies ne correspondent pas.")
        try:
            h = hash_password(pw)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        conn = _conn()
        uid = dbmod.ensure_user(conn)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (h, uid))
        conn.commit()
        click.echo("Mot de passe enregistré.")

    @app.cli.command("charger-modele")
    @click.option("--fichier", default=None, help="Chemin du modèle TOML (défaut : config/modele.toml).")
    def charger_modele(fichier):
        """Charge le modèle de départ (postes, premier mois, crédits). Une seule fois."""
        path = Path(fichier or current_app.config["MODELE_FILE"])
        with open(path, "rb") as f:
            data = tomllib.load(f)
        conn = _conn()
        uid = dbmod.ensure_user(conn)
        try:
            n = load_modele(conn, uid, data)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"{n} postes chargés depuis {path}.")

    @app.cli.command("backup")
    @click.argument("destination", type=click.Path())
    def backup(destination):
        """Écrit une copie cohérente de la base dans DESTINATION (dossier ou fichier)."""
        dest = Path(destination)
        if dest.is_dir():
            dest = dest / f"budget-{datetime.now():%Y%m%d-%H%M%S}.sqlite"
        dbmod.backup_to(current_app.config["DATABASE"], str(dest))
        check = sqlite3.connect(dest)
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
        check.close()
        if ok != "ok":
            raise click.ClickException(f"Copie corrompue : {ok}")
        click.echo(str(dest))

    @app.cli.command("verifier-sauvegarde")
    @click.argument("fichier", type=click.Path(exists=True))
    def verifier(fichier):
        """Test de restauration : ouvre une sauvegarde et vérifie son contenu."""
        conn = sqlite3.connect(fichier)
        conn.row_factory = sqlite3.Row
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise click.ClickException(f"Sauvegarde corrompue : {ok}")
        n_mois = conn.execute("SELECT COUNT(*) FROM months").fetchone()[0]
        n_lignes = conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
        last = conn.execute("SELECT year, month FROM months ORDER BY year DESC, month DESC LIMIT 1").fetchone()
        dernier = month_label(last["year"], last["month"]) if last else "aucun"
        click.echo(f"Sauvegarde lisible : {n_mois} mois, {n_lignes} lignes, dernier mois : {dernier}.")


def load_modele(conn: sqlite3.Connection, user_id: int, data: dict) -> int:
    """Insère les postes, le mois de départ et les crédits du modèle."""
    if conn.execute("SELECT COUNT(*) FROM postes WHERE user_id = ?", (user_id,)).fetchone()[0]:
        raise ValueError("Des postes existent déjà : le modèle ne se charge qu'une fois.")
    accounts = {
        r["name"]: r["id"]
        for r in conn.execute("SELECT id, name FROM accounts WHERE user_id = ?", (user_id,))
    }
    postes = data.get("postes", [])
    if sum(1 for p in postes if p.get("reserve")) > 1:
        raise ValueError("Un seul poste peut être marqué « reserve ».")
    partner: dict[int, int] = {}
    for i, p in enumerate(postes):
        if p["compte"] not in accounts:
            raise ValueError(f"Poste « {p['nom']} » : compte inconnu « {p['compte']} » (voir settings.toml).")
        cur = conn.execute(
            "INSERT INTO postes (user_id, name, account_id, category, debit_day, seasonal, contractual, "
            "is_reserve, default_planned, sort) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, p["nom"], accounts[p["compte"]], p.get("categorie", "besoins"), p.get("jour"),
             int(p.get("saisonnier", False)), int(p.get("contractuel", False)),
             int(p.get("reserve", False)), euros_to_cents(p.get("montant", 0)), i),
        )
        if "part_laetitia" in p:
            partner[cur.lastrowid] = euros_to_cents(p["part_laetitia"])
    md = data.get("mois_depart")
    if md:
        from .store import create_month

        def val(key):
            v = md.get(key, 0)
            return euros_to_cents(v) if v else None
        mid = create_month(conn, user_id, int(md["annee"]), int(md["mois"]),
                           val("salaire_net"), val("net_imposable"), val("prelevement_source"))
        for poste_id, cents in partner.items():
            conn.execute(
                "UPDATE lines SET info_partner = ? WHERE month_id = ? AND poste_id = ?",
                (cents, mid, poste_id),
            )
    for c in data.get("credits", []):
        conn.execute(
            "INSERT OR IGNORE INTO credits (user_id, name, target_date) VALUES (?, ?, ?)",
            (user_id, c["nom"], c.get("objectif")),
        )
    conn.commit()
    return len(postes)
