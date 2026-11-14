"""Import Excel, testé sur des classeurs fabriqués ici (montants fictifs)."""
import sqlite3

import openpyxl
import pytest

from budget import importer


def classeur(path, salaire, electricite, total=None, renouvelable=500, ancien_nom=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Gestion du budget du mois"
    ws["N1"] = salaire
    rows = {
        4: ("Crédit", "Emprunt immobilier", 600, 400),
        9: ("Dépenses fixes", "Nourriture", 300, 0),
        10: (None, "Electricité", electricite, 0),
        11: (None, "Eaux", 0, 0),                      # à 0 : ignoré
        30: ("Charges fixes", "Carburant", 50, None),
        35: ("Conforts", "Abonnement chatGPT" if ancien_nom else "Abonnement chatGPT/claude", 20, None),
        40: (None, "Argent de poche (Revolut)", 200, None),
        43: ("Crédits", "Reserve", 500, None),
        45: (None, "prêt conso", 100, None),
        46: ("Epargne", "Livret A", 80, None),
    }
    for r, (grp, name, fred, laet) in rows.items():
        ws.cell(r, 2, grp); ws.cell(r, 3, name); ws.cell(r, 4, fred); ws.cell(r, 7, laet)
    ws["D23"] = 9999                                   # ligne de total : hors des lignes lues
    ws["E65"] = total if total is not None else 1850 + electricite

    c = wb.create_sheet("50-30-20")
    c["A2"] = "CHARGE FIXE"
    for i, n in enumerate(["Emprunt immobilier", "Nourriture", "Electricité", "Carburant"]):
        c.cell(2 + i, 2, n)
    c["A23"] = "ENVIES"
    for i, n in enumerate(["Argent de poche (Revolut)", "Abonnement chatGPT/claude"]):
        c.cell(23 + i, 2, n)
    c["B45"] = "prêt conso"
    c["A46"] = "EPARGNE"; c["B46"] = "Livret A"

    d = wb.create_sheet("Depences personnelles")
    d["C7"] = "Compte LCL"
    for i, (n, v) in enumerate([("Carburant", 50), ("Livret A", 80), ("Emprunt immobilier", 600)]):
        d.cell(8 + i, 3, n); d.cell(8 + i, 4, v)
    d["C11"] = "TOTAL"; d["D11"] = 730
    d["G7"] = "Bourso perso "
    for i, (n, v) in enumerate([("Electricité", electricite), ("prêt conso", 100), ("Reserve", 500),
                                ("Abonnement chatGPT/claude", 20)]):
        d.cell(8 + i, 7, n); d.cell(8 + i, 8, v)
    d["K7"] = "Compte Revolut"; d["K8"] = "Argent de poche (Revolut)"; d["L8"] = 200
    d["K11"] = "TOTAL"; d["L11"] = 200
    d["K17"] = "Bourso joint"; d["K18"] = "Nourriture"; d["L18"] = 300

    k = wb.create_sheet("Crédit")
    k.append(["Compte", "Montant dispo", "total à rembourser", "Montant réellement dû"])
    k.append(["Decouvert", 0, 0, 0])
    k.append(["Crédit rénouvelable", 0, 1000, renouvelable, "Objectif : Remboursement total grand max 31/12/2026"])
    k.append(["TOTAL", 0, 1000, renouvelable])
    wb.save(path)


CONFIG = {
    "compte_reserve": "N26", "compte_defaut": "LCL",
    "comptes": {"Compte LCL": "LCL", "Bourso perso": "Boursorama", "Compte Revolut": "Revolut",
                "Bourso joint": "Compte joint"},
    "alias": {"Abonnement chatGPT": "Abonnement chatGPT/claude"},
    "categories": {"prêt conso": "besoins"},
    "comptes_postes": {"Livret A": "Livret A LCL"},
}
COMPTES = {"LCL", "Boursorama", "Revolut", "Compte joint", "N26", "Livret A LCL"}


@pytest.fixture
def dossier(tmp_path):
    classeur(tmp_path / "OCTOBRE_SOLO.xlsx", 3000, 100, renouvelable=700, ancien_nom=True)
    classeur(tmp_path / "NOVEMBRE_SOLO.xlsx", 3200, 130, renouvelable=500)
    return tmp_path


def test_lecture(dossier):
    months = importer.read_folder(dossier, 2026, CONFIG)
    assert [(m.month, m.salary, m.total) for m in months] == [(10, 300000, 195000), (11, 320000, 198000)]
    assert "Eaux" not in [p.name for p in months[0].postes]
    assert months[0].credits == {"Decouvert": 0, "Crédit rénouvelable": 70000}
    assert months[1].targets == {"Crédit rénouvelable": "2026-12-31"}
    emprunt = next(p for p in months[1].postes if p.name == "Emprunt immobilier")
    assert emprunt.partner == 40000


def test_fiches_des_postes(dossier):
    months = importer.read_folder(dossier, 2026, CONFIG)
    postes = {s.name: s for s in importer.build_postes(months, CONFIG, COMPTES).values()}
    assert postes["Reserve"].is_reserve and postes["Reserve"].account == "N26"        # décision de Fred
    assert postes["Livret A"].account == "Livret A LCL" and postes["Livret A"].category == "epargne"
    assert postes["prêt conso"].category == "besoins" and postes["prêt conso"].contractual
    assert postes["Nourriture"].account == "Compte joint" and postes["Nourriture"].category == "besoins"
    assert postes["Argent de poche (Revolut)"].category == "envies"
    assert postes["Electricité"].seasonal and postes["Electricité"].account == "Boursorama"
    # L'ancien nom d'octobre est rattaché au poste actuel : un seul poste.
    assert "Abonnement chatGPT" not in postes and len(postes) == 9


def test_total_incoherent(tmp_path):
    classeur(tmp_path / "MARS_SOLO.xlsx", 3000, 100, total=5000)
    with pytest.raises(ValueError, match="E65"):
        importer.read_folder(tmp_path, 2026, CONFIG)


def test_nom_de_fichier(tmp_path):
    classeur(tmp_path / "BUDGET_SOLO.xlsx", 3000, 100)
    with pytest.raises(ValueError, match="mois"):
        importer.read_folder(tmp_path, 2026, CONFIG)


def test_ecriture_en_base(app, dossier):
    months = importer.read_folder(dossier, 2026, CONFIG)
    postes = importer.build_postes(months, CONFIG, COMPTES)
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    importer.apply(conn, 1, months, postes)
    rows = conn.execute("SELECT year, month, salary_net, (SELECT SUM(planned) FROM lines WHERE month_id = months.id) AS t "
                        "FROM months ORDER BY month").fetchall()
    assert [tuple(r) for r in rows] == [(2026, 10, 300000, 195000), (2026, 11, 320000, 198000)]
    assert conn.execute("SELECT COUNT(*) FROM lines WHERE actual IS NOT NULL").fetchone()[0] == 0
    # Seul le crédit qui a été dû est créé, avec son objectif et ses deux soldes.
    credits = conn.execute("SELECT name, target_date FROM credits").fetchall()
    assert [tuple(c) for c in credits] == [("Crédit rénouvelable", "2026-12-31")]
    assert [r[0] for r in conn.execute("SELECT balance FROM credit_balances ORDER BY month")] == [70000, 50000]
    with pytest.raises(ValueError, match="base vide"):
        importer.apply(conn, 1, months, postes)
