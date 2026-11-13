import re
import sqlite3
import tomllib
from pathlib import Path

from budget.cli import load_modele
from conftest import PASSWORD, ROOT


def token(client, path="/connexion"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def login(client):
    t = token(client)
    r = client.post("/connexion", data={"csrf": t, "password": PASSWORD})
    assert r.status_code == 302
    return token(client, "/postes")


def seed(app):
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    data = tomllib.loads((ROOT / "config" / "modele.toml").read_text(encoding="utf-8"))
    load_modele(conn, 1, data)
    conn.close()


def q(app, sql, *args):
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return rows


def test_pages_protegees(client):
    for path in ("/", "/mois", "/postes", "/cheques", "/credits", "/mois/2026/10"):
        r = client.get(path)
        assert r.status_code == 302 and "/connexion" in r.headers["Location"]
    assert client.get("/sante").status_code == 200


def test_mauvais_mot_de_passe_et_blocage(client):
    t = token(client)
    for _ in range(5):
        r = client.post("/connexion", data={"csrf": t, "password": "faux"})
        assert r.status_code == 401
    r = client.post("/connexion", data={"csrf": t, "password": PASSWORD})
    assert r.status_code == 401 and "Trop de tentatives" in r.get_data(as_text=True)


def test_post_sans_jeton_refuse(client):
    login(client)
    assert client.post("/cheques", data={"amount": "10", "payee": "x", "year": 2026, "month": 10}).status_code == 400


def test_en_tetes_de_securite(client):
    r = client.get("/connexion")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"


def test_parcours_complet(app, client):
    seed(app)
    t = login(client)

    # Octobre vient du modèle ; on saisit le salaire et deux réels.
    page = client.get("/mois/2026/10").get_data(as_text=True)
    assert "Virements à faire" in page and "Réserve (matelas)" in page
    lines = {r["name"]: r for r in q(app, "SELECT l.id, p.name, l.planned FROM lines l JOIN postes p ON p.id = l.poste_id")}

    def save(year, month, salary, actuals):
        rows = q(app, "SELECT l.id, p.name, l.planned FROM lines l JOIN postes p ON p.id = l.poste_id "
                      "JOIN months m ON m.id = l.month_id WHERE m.year = ? AND m.month = ?", year, month)
        data = {"csrf": t, "salary_net": salary, "net_imposable": "3 300", "pas": "250"}
        for r in rows:
            data[f"planned_{r['id']}"] = str(r["planned"] / 100).replace(".", ",")
            data[f"actual_{r['id']}"] = actuals.get(r["name"], "")
        r = client.post(f"/mois/{year}/{month}", data=data)
        assert r.status_code == 302

    save(2026, 10, "3 200,00", {"Nourriture": "470", "Électricité": "110"})
    page = client.get("/mois/2026/10").get_data(as_text=True)
    assert "470,00" in page                      # reste du matelas : 500 − 70 + 40
    assert q(app, "SELECT salary_net FROM months")[0]["salary_net"] == 320000

    # Nouveau mois : copie des postes et des prévus, réel vide.
    r = client.post("/mois/nouveau", data={"csrf": t, "year": 2026, "month": 11, "salary_net": "3200"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/mois/2026/11")
    nov = q(app, "SELECT l.* FROM lines l JOIN months m ON m.id = l.month_id WHERE m.month = 11")
    assert len(nov) == len(lines) and all(r["actual"] is None for r in nov)
    assert sum(r["planned"] for r in nov) == sum(r["planned"] for r in lines.values())

    # Deuxième mois de dépassement sur la nourriture -> proposition, puis acceptation.
    save(2026, 11, "3200", {"Nourriture": "480"})
    page = client.get("/mois/2026/11").get_data(as_text=True)
    assert "Une idée pour" in page
    m = re.search(r'action="(/propositions/\d+/\d+/accepter)"', page)
    assert client.post(m.group(1), data={"csrf": t}).status_code == 302
    planned = q(app, "SELECT l.planned FROM lines l JOIN postes p ON p.id = l.poste_id JOIN months m ON m.id = l.month_id "
                     "WHERE p.name = 'Nourriture' AND m.month = 11")[0]["planned"]
    assert planned == 47500                      # médiane (470, 480) arrondie à 5 €
    assert "Une idée pour" not in client.get("/mois/2026/11").get_data(as_text=True)
    # Octobre n'est pas modifié.
    assert q(app, "SELECT l.planned FROM lines l JOIN postes p ON p.id = l.poste_id JOIN months m ON m.id = l.month_id "
                  "WHERE p.name = 'Nourriture' AND m.month = 10")[0]["planned"] == 40000

    for path in ("/mois/2026/11/analyse", "/mois/2026/11/calendrier", "/mois", "/postes", "/credits", "/cheques", "/couleurs.css"):
        assert client.get(path).status_code == 200, path
    import html
    assert "Taux d'épargne" in html.unescape(client.get("/mois/2026/11/analyse").get_data(as_text=True))


def test_cheques(app, client):
    seed(app)
    t = login(client)
    r = client.post("/cheques", data={"csrf": t, "amount": "120,50", "payee": "Plombier", "year": 2026, "month": 10, "note": "fuite"})
    assert r.status_code == 302
    assert "Plombier" in client.get("/mois/2026/10/calendrier").get_data(as_text=True)
    assert "120,50" in client.get("/mois/2026/10").get_data(as_text=True)
    cid = q(app, "SELECT id FROM cheques")[0]["id"]
    # Octobre 2026 est passé : le chèque en attente est signalé.
    assert "as-tu oublié" in client.get("/cheques").get_data(as_text=True)
    client.post(f"/cheques/{cid}/debite", data={"csrf": t})
    assert q(app, "SELECT status FROM cheques")[0]["status"] == "debited"
    assert "as-tu oublié" not in client.get("/cheques").get_data(as_text=True)


def test_postes_et_credits(app, client):
    seed(app)
    t = login(client)
    acc = q(app, "SELECT id FROM accounts WHERE name = 'Boursorama'")[0]["id"]
    r = client.post("/postes", data={"csrf": t, "name": "Gaz", "account_id": acc, "category": "besoins",
                                     "debit_day": "20", "seasonal": "on", "planned": "80"})
    assert r.status_code == 302
    assert "Gaz" in client.get("/mois/2026/10").get_data(as_text=True)
    cid = q(app, "SELECT id FROM credits WHERE name = 'Crédit renouvelable'")[0]["id"]
    for month, bal in ((9, "1000"), (10, "800")):
        client.post(f"/credits/{cid}/solde", data={"csrf": t, "year": 2026, "month": month, "balance": bal})
    page = client.get("/credits").get_data(as_text=True)
    assert "800,00" in page and "−200,00" in page


def test_montant_invalide(app, client):
    seed(app)
    t = login(client)
    r = client.post("/cheques", data={"csrf": t, "amount": "abc", "payee": "x", "year": 2026, "month": 10})
    assert r.status_code == 400


def test_cle_secrete_generee(tmp_path, monkeypatch):
    from budget import create_app
    monkeypatch.setenv("BUDGET_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BUDGET_SECRET_KEY", raising=False)
    app = create_app({"TESTING": True})
    assert len(app.config["SECRET_KEY"]) == 64
    assert (tmp_path / "secret_key").stat().st_mode & 0o777 == 0o600
    assert app.test_client().get("/connexion").status_code == 200


def test_virements_a_cocher(app, client):
    seed(app)
    t = login(client)
    data = {"csrf": t, "account": "Boursorama", "kind": "debut"}
    assert client.post("/mois/2026/10/virement", data=data).status_code == 302
    assert [tuple(r) for r in q(app, "SELECT a.name, t.kind FROM transfers_done t JOIN accounts a ON a.id = t.account_id")] == [("Boursorama", "debut")]
    assert 'aria-pressed="true"' in client.get("/mois/2026/10").get_data(as_text=True)
    # Le virement de fin de mois (reste du matelas) se coche à part.
    r = client.post("/mois/2026/10/virement", data={"csrf": t, "account": "Livret A LCL", "kind": "fin"},
                    headers={"X-Requested-With": "fetch"})
    assert r.get_json() == {"done": True}
    # Un nouveau mois repart sans rien de coché.
    client.post("/mois/nouveau", data={"csrf": t, "year": 2026, "month": 11, "salary_net": "3200"})
    assert 'aria-pressed="true"' not in client.get("/mois/2026/11").get_data(as_text=True)
    # Décocher.
    client.post("/mois/2026/10/virement", data=data)
    assert len(q(app, "SELECT * FROM transfers_done")) == 1
    assert client.post("/mois/2026/10/virement", data={"csrf": t, "account": "Inconnu"}).status_code == 400
