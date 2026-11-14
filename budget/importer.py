"""Import unique des fichiers Excel mensuels (MOIS_SOLO.xlsx).

Structure lue (identique dans les neuf fichiers de 2026) :
  - 1er onglet : postes en colonne C, montant de Fred en D, part de Laetitia en G
    (lignes 4-20 : dépenses communes ; lignes 30-57 : charges personnelles) ;
    salaire en N1, total des dépenses en E65 ;
  - « 50-30-20 » : classement besoins / envies / épargne ;
  - « Depences personnelles » : compte de chaque poste ;
  - « Crédit » : reste dû par crédit (colonne D), objectif en colonne E.
"""
from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .money import MOIS_FR, euros_to_cents, month_index

ROWS = list(range(4, 21)) + list(range(30, 58))
COMMON_ROWS = range(4, 21)
FILE_MONTHS = {
    "JANVIER": 1, "FEVRIER": 2, "MARS": 3, "AVRIL": 4, "MAI": 5, "JUIN": 6, "JUILLET": 7,
    "AOUT": 8, "SEPTEMBRE": 9, "OCTOBRE": 10, "NOVEMBRE": 11, "DECEMBRE": 12,
}
# Groupe de la colonne B du 1er onglet -> catégorie, si le poste manque dans « 50-30-20 ».
GROUP_CATEGORY = {
    "credit": "besoins", "impots": "besoins", "depenses fixes": "besoins", "charges fixes": "besoins",
    "credits": "besoins", "impot": "besoins", "loisirs": "envies", "conforts": "envies",
    "autre": "envies", "epargne": "epargne",
}
CONTRACTUAL = re.compile(
    r"emprunt|pret|credit|assurance|co-propriete|internet|netfix|netflix|icloud|iptv|spotif|"
    r"abonnement|navigo|livret|epargne|telephone|salle de sport"
)
SEASONAL = re.compile(r"electricite|gaz|chauffage|energie")


def key(text) -> str:
    """Clé de comparaison : sans accents, sans casse, espaces réduits."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().casefold()


def clean(text) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


@dataclass
class PosteRow:
    name: str
    amount: int            # centimes
    partner: int | None
    group: str


@dataclass
class MonthFile:
    path: Path
    year: int
    month: int
    salary: int | None
    excel_total: int | None
    postes: list[PosteRow] = field(default_factory=list)
    accounts: dict[str, str] = field(default_factory=dict)     # clé du poste -> titre de bloc
    categories: dict[str, str] = field(default_factory=dict)   # clé du poste -> catégorie
    credits: dict[str, int] = field(default_factory=dict)      # nom -> reste dû
    targets: dict[str, str] = field(default_factory=dict)      # nom -> AAAA-MM-JJ

    @property
    def total(self) -> int:
        return sum(p.amount for p in self.postes)


def month_from_filename(path: Path) -> int:
    stem = key(path.stem).upper().split("_")[0]
    if stem not in FILE_MONTHS:
        raise ValueError(f"{path.name} : le nom doit commencer par un mois (ex. OCTOBRE_SOLO.xlsx).")
    return FILE_MONTHS[stem]


def _sheet(wb, wanted: str):
    for ws in wb.worksheets:
        if key(ws.title) == key(wanted):
            return ws
    return None


def read_file(path: Path, year: int, alias: dict[str, str]) -> MonthFile:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    sal, tot = num(ws["N1"].value), num(ws["E65"].value)
    mf = MonthFile(path, year, month_from_filename(path),
                   euros_to_cents(sal) if sal is not None else None,
                   euros_to_cents(tot) if tot is not None else None)
    aliases = {key(k): v for k, v in alias.items()}
    group = ""
    for r in ROWS:
        if ws.cell(r, 2).value:
            group = key(ws.cell(r, 2).value)
        name, amount = ws.cell(r, 3).value, num(ws.cell(r, 4).value)
        if not name or not amount:
            continue
        name = aliases.get(key(name), clean(name))
        partner = num(ws.cell(r, 7).value) if r in COMMON_ROWS else None
        mf.postes.append(PosteRow(name, euros_to_cents(amount),
                                  euros_to_cents(partner) if partner else None, group))

    # Comptes : chaque bloc de l'onglet commence par son titre et s'arrête à « TOTAL ».
    ws2 = _sheet(wb, "Depences personnelles")
    if ws2 is not None:
        for col in ws2.iter_cols():
            block = None
            for c in col:
                if not isinstance(c.value, str):
                    continue
                k = key(c.value)
                if k.startswith(("total", "reste", "repartition", "gain")):
                    block = None
                elif num(ws2.cell(c.row, c.column + 1).value) is None or k.startswith(("compte", "bourso", "cantine")):
                    block = clean(c.value) if k.startswith(("compte", "bourso", "cantine")) else block
                elif block:
                    mf.accounts[key(aliases.get(k, c.value))] = block

    # Catégories : trois blocs dans l'onglet « 50-30-20 ».
    ws3 = _sheet(wb, "50-30-20")
    if ws3 is not None:
        cat = None
        for r in range(2, ws3.max_row + 1):
            head = key(ws3.cell(r, 1).value)
            name = ws3.cell(r, 2).value
            if head.startswith("charge"):
                cat = "besoins"
            elif head.startswith("envie"):
                cat = "envies"
            elif head.startswith("epargne") or (name and cat == "envies" and not ws3.cell(r - 1, 2).value
                                                and not ws3.cell(r - 2, 2).value and r > 30):
                cat = "epargne"
            if name and cat:
                mf.categories[key(name)] = cat

    ws4 = _sheet(wb, "Crédit")
    if ws4 is not None:
        for r in range(2, ws4.max_row + 1):
            name, due = ws4.cell(r, 1).value, num(ws4.cell(r, 4).value)
            if not name or due is None or key(name) == "total":
                continue
            mf.credits[clean(name)] = euros_to_cents(due)
            m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(ws4.cell(r, 5).value or ""))
            if m:
                mf.targets[clean(name)] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return mf


def read_folder(folder: str | Path, year: int, config: dict) -> list[MonthFile]:
    files = sorted(Path(folder).glob("*_SOLO.xlsx"))
    if not files:
        raise ValueError(f"Aucun fichier *_SOLO.xlsx dans {folder}.")
    months = [read_file(f, year, config.get("alias", {})) for f in files]
    for mf in months:
        if mf.excel_total is not None and mf.excel_total != mf.total:
            from .money import format_eur
            raise ValueError(
                f"{mf.path.name} : les postes lus font {format_eur(mf.total)} mais Excel indique "
                f"{format_eur(mf.excel_total)} (cellule E65). La structure du fichier a peut-être changé."
            )
    return sorted(months, key=lambda m: month_index(m.year, m.month))


def category_for(name: str, group: str, categories: dict[str, str]) -> str:
    k = key(name)
    if k in categories:
        return categories[k]
    for other, cat in categories.items():           # « Assurance Vie LCL » ~ « Assurance Vie »
        if len(other) >= 6 and (k.startswith(other) or other.startswith(k)):
            return cat
    return GROUP_CATEGORY.get(group, "besoins")


@dataclass
class PosteSpec:
    name: str
    account: str
    category: str
    contractual: bool
    seasonal: bool
    is_reserve: bool
    active: bool
    account_guessed: bool


def build_postes(months: list[MonthFile], config: dict, known_accounts: set[str]) -> dict[str, PosteSpec]:
    """Fiche de chaque poste, d'après le fichier le plus récent où il apparaît."""
    mapping = {key(k): v for k, v in config.get("comptes", {}).items()}
    forced_account = {key(k): v for k, v in config.get("comptes_postes", {}).items()}
    forced_cat = {key(k): v for k, v in config.get("categories", {}).items()}
    default = config.get("compte_defaut", "LCL")
    reserve_account = config.get("compte_reserve", "N26")
    last = months[-1]
    active = {key(p.name) for p in last.postes}
    out: dict[str, PosteSpec] = {}
    for mf in reversed(months):
        for p in mf.postes:
            k = key(p.name)
            if k in out:
                continue
            block = mf.accounts.get(k) or last.accounts.get(k)
            account = forced_account.get(k) or (mapping.get(key(block)) if block else None)
            is_reserve = k == "reserve"
            guessed = account is None and not is_reserve
            if is_reserve:
                account = reserve_account
            account = account or default
            if account not in known_accounts:
                raise ValueError(f"Poste « {p.name} » : compte « {account} » absent de settings.toml.")
            cat = "besoins" if is_reserve else forced_cat.get(k) or category_for(
                p.name, p.group, {**last.categories, **mf.categories})
            if cat not in ("besoins", "envies", "epargne"):
                raise ValueError(f"Poste « {p.name} » : catégorie inconnue « {cat} ».")
            out[k] = PosteSpec(
                name=p.name, account=account, category=cat,
                contractual=bool(CONTRACTUAL.search(k)) and not is_reserve,
                seasonal=bool(SEASONAL.search(k)), is_reserve=is_reserve,
                active=k in active, account_guessed=guessed,
            )
    return out


def report(months: list[MonthFile], postes: dict[str, PosteSpec]) -> str:
    """Compte rendu lisible : sert d'exécution à blanc."""
    from .money import format_eur

    lines = ["Mois lus :"]
    for mf in months:
        ok = "" if mf.excel_total is None or mf.excel_total == mf.total else \
            f"  ⚠ Excel indique {format_eur(mf.excel_total)}"
        lines.append(f"  {MOIS_FR[mf.month - 1]:<10} {mf.year}  salaire {format_eur(mf.salary):>14}  "
                     f"budget {format_eur(mf.total):>13}  {len(mf.postes)} postes{ok}")
    lines.append("")
    lines.append(f"Postes ({len(postes)}) :")
    for s in sorted(postes.values(), key=lambda s: (s.account, s.name.casefold())):
        flags = [f for f, on in (("matelas", s.is_reserve), ("contractuel", s.contractual),
                                 ("saisonnier", s.seasonal), ("inactif", not s.active),
                                 ("compte par défaut", s.account_guessed)) if on]
        lines.append(f"  {s.account:<13} {s.category:<8} {s.name}" + (f"  [{', '.join(flags)}]" if flags else ""))
    last = months[-1]
    if last.credits:
        lines.append("")
        lines.append(f"Crédits (reste dû en {MOIS_FR[last.month - 1]}) :")
        for name, due in last.credits.items():
            t = last.targets.get(name)
            lines.append(f"  {name:<22} {format_eur(due):>13}" + (f"  objectif {t}" if t else ""))
    return "\n".join(lines)


def apply(conn, user_id: int, months: list[MonthFile], postes: dict[str, PosteSpec]) -> None:
    """Écrit postes, mois, lignes et soldes de crédits. Base vide exigée."""
    if conn.execute("SELECT COUNT(*) FROM postes WHERE user_id = ?", (user_id,)).fetchone()[0]:
        raise ValueError("Des postes existent déjà : l'import ne se fait que sur une base vide.")
    accounts = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM accounts WHERE user_id = ?", (user_id,))}
    latest = {key(p.name): p.amount for p in months[-1].postes}
    ids: dict[str, int] = {}
    for i, (k, s) in enumerate(postes.items()):
        cur = conn.execute(
            "INSERT INTO postes (user_id, name, account_id, category, seasonal, contractual, is_reserve, "
            "default_planned, active, sort) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, s.name, accounts[s.account], s.category, int(s.seasonal), int(s.contractual),
             int(s.is_reserve), latest.get(k, 0), int(s.active), i),
        )
        ids[k] = cur.lastrowid
    credit_ids: dict[str, int] = {}
    for mf in months:
        cur = conn.execute(
            "INSERT INTO months (user_id, year, month, salary_net) VALUES (?, ?, ?, ?)",
            (user_id, mf.year, mf.month, mf.salary),
        )
        for p in mf.postes:
            conn.execute(
                "INSERT INTO lines (month_id, poste_id, planned, info_partner) VALUES (?, ?, ?, ?)",
                (cur.lastrowid, ids[key(p.name)], p.amount, p.partner),
            )
        for name, due in mf.credits.items():
            k = key(name)
            if k not in credit_ids:
                target = next((m.targets[name] for m in reversed(months) if name in m.targets), None)
                credit_ids[k] = conn.execute(
                    "INSERT INTO credits (user_id, name, target_date) VALUES (?, ?, ?)", (user_id, name, target)
                ).lastrowid
            conn.execute(
                "INSERT INTO credit_balances (credit_id, year, month, balance) VALUES (?, ?, ?, ?)",
                (credit_ids[k], mf.year, mf.month, due),
            )
    # Un crédit jamais dû (toujours à 0) n'a pas d'intérêt.
    never = "SELECT id FROM credits WHERE user_id = ? AND id NOT IN (SELECT credit_id FROM credit_balances WHERE balance > 0)"
    conn.execute(f"DELETE FROM credit_balances WHERE credit_id IN ({never})", (user_id,))
    conn.execute(
        "DELETE FROM credits WHERE user_id = ? AND id NOT IN (SELECT credit_id FROM credit_balances)", (user_id,)
    )
    conn.commit()


def load_config(settings_file: str) -> dict:
    with open(settings_file, "rb") as f:
        return tomllib.load(f).get("import", {})
