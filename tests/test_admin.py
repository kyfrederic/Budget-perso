"""Mise en route, second facteur, import par écran, sauvegarde et restauration."""
import io
import json
import re

import pytest

from budget import create_app, totp
from budget import db as dbmod
from conftest import PASSWORD
from test_app import login, q, seed, token
from test_importer import classeur

NOUVEAU = "un-tout-nouveau-mot-de-passe"


@pytest.fixture
def vierge(app):
    """Appli sans mot de passe, comme à la première ouverture."""
    conn = dbmod.connect(app.config["DATABASE"])
    conn.execute("UPDATE users SET password_hash = NULL")
    conn.commit(); conn.close()
    return app


def test_mise_en_route(vierge, monkeypatch):
    c = vierge.test_client()
    assert c.get("/").headers["Location"].endswith("/connexion")
    assert c.get("/connexion").headers["Location"].endswith("/mise-en-route")

    # Sans code configuré chez l'hébergeur, l'écran l'explique et refuse de créer l'accès.
    monkeypatch.setenv("BUDGET_SETUP_CODE", "code-choisi-par-fred")
    t = token(c, "/mise-en-route")
    monkeypatch.delenv("BUDGET_SETUP_CODE")
    assert "BUDGET_SETUP_CODE" in c.get("/mise-en-route").get_data(as_text=True)
    r = c.post("/mise-en-route", data={"csrf": t, "setup_code": "", "password": NOUVEAU, "confirm": NOUVEAU})
    assert r.status_code == 400 and q(vierge, "SELECT password_hash FROM users")[0]["password_hash"] is None

    monkeypatch.setenv("BUDGET_SETUP_CODE", "code-choisi-par-fred")
    data = {"csrf": t, "setup_code": "mauvais", "password": NOUVEAU, "confirm": NOUVEAU}
    assert c.post("/mise-en-route", data=data).status_code == 400            # mauvais code
    data["setup_code"] = "code-choisi-par-fred"
    assert c.post("/mise-en-route", data={**data, "password": "court", "confirm": "court"}).status_code == 400
    assert c.post("/mise-en-route", data={**data, "confirm": "autre-chose-de-long"}).status_code == 400
    r = c.post("/mise-en-route", data=data)
    assert r.status_code == 302 and r.headers["Location"].endswith("/securite")   # connecté, vers le second facteur

    # L'écran est fermé pour de bon : plus personne ne peut redéfinir le mot de passe par ce chemin.
    autre = vierge.test_client()
    assert autre.get("/mise-en-route").headers["Location"].endswith("/connexion")
    t2 = token(autre)
    r = autre.post("/mise-en-route", data={"csrf": t2, "setup_code": "code-choisi-par-fred", "password": "x" * 20, "confirm": "x" * 20})
    assert r.status_code == 302
    assert autre.post("/connexion", data={"csrf": t2, "password": NOUVEAU}).status_code == 302   # le bon mot de passe marche


def test_totp_rfc6238():
    # Vecteur de test de la RFC 6238 (SHA-1, secret « 12345678901234567890 »), tronqué à 6 chiffres.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp.code_at(secret, 59) == "287082"
    assert totp.code_at(secret, 1111111109) == "081804"
    step = totp.verify(secret, "287082", when=59)
    assert step == 1
    assert totp.verify(secret, "287082", last_step=step, when=59) is None      # pas de rejeu
    assert totp.verify(secret, "287082", when=65) == 1                         # pas suivant : 30 s de tolérance
    assert totp.verify(secret, "287082", when=59 + 120) is None
    assert totp.verify(secret, "abc", when=59) is None


def activer(app, client, t):
    client.post("/securite", data={"csrf": t, "action": "start"})
    secret = q(app, "SELECT totp_secret FROM user_security")[0]["totp_secret"]
    page = client.get("/securite").get_data(as_text=True)
    assert "<svg" in page and secret in page
    assert client.post("/securite", data={"csrf": t, "action": "confirm", "code": "000000"}).status_code == 302
    assert q(app, "SELECT totp_enabled FROM user_security")[0]["totp_enabled"] == 0   # mauvais code : pas activé
    r = client.post("/securite", data={"csrf": t, "action": "confirm", "code": totp.code_at(secret)})
    codes = re.findall(r"<code>([0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4})</code>", r.get_data(as_text=True))
    assert len(codes) == 8
    return secret, codes


def test_second_facteur(app, client):
    t = login(client)
    secret, codes = activer(app, client, t)
    # Les codes de secours ne sont gardés que sous forme d'empreintes.
    assert codes[0] not in q(app, "SELECT recovery FROM user_security")[0]["recovery"]

    c = app.test_client()
    t = token(c)
    r = c.post("/connexion", data={"csrf": t, "password": PASSWORD})
    assert r.headers["Location"].endswith("/connexion/code")
    assert c.get("/mois").headers["Location"].endswith("/connexion")           # mot de passe seul : pas connecté
    t = token(c, "/connexion/code")
    assert c.post("/connexion/code", data={"csrf": t, "code": "123456"}).status_code == 401
    import time
    bon = totp.code_at(secret, time.time() + 30)        # pas suivant : celui de l'activation est déjà consommé
    assert c.post("/connexion/code", data={"csrf": t, "code": bon}).status_code == 302
    assert c.get("/mois").status_code == 200

    # Le même code ne peut pas resservir.
    c2 = app.test_client()
    t2 = token(c2)
    c2.post("/connexion", data={"csrf": t2, "password": PASSWORD})
    t2 = token(c2, "/connexion/code")
    assert c2.post("/connexion/code", data={"csrf": t2, "code": bon}).status_code == 401
    # Un code de secours ouvre la session, une seule fois.
    assert c2.post("/connexion/code", data={"csrf": t2, "code": codes[0]}).status_code == 302
    c3 = app.test_client()
    t3 = token(c3)
    c3.post("/connexion", data={"csrf": t3, "password": PASSWORD})
    t3 = token(c3, "/connexion/code")
    assert c3.post("/connexion/code", data={"csrf": t3, "code": codes[0]}).status_code == 401

    # Désactiver exige le mot de passe et un code valide.
    t = token(c, "/securite")
    assert c.post("/securite", data={"csrf": t, "action": "disable", "password": "faux", "code": "1"}).status_code == 400
    assert q(app, "SELECT totp_enabled FROM user_security")[0]["totp_enabled"] == 1


def test_code_sans_mot_de_passe(app, client):
    """On n'arrive pas à l'étape du code sans avoir passé celle du mot de passe."""
    assert client.get("/connexion/code").headers["Location"].endswith("/connexion")


def fichiers(tmp_path):
    classeur(tmp_path / "OCTOBRE_SOLO.xlsx", 3000, 100, renouvelable=700)
    classeur(tmp_path / "NOVEMBRE_SOLO.xlsx", 3200, 130, renouvelable=500)
    return [(io.BytesIO((tmp_path / n).read_bytes()), n) for n in ("OCTOBRE_SOLO.xlsx", "NOVEMBRE_SOLO.xlsx")]


def test_import_par_ecran(app, client, tmp_path):
    t = login(client)
    r = client.post("/import", data={"csrf": t, "action": "upload", "year": 2026, "files": fichiers(tmp_path)},
                    content_type="multipart/form-data")
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "Mois lus" in page and "novembre" in page and "Emprunt immobilier" in page
    assert q(app, "SELECT COUNT(*) n FROM months")[0]["n"] == 0            # aperçu : rien d'enregistré
    r = client.post("/import", data={"csrf": t, "action": "confirm", "year": 2026})
    assert r.status_code == 302
    rows = q(app, "SELECT month, salary_net FROM months ORDER BY month")
    assert [tuple(x) for x in rows] == [(10, 300000), (11, 320000)]
    assert q(app, "SELECT COUNT(*) n FROM import_files")[0]["n"] == 0      # fichiers déposés effacés
    assert client.get("/mois/2026/11").status_code == 200
    # Budget non vide : l'import est fermé.
    assert "ne se fait que sur un budget vide" in client.get("/import").get_data(as_text=True)


def test_import_refuse_ce_qui_n_est_pas_excel(app, client):
    t = login(client)
    r = client.post("/import", data={"csrf": t, "action": "upload", "year": 2026, "files": [(io.BytesIO(b"bonjour"), "MARS_SOLO.xlsx")]},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post("/import", data={"csrf": t, "action": "upload", "year": 2026, "files": [(io.BytesIO(b"PK"), "../x.exe")]},
                    content_type="multipart/form-data")
    assert r.status_code == 400


def test_sauvegarde_et_restauration(app, client):
    seed(app)
    t = login(client)
    client.post("/mois/2026/10/achat", data={"csrf": t, "label": "Resto", "amount": "62", "target": "matelas"})
    client.post("/mois/2026/10/virement", data={"csrf": t, "account": "Revolut", "kind": "debut"})
    r = client.get("/sauvegarde")
    assert "attachment" in r.headers["Content-Disposition"]
    dump = json.loads(r.get_data(as_text=True))
    assert len(dump["tables"]["postes"]) == 13 and dump["tables"]["purchases"][0]["label"] == "Resto"
    assert "users" not in dump["tables"] and "password" not in r.get_data(as_text=True)

    avant = {tbl: q(app, f"SELECT COUNT(*) n FROM {tbl}")[0]["n"] for tbl in ("postes", "lines", "purchases", "transfers_done")}
    client.post("/mois/2026/10/achat", data={"csrf": t, "label": "Après la sauvegarde", "amount": "10", "target": "matelas"})

    envoi = lambda mdp, contenu: client.post("/restaurer", content_type="multipart/form-data", data={
        "csrf": t, "password": mdp, "file": (io.BytesIO(contenu), "s.json")})
    brut = json.dumps(dump).encode()
    assert envoi("mauvais", brut).status_code == 400
    assert envoi(PASSWORD, b"{}").status_code == 400
    assert q(app, "SELECT COUNT(*) n FROM purchases")[0]["n"] == 2          # refus : rien n'a bougé
    assert envoi(PASSWORD, brut).status_code == 302
    assert {tbl: q(app, f"SELECT COUNT(*) n FROM {tbl}")[0]["n"] for tbl in avant} == avant
    assert client.get("/mois/2026/10").status_code == 200
    # Après restauration on peut encore créer des lignes (compteurs d'identifiants recalés).
    assert client.post("/mois/2026/10/achat", data={"csrf": t, "label": "Suite", "amount": "5", "target": "matelas"}).status_code == 302
    assert client.post("/mois/nouveau", data={"csrf": t, "year": 2026, "month": 11, "salary_net": "3000"}).status_code == 302
