"""Montants : stockés en centimes (entiers), saisis et affichés en euros à la française."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def euros_to_cents(value) -> int:
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d * 100)


def parse_amount(text: str | None) -> int | None:
    """« 1 234,56 », « 1234.5 », « 12 € » -> centimes. Vide -> None. Invalide -> ValueError."""
    if text is None:
        return None
    t = str(text).strip().replace("€", "").replace(" ", "").replace(" ", "").replace(" ", "")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "")
    t = t.replace(",", ".")
    try:
        return euros_to_cents(Decimal(t))
    except InvalidOperation as exc:
        raise ValueError(f"Montant invalide : {text!r}") from exc


def format_eur(cents: int | None, signe: bool = False, decimales: bool = True) -> str:
    if cents is None:
        return "—"
    neg = cents < 0
    c = abs(int(cents))
    euros, cts = divmod(c, 100)
    ent = f"{euros:,}".replace(",", " ")
    txt = f"{ent},{cts:02d}" if decimales or cts else ent
    prefix = "−" if neg else ("+" if signe and cents > 0 else "")
    return f"{prefix}{txt} €"


def format_input(cents: int | None) -> str:
    """Valeur pré-remplie dans un champ de saisie."""
    if cents is None:
        return ""
    euros, cts = divmod(abs(int(cents)), 100)
    s = f"{euros},{cts:02d}" if cts else str(euros)
    return ("-" if cents < 0 else "") + s


def month_label(year: int, month: int) -> str:
    return f"{MOIS_FR[month - 1]} {year}"


def month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def from_index(idx: int) -> tuple[int, int]:
    return idx // 12, idx % 12 + 1


def next_month(year: int, month: int) -> tuple[int, int]:
    return from_index(month_index(year, month) + 1)


def prev_month(year: int, month: int) -> tuple[int, int]:
    return from_index(month_index(year, month) - 1)


def date_fr(iso: str | None) -> str:
    """« 2026-12-31 » -> « 31/12/2026 »."""
    if not iso or len(iso) < 10:
        return iso or ""
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"
