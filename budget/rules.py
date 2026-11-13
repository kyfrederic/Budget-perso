"""Règles métier, sans accès à la base : faciles à tester.

Tous les montants sont en centimes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from .money import MOIS_FR, date_fr, format_eur, from_index, month_index, month_label
from .settings import Settings

CATEGORIES = ("besoins", "envies", "epargne")
CATEGORIES_LABEL = {"besoins": "Besoins", "envies": "Envies", "epargne": "Épargne"}


@dataclass
class Line:
    poste_id: int
    name: str
    account: str
    planned: int
    actual: int | None = None
    category: str = "besoins"
    debit_day: int | None = None
    seasonal: bool = False
    contractual: bool = False
    is_reserve: bool = False
    info_partner: int | None = None
    line_id: int | None = None

    @property
    def diff(self) -> int | None:
        """Réel − prévu (positif = dépassement). None si le réel n'est pas saisi."""
        if self.actual is None or self.is_reserve:
            return None
        return self.actual - self.planned


@dataclass
class Month:
    year: int
    month: int
    salary_net: int | None
    lines: list[Line] = field(default_factory=list)

    @property
    def idx(self) -> int:
        return month_index(self.year, self.month)


@dataclass
class Virement:
    account: str
    amount: int
    detail: str = ""
    kind: str = "budget"  # budget | reste | epargne


@dataclass
class Summary:
    total_budget: int
    reserve: int
    overruns: int          # somme des dépassements
    savings: int           # somme des économies (postes sous leur prévu)
    matelas_rest: int      # reserve − dépassements + économies (peut être négatif)
    to_savings_end: int    # reste du matelas viré en épargne en fin de mois
    deficit: int           # ce que le matelas n'a pas pu absorber
    epargne_debut: int | None   # salaire − budget
    epargne_postes: int    # postes de catégorie « épargne » (épargne programmée)
    epargne_mois: int | None    # (salaire − budget) + reste du matelas
    taux_epargne: float | None  # (épargne du mois + épargne programmée) / salaire
    virements: list[Virement]
    n_lines: int
    n_entered: int

    @property
    def complete(self) -> bool:
        return self.n_lines > 0 and self.n_entered == self.n_lines


# ---------------------------------------------------------------- synthèse


def summarize(month: Month, settings: Settings) -> Summary:
    lines = month.lines
    total = sum(l.planned for l in lines)
    reserve = sum(l.planned for l in lines if l.is_reserve)
    normal = [l for l in lines if not l.is_reserve]
    diffs = [l.diff for l in normal if l.diff is not None]
    overruns = sum(d for d in diffs if d > 0)
    savings = -sum(d for d in diffs if d < 0)
    rest = reserve - overruns + savings
    to_savings_end = max(0, rest)
    deficit = max(0, -rest)

    epargne_debut = None if month.salary_net is None else month.salary_net - total
    epargne_postes = sum(l.planned for l in normal if l.category == "epargne")
    epargne_mois = None if epargne_debut is None else epargne_debut + to_savings_end
    taux = None
    if month.salary_net:
        taux = (epargne_mois + epargne_postes) / month.salary_net * 100

    return Summary(
        total_budget=total,
        reserve=reserve,
        overruns=overruns,
        savings=savings,
        matelas_rest=rest,
        to_savings_end=to_savings_end,
        deficit=deficit,
        epargne_debut=epargne_debut,
        epargne_postes=epargne_postes,
        epargne_mois=epargne_mois,
        taux_epargne=taux,
        virements=_virements(month, epargne_debut, settings),
        n_lines=len(normal),
        n_entered=len(diffs),
    )


def _virements(month: Month, epargne_debut: int | None, settings: Settings) -> list[Virement]:
    """Un virement par compte, à faire depuis le compte du salaire à sa réception."""
    par_compte: dict[str, list[Line]] = {}
    for l in month.lines:
        if l.planned:
            par_compte.setdefault(l.account, []).append(l)
    ordre = [c.nom for c in settings.comptes]
    noms = sorted(par_compte, key=lambda n: ordre.index(n) if n in ordre else len(ordre))
    out: list[Virement] = []
    for nom in noms:
        ls = par_compte[nom]
        montant = sum(l.planned for l in ls)
        detail = ", ".join(l.name for l in ls)
        if nom == settings.compte_epargne:
            continue  # regroupé avec l'épargne ci-dessous
        kind = "reste" if nom == settings.compte_salaire else "budget"
        out.append(Virement(nom, montant, detail, kind))
    ep_lines = par_compte.get(settings.compte_epargne, [])
    ep = sum(l.planned for l in ep_lines)
    parts = [l.name for l in ep_lines]
    if epargne_debut is not None and epargne_debut > 0:
        ep += epargne_debut
        parts.append(f"salaire − budget ({format_eur(epargne_debut)})")
    if ep:
        out.append(Virement(settings.compte_epargne, ep, ", ".join(parts), "epargne"))
    return out


def split_503020(month: Month, summary: Summary, settings: Settings) -> list[dict]:
    """Répartition besoins / envies / épargne en % du salaire net.

    Réel si saisi, sinon prévu. Le matelas n'est pas compté comme un poste :
    sa part consommée est déjà dans le réel des postes, son reste part en épargne.
    """
    montants = dict.fromkeys(CATEGORIES, 0)
    for l in month.lines:
        if l.is_reserve:
            continue
        montants[l.category] += l.actual if l.actual is not None else l.planned
    if summary.epargne_mois is not None:
        montants["epargne"] += max(0, summary.epargne_mois)
    base = month.salary_net or sum(montants.values())
    out = []
    for cat in CATEGORIES:
        pct = montants[cat] / base * 100 if base else 0.0
        out.append({
            "key": cat,
            "label": CATEGORIES_LABEL[cat],
            "amount": montants[cat],
            "pct": pct,
            "target": settings.repartition[cat],
        })
    return out


# ------------------------------------------------------------ propositions


@dataclass
class Proposal:
    poste_id: int
    name: str
    direction: str  # hausse | baisse
    current: int
    proposed: int
    ref_idx: int
    reason: str

    @property
    def ref(self) -> tuple[int, int]:
        return from_index(self.ref_idx)


def _significant(planned: int, actual: int, settings: Settings) -> int:
    """+1 dépassement significatif, −1 économie significative, 0 sinon.

    Un écart compte seulement s'il atteint le seuil en euros ET le seuil en %.
    """
    diff = actual - planned
    if abs(diff) < settings.prop_seuil_cents:
        return 0
    if planned > 0 and abs(diff) * 100 < settings.prop_seuil_pct * planned:
        return 0
    return 1 if diff > 0 else -1


def round_to(cents: float, step: int) -> int:
    if step <= 0:
        return int(round(cents))
    return int((cents + step / 2) // step) * step


def compute_proposals(
    current: Month,
    history: dict[int, list[tuple[int, int, int]]],
    decided: set[tuple[int, int]],
    settings: Settings,
) -> list[Proposal]:
    """Propositions d'ajustement pour le mois en cours.

    history : poste_id -> [(index du mois, prévu, réel)] pour les mois où le réel est saisi.
    decided : {(poste_id, index du mois de référence)} déjà acceptées ou refusées.
    """
    out: list[Proposal] = []
    k = max(1, settings.prop_mois_consecutifs)
    for line in current.lines:
        if line.is_reserve or line.contractual:
            continue
        hist = sorted(h for h in history.get(line.poste_id, []) if h[0] <= current.idx)
        if len(hist) < max(settings.prop_mois_minimum, k):
            continue
        last = hist[-k:]
        ref_idx = last[-1][0]
        if ref_idx < current.idx - 1:
            continue  # historique trop ancien
        if any(b[0] - a[0] != 1 for a, b in zip(last, last[1:])):
            continue  # pas des mois consécutifs
        signs = {_significant(p, a, settings) for _, p, a in last}
        if signs == {1}:
            direction = "hausse"
        elif signs == {-1} and not line.seasonal:
            direction = "baisse"
        else:
            continue
        if (line.poste_id, ref_idx) in decided:
            continue
        window = [a for _, _, a in hist[-max(1, settings.prop_fenetre_mediane):]]
        proposed = round_to(median(window), settings.prop_arrondi_cents)
        if direction == "hausse" and proposed <= line.planned:
            continue
        if direction == "baisse" and proposed >= line.planned:
            continue
        mois_txt = " et ".join(month_label(*from_index(i)) for i, _, _ in last)
        verbe = "dépassé" if direction == "hausse" else "sous le prévu"
        reels = ", ".join(format_eur(a) for a in window)
        out.append(Proposal(
            poste_id=line.poste_id,
            name=line.name,
            direction=direction,
            current=line.planned,
            proposed=proposed,
            ref_idx=ref_idx,
            reason=f"{verbe.capitalize()} en {mois_txt}. Médiane des derniers réels ({reels}).",
        ))
    out.sort(key=lambda p: -abs(p.proposed - p.current))
    return out


# ------------------------------------------------------------ saisonnalité


def seasonal_alerts(
    current: Month,
    history: dict[int, list[tuple[int, int, int]]],
    settings: Settings,
) -> list[dict]:
    """Alerte préventive à l'approche de la saison forte, pour les postes saisonniers."""
    saison = set(settings.mois_saison_forte)
    if not saison or current.month in saison:
        return []
    approche = any(
        from_index(current.idx + k)[1] in saison
        for k in range(1, settings.alerte_mois_avant + 1)
    )
    if not approche:
        return []
    out = []
    for line in current.lines:
        if not line.seasonal:
            continue
        # Réels de la saison forte précédente (les 12 derniers mois).
        passes = [
            (i, a) for i, _, a in history.get(line.poste_id, [])
            if current.idx - 12 <= i < current.idx and from_index(i)[1] in saison
        ]
        if passes:
            i_max, a_max = max(passes, key=lambda t: t[1])
            ok = a_max <= line.planned
            texte = (
                f"{line.name} : la saison forte arrive. L'an dernier, jusqu'à "
                f"{format_eur(a_max)} ({month_label(*from_index(i_max))}) pour "
                f"{format_eur(line.planned)} prévus aujourd'hui."
                + ("" if ok else " Le montant fixé risque de ne pas suffire.")
            )
            out.append({"poste_id": line.poste_id, "level": "info" if ok else "warn", "text": texte})
        else:
            out.append({
                "poste_id": line.poste_id,
                "level": "info",
                "text": (
                    f"{line.name} : la saison forte arrive, ce poste est habituellement plus "
                    f"haut. Vérifier que {format_eur(line.planned)} suffisent "
                    "(pas encore d'historique de l'an dernier)."
                ),
            })
    return out


# ----------------------------------------------------------------- crédits


def credit_status(name: str, target_date: str | None, balances: list[tuple[int, int]], upto_idx: int) -> dict:
    """Évolution d'un crédit. balances : [(index du mois, reste dû)]."""
    pts = sorted(b for b in balances if b[0] <= upto_idx)
    st = {
        "name": name, "target_date": target_date, "balance": None, "delta": None,
        "pace": None, "needed": None, "on_track": None, "months_left": None, "last_idx": None,
    }
    if not pts:
        return st
    st["last_idx"], st["balance"] = pts[-1]
    if len(pts) >= 2:
        st["delta"] = pts[-1][1] - pts[-2][1]
        recent = pts[-4:]
        span = recent[-1][0] - recent[0][0]
        if span > 0:
            st["pace"] = (recent[0][1] - recent[-1][1]) / span  # baisse moyenne par mois
    if target_date and st["balance"] > 0:
        y, m = int(target_date[:4]), int(target_date[5:7])
        left = month_index(y, m) - st["last_idx"]
        st["months_left"] = left
        if left > 0:
            st["needed"] = st["balance"] / left
            if st["pace"] is not None:
                st["on_track"] = st["pace"] >= st["needed"]
        else:
            st["on_track"] = False
    elif target_date and st["balance"] <= 0:
        st["on_track"] = True
    return st


# ----------------------------------------------------------------- analyse


def analysis_notes(
    month: Month,
    summary: Summary,
    split: list[dict],
    credits: list[dict],
    previous: Summary | None,
    n_proposals: int,
    settings: Settings,
) -> list[dict]:
    """Constats et pistes d'amélioration du mois (moteur à règles)."""
    notes: list[dict] = []

    def add(level: str, text: str) -> None:
        notes.append({"level": level, "text": text})

    if not summary.complete:
        manquants = summary.n_lines - summary.n_entered
        add("info", f"Analyse partielle : {manquants} poste(s) sans réel saisi (comptés à leur prévu).")

    if summary.epargne_debut is not None and summary.epargne_debut < 0:
        add("alert", f"Le budget dépasse le salaire de {format_eur(-summary.epargne_debut)} : "
                     "aucune épargne possible ce mois-ci, revoir les postes.")

    if summary.deficit > 0:
        add("alert", f"Le matelas n'a pas suffi : {format_eur(summary.deficit)} de dépassement "
                     "non couvert (risque de découvert).")
    elif summary.complete and summary.reserve:
        if summary.matelas_rest >= summary.reserve:
            add("ok", f"Matelas intact : {format_eur(summary.to_savings_end)} à virer en épargne.")
        else:
            utilise = summary.reserve - summary.matelas_rest
            add("info", f"Matelas entamé de {format_eur(utilise)} ; il reste "
                        f"{format_eur(summary.to_savings_end)} à virer en épargne.")

    depass = sorted(
        (l for l in month.lines if (l.diff or 0) > 0 and _significant(l.planned, l.actual, settings) == 1),
        key=lambda l: -l.diff,
    )
    if depass:
        txt = ", ".join(f"{l.name} ({format_eur(l.diff, signe=True)})" for l in depass[:4])
        add("warn", f"Postes en dépassement : {txt}.")
    if n_proposals:
        add("info", f"{n_proposals} proposition(s) d'ajustement du budget à examiner.")

    cible = settings.repartition
    by = {s["key"]: s for s in split}
    if month.salary_net:
        if summary.taux_epargne is not None:
            if summary.taux_epargne >= cible["epargne"]:
                add("ok", f"Taux d'épargne de {summary.taux_epargne:.0f} % "
                          f"(cible {cible['epargne']:.0f} %).")
            else:
                manque = int((cible["epargne"] - summary.taux_epargne) / 100 * month.salary_net)
                add("warn", f"Taux d'épargne de {summary.taux_epargne:.0f} % sous la cible de "
                            f"{cible['epargne']:.0f} % : il manque environ "
                            f"{format_eur(manque, decimales=False)} par mois.")
        if by["envies"]["pct"] > cible["envies"]:
            gros = sorted((l for l in month.lines if l.category == "envies"),
                          key=lambda l: -(l.actual if l.actual is not None else l.planned))[:3]
            add("warn", f"Envies à {by['envies']['pct']:.0f} % du salaire (cible "
                        f"{cible['envies']:.0f} %). Plus gros postes : "
                        + ", ".join(l.name for l in gros) + ".")
        if by["besoins"]["pct"] > cible["besoins"]:
            add("info", f"Besoins à {by['besoins']['pct']:.0f} % du salaire (cible "
                        f"{cible['besoins']:.0f} %) : gagner en pouvoir d'achat passe par les "
                        "gros contrats (assurances, énergie, abonnements à renégocier).")

    if previous and previous.epargne_mois is not None and summary.epargne_mois is not None:
        d = summary.epargne_mois - previous.epargne_mois
        if d:
            add("info", f"Épargne du mois : {format_eur(summary.epargne_mois)} "
                        f"({format_eur(d, signe=True)} par rapport au mois précédent).")

    if (summary.complete and previous and previous.complete and summary.reserve
            and summary.matelas_rest >= 0.8 * summary.reserve
            and previous.matelas_rest >= 0.8 * previous.reserve):
        add("ok", "Le matelas est presque intact deux mois de suite : le budget tient. "
                  "Tu peux envisager d'augmenter l'épargne programmée ou d'investir l'excédent.")

    for c in credits:
        if c["balance"] is None:
            continue
        if c["on_track"] is False and c["balance"] > 0:
            if c["needed"]:
                add("warn", f"{c['name']} : au rythme actuel, l'objectif du {date_fr(c['target_date'])} "
                            f"ne sera pas tenu (il faudrait {format_eur(int(c['needed']), decimales=False)} "
                            "par mois).")
            else:
                add("warn", f"{c['name']} : l'objectif du {date_fr(c['target_date'])} est dépassé.")
        elif c["on_track"] and c["balance"] > 0:
            add("ok", f"{c['name']} : le rythme actuel permet de tenir l'objectif du {date_fr(c['target_date'])}.")
    return notes


__all__ = [
    "CATEGORIES", "CATEGORIES_LABEL", "Line", "Month", "Proposal", "Summary", "Virement",
    "analysis_notes", "compute_proposals", "credit_status", "round_to", "seasonal_alerts",
    "split_503020", "summarize", "MOIS_FR",
]
