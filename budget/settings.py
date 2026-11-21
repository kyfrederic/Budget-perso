"""Lecture des fichiers de configuration TOML."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .money import euros_to_cents


@dataclass(frozen=True)
class Compte:
    nom: str
    couleur: str
    description: str = ""


@dataclass(frozen=True)
class Settings:
    matelas: int  # centimes
    compte_epargne: str
    compte_salaire: str
    prop_mois_minimum: int
    prop_mois_consecutifs: int
    prop_seuil_pct: float
    prop_seuil_cents: int
    prop_fenetre_mediane: int
    prop_arrondi_cents: int
    mois_saison_forte: tuple[int, ...]
    alerte_mois_avant: int
    repartition: dict[str, float]
    duree_session_heures: int
    tentatives_max: int
    fenetre_tentatives_minutes: int
    comptes: tuple[Compte, ...] = field(default_factory=tuple)

    def couleur(self, nom_compte: str) -> str:
        for c in self.comptes:
            if c.nom == nom_compte:
                return c.couleur
        return "#888888"


def load_settings(path: str | Path) -> Settings:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    p = raw.get("propositions", {})
    s = raw.get("saisonnalite", {})
    r = raw.get("repartition", {})
    sec = raw.get("securite", {})
    ep = raw.get("epargne", {})
    comptes = tuple(
        Compte(c["nom"], c.get("couleur", "#888888"), c.get("description", ""))
        for c in raw.get("comptes", [])
    )
    if not comptes:
        raise ValueError("settings.toml : au moins un [[comptes]] est requis")
    noms = {c.nom for c in comptes}
    for cle, val in (("epargne.compte", ep.get("compte")), ("epargne.compte_salaire", ep.get("compte_salaire"))):
        if val and val not in noms:
            raise ValueError(f"settings.toml : {cle} = {val!r} ne correspond à aucun compte")
    return Settings(
        matelas=euros_to_cents(raw.get("matelas", {}).get("montant", 500)),
        compte_epargne=ep.get("compte", comptes[0].nom),
        compte_salaire=ep.get("compte_salaire", comptes[0].nom),
        prop_mois_minimum=int(p.get("mois_minimum", 2)),
        prop_mois_consecutifs=int(p.get("mois_consecutifs", 2)),
        prop_seuil_pct=float(p.get("seuil_pourcentage", 10)),
        prop_seuil_cents=euros_to_cents(p.get("seuil_euros", 10)),
        prop_fenetre_mediane=int(p.get("fenetre_mediane", 3)),
        prop_arrondi_cents=euros_to_cents(p.get("arrondi", 5)),
        mois_saison_forte=tuple(int(m) for m in s.get("mois_saison_forte", [11, 12, 1, 2])),
        alerte_mois_avant=int(s.get("alerte_mois_avant", 1)),
        repartition={
            "besoins": float(r.get("besoins", 50)),
            "envies": float(r.get("envies", 30)),
            "epargne": float(r.get("epargne", 20)),
        },
        duree_session_heures=int(sec.get("duree_session_heures", 12)),
        tentatives_max=int(sec.get("tentatives_max", 5)),
        fenetre_tentatives_minutes=int(sec.get("fenetre_tentatives_minutes", 15)),
        comptes=comptes,
    )
