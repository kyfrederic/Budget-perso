from budget.money import format_eur, month_index, parse_amount
from budget.rules import (Line, Month, Unplanned, analysis_notes, compute_proposals, credit_status, round_to,
                          seasonal_alerts, split_503020, summarize)


def E(x):
    return int(round(x * 100))


def mois(salary=3000, **actuals):
    lines = [
        Line(1, "Emprunt", "LCL", E(900), contractual=True),
        Line(2, "Nourriture", "Compte joint", E(400)),
        Line(3, "Électricité", "Boursorama", E(150), seasonal=True),
        Line(4, "Abonnements", "Boursorama", E(60), category="envies"),
        Line(5, "Argent de poche", "Revolut", E(200), category="envies"),
        Line(6, "Épargne programmée", "Livret A LCL", E(200), category="epargne"),
        Line(7, "Réserve", "N26", E(500), is_reserve=True),
    ]
    by = {l.name: l for l in lines}
    for name, val in actuals.items():
        by[name.replace("_", " ")].actual = E(val)
    return Month(2026, 10, E(salary) if salary is not None else None, lines)


# ------------------------------------------------------------- montants

def test_parse_amount():
    assert parse_amount("1 234,56") == 123456
    assert parse_amount("1234.5") == 123450
    assert parse_amount("1.234,56 €") == 123456
    assert parse_amount("") is None
    assert format_eur(123456) == "1 234,56 €"
    assert format_eur(-500) == "−5,00 €"


# -------------------------------------------------------------- matelas

def test_epargne_sans_reel(settings):
    s = summarize(mois(), settings)
    assert s.total_budget == E(2410)
    assert s.epargne_debut == E(590)
    assert s.matelas_rest == E(500)          # rien de saisi : matelas intact
    # Le matelas est une dépense : l'épargne du mois n'est que salaire − budget…
    assert s.epargne_mois == E(590)
    # …jusqu'à ce que son reste soit viré au Livret A (virement de fin de mois coché).
    m = mois()
    m.matelas_saved = True
    assert summarize(m, settings).epargne_mois == E(590 + 500)


def test_depassement_pris_dans_le_matelas(settings):
    s = summarize(mois(Nourriture=470), settings)
    assert s.overruns == E(70)
    assert s.matelas_rest == E(430)
    assert s.to_savings_end == E(430)
    assert s.deficit == 0


def test_les_economies_compensent(settings):
    # Décision de Fred : reste = 500 − dépassements + économies.
    s = summarize(mois(Nourriture=470, Électricité=110), settings)
    assert s.overruns == E(70) and s.savings == E(40)
    assert s.matelas_rest == E(470)
    assert s.epargne_mois == E(590)                       # reste pas encore viré


def test_alerte_quand_le_matelas_ne_suffit_plus(settings):
    s = summarize(mois(Nourriture=1000), settings)
    assert s.matelas_rest == E(-100)
    assert s.deficit == E(100)
    assert s.to_savings_end == 0             # s'il ne reste rien, rien n'est viré
    assert s.epargne_mois == E(590)


def test_sans_salaire(settings):
    s = summarize(mois(salary=None), settings)
    assert s.epargne_debut is None and s.epargne_mois is None and s.taux_epargne is None


def test_virements_par_compte(settings):
    v = {x.account: x for x in summarize(mois(), settings).virements}
    assert v["Boursorama"].amount == E(210)          # électricité + abonnements
    assert v["Compte joint"].amount == E(400)
    assert v["Revolut"].amount == E(200)
    assert v["N26"].amount == E(500)
    assert v["LCL"].kind == "reste" and v["LCL"].amount == E(900)
    # Livret A : épargne programmée + (salaire − budget)
    assert v["Livret A LCL"].amount == E(200 + 590)
    # Tout le salaire est réparti.
    assert sum(x.amount for x in v.values()) == E(3000)


def test_503020(settings):
    m = mois()
    split = {s["key"]: s for s in split_503020(m, summarize(m, settings), settings)}
    # Budget du mois, matelas exclu : 1 450 + 260 + 200 = 1 910 €.
    assert split["besoins"]["amount"] == E(1450)
    assert split["envies"]["amount"] == E(260)
    assert split["epargne"]["amount"] == E(200)          # ni le salaire − budget, ni le matelas
    assert round(split["besoins"]["pct"], 1) == round(1450 / 1910 * 100, 1)
    assert round(sum(s["pct"] for s in split.values())) == 100


def test_503020_matelas_selon_usage(settings):
    m = mois(Nourriture=470)                              # dépassement de 70 € sur un besoin
    m.unplanned = [Unplanned("Resto", E(60)), Unplanned("Facture eau", E(40), "besoins")]
    m.matelas_saved = True                                # reste viré au Livret A
    s = summarize(m, settings)
    assert s.to_savings_end == E(500 - 70 - 100)
    split = {x["key"]: x for x in split_503020(m, s, settings)}
    assert split["besoins"]["amount"] == E(1450 + 70 + 40)
    assert split["envies"]["amount"] == E(260 + 60)
    assert split["epargne"]["amount"] == E(200 + 330)
    assert round(sum(x["pct"] for x in split.values())) == 100


def test_poste_non_saisi_vaut_son_prevu(settings):
    m = mois(Nourriture=470)
    by = {l.name: l for l in m.lines}
    assert by["Navigo" if "Navigo" in by else "Abonnements"].effective == by["Abonnements"].planned
    assert by["Nourriture"].effective == E(470)


# --------------------------------------------------------- propositions

OCT = month_index(2026, 10)


def props(history, settings, decided=frozenset(), current=None):
    return compute_proposals(current or mois(), history, set(decided), settings)


def test_pas_de_proposition_avant_deux_mois(settings):
    assert props({2: [(OCT, E(400), E(480))]}, settings) == []


def test_hausse_apres_deux_mois_de_suite(settings):
    p = props({2: [(OCT - 1, E(400), E(470)), (OCT, E(400), E(482))]}, settings)
    assert len(p) == 1
    assert p[0].direction == "hausse" and p[0].current == E(400)
    assert p[0].proposed == E(475)           # médiane (470, 482) = 476 -> arrondi à 5 €


def test_mediane_des_trois_derniers_mois(settings):
    h = {2: [(OCT - 2, E(400), E(405)), (OCT - 1, E(400), E(460)), (OCT, E(400), E(520))]}
    assert props(h, settings)[0].proposed == E(460)


def test_seuils_dix_pourcent_et_dix_euros(settings):
    # +8 € sur 60 € : plus de 10 % mais moins de 10 € -> rien.
    assert props({4: [(OCT - 1, E(60), E(68)), (OCT, E(60), E(68))]}, settings) == []
    # +30 € sur 400 € : plus de 10 € mais moins de 10 % -> rien.
    assert props({2: [(OCT - 1, E(400), E(430)), (OCT, E(400), E(430))]}, settings) == []


def test_mois_non_consecutifs(settings):
    assert props({2: [(OCT - 2, E(400), E(480)), (OCT, E(400), E(480))]}, settings) == []


def test_un_seul_mois_au_dessus_ne_suffit_pas(settings):
    assert props({2: [(OCT - 1, E(400), E(400)), (OCT, E(400), E(480))]}, settings) == []


def test_contractuel_exclu(settings):
    assert props({1: [(OCT - 1, E(900), E(1100)), (OCT, E(900), E(1100))]}, settings) == []


def test_baisse_pour_un_poste_normal(settings):
    p = props({5: [(OCT - 1, E(200), E(150)), (OCT, E(200), E(140))]}, settings)
    assert p[0].direction == "baisse" and p[0].proposed == E(145)


def test_pas_de_baisse_pour_un_saisonnier(settings):
    assert props({3: [(OCT - 1, E(150), E(90)), (OCT, E(150), E(95))]}, settings) == []


def test_hausse_possible_pour_un_saisonnier(settings):
    p = props({3: [(OCT - 1, E(150), E(210)), (OCT, E(150), E(230))]}, settings)
    assert p[0].direction == "hausse" and p[0].proposed == E(220)


def test_proposition_deja_decidee(settings):
    h = {2: [(OCT - 1, E(400), E(470)), (OCT, E(400), E(480))]}
    assert props(h, settings, decided={(2, OCT)}) == []


def test_round_to():
    assert round_to(47600, 500) == 47500
    assert round_to(47800, 500) == 48000
    assert round_to(47750, 500) == 48000


# ---------------------------------------------------------- saisonnalité

def test_alerte_avant_la_saison_forte(settings):
    m = mois()                                # octobre, saison forte à partir de novembre
    a = seasonal_alerts(m, {}, settings)
    assert len(a) == 1 and "Électricité" in a[0]["text"] and a[0]["level"] == "info"
    hist = {3: [(month_index(2026, 1), E(150), E(290))]}
    a = seasonal_alerts(m, hist, settings)
    assert a[0]["level"] == "warn" and "290" in a[0]["text"]


def test_pas_d_alerte_hors_approche(settings):
    m = mois()
    m.month = 6
    assert seasonal_alerts(m, {}, settings) == []
    m.month = 12                              # déjà dans la saison forte
    assert seasonal_alerts(m, {}, settings) == []


# --------------------------------------------------------------- crédits

def test_credit_objectif(settings):
    bal = [(month_index(2026, 8), E(1000)), (month_index(2026, 9), E(850)), (month_index(2026, 10), E(700))]
    st = credit_status("Renouvelable", "2026-12-31", bal, OCT)
    assert st["balance"] == E(700) and st["delta"] == E(-150)
    assert st["months_left"] == 2 and st["on_track"] is False   # 150/mois, il en faut 350
    st = credit_status("Renouvelable", "2027-06-30", bal, OCT)
    assert st["on_track"] is True


# ------------------------------------------------- imprévus payés avec le matelas

def avec_imprevus(*montants, **actuals):
    m = mois(**actuals)
    m.unplanned = [Unplanned(f"Achat {i}", E(v), "besoins" if i == 0 and v == 99 else "envies") for i, v in enumerate(montants)]
    return m


def test_imprevus_pris_sur_le_matelas(settings):
    s = summarize(avec_imprevus(62, 120), settings)
    assert s.unplanned == E(182)
    assert s.matelas_rest == E(318) and s.to_savings_end == E(318)
    assert s.epargne_mois == E(590)


def test_imprevus_depassements_et_economies(settings):
    # 500 − 70 de dépassement + 40 d'économie − 150 d'imprévus = 320
    s = summarize(avec_imprevus(150, Nourriture=470, Électricité=110), settings)
    assert s.matelas_rest == E(320)


def test_matelas_vide_sans_alerte(settings):
    m = avec_imprevus(300, 200)
    s = summarize(m, settings)
    assert s.matelas_rest == 0 and s.deficit == 0 and s.to_savings_end == 0
    assert s.epargne_mois == E(590)                       # il ne reste que salaire − budget
    notes = analysis_notes(m, s, split_503020(m, s, settings), [], None, 0, settings)
    assert any("servi en entier" in n["text"] and n["level"] == "warn" for n in notes)
    assert not any(n["level"] == "alert" for n in notes)   # le rouge reste réservé au dépassement


def test_au_dela_du_matelas(settings):
    m = avec_imprevus(300, 250)
    s = summarize(m, settings)
    assert s.matelas_rest == E(-50) and s.deficit == E(50)
    notes = analysis_notes(m, s, split_503020(m, s, settings), [], None, 0, settings)
    assert any(n["level"] == "alert" for n in notes)


def test_imprevus_dans_le_503020(settings):
    m = avec_imprevus(99, 60)                              # 99 € marqué « besoin », 60 € en envie
    split = {x["key"]: x for x in split_503020(m, summarize(m, settings), settings)}
    assert split["besoins"]["amount"] == E(1450 + 99)
    assert split["envies"]["amount"] == E(260 + 60)
    assert round(sum(x["pct"] for x in split.values())) == 100


def test_mois_en_cours_les_economies_attendent(settings):
    # 42 € de courses notés sur 400 € prévus : ce n'est pas 358 € d'économie tant que le mois court.
    m = mois(Nourriture=42)
    m.closed = False
    s = summarize(m, settings)
    assert s.savings == E(358) and s.savings_counted is False
    assert s.matelas_rest == E(500)                    # ni gonflé, ni entamé
    m.closed = True                                    # mois terminé : l'économie est acquise
    assert summarize(m, settings).matelas_rest == E(858)


def test_mois_en_cours_les_depassements_comptent_tout_de_suite(settings):
    m = mois(Nourriture=470, Électricité=110)
    m.closed = False
    assert summarize(m, settings).matelas_rest == E(430)


def test_credit_part_remboursee():
    bal = [(month_index(2026, 3), E(2552)), (month_index(2026, 10), E(1990)), (month_index(2026, 11), E(1892))]
    st = credit_status("prèt conso", None, bal, month_index(2026, 11))
    assert st["peak"] == E(2552) and st["repaid_pct"] == 26
    assert credit_status("x", None, [(OCT, 0)], OCT)["repaid_pct"] is None
