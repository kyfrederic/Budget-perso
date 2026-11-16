"""Lecture et écriture en base ; convertit les lignes SQL en objets de rules.py."""
from __future__ import annotations

from datetime import date

from .money import month_index, prev_month
from .rules import Line, Month, Unplanned

LINE_SQL = """
SELECT l.id AS line_id, l.planned, l.actual, l.info_partner,
       p.id AS poste_id, p.name, p.category, p.debit_day, p.seasonal, p.contractual,
       p.is_reserve, a.name AS account
FROM lines l
JOIN postes p ON p.id = l.poste_id
JOIN accounts a ON a.id = p.account_id
WHERE l.month_id = ?
ORDER BY a.sort, p.is_reserve, p.sort, LOWER(p.name)
"""


def _line(r) -> Line:
    return Line(
        poste_id=r["poste_id"], name=r["name"], account=r["account"], planned=r["planned"],
        actual=r["actual"], category=r["category"], debit_day=r["debit_day"],
        seasonal=bool(r["seasonal"]), contractual=bool(r["contractual"]),
        is_reserve=bool(r["is_reserve"]), info_partner=r["info_partner"], line_id=r["line_id"],
    )


def month_row(db, user_id: int, year: int, month: int):
    return db.execute(
        "SELECT * FROM months WHERE user_id = ? AND year = ? AND month = ?", (user_id, year, month)
    ).fetchone()


def load_month(db, row) -> Month:
    lines = [_line(r) for r in db.execute(LINE_SQL, (row["id"],))]
    unplanned = [
        Unplanned(r["label"], r["amount"], r["category"])
        for r in db.execute(
            "SELECT label, amount, category FROM purchases WHERE month_id = ? AND poste_id IS NULL", (row["id"],)
        )
    ]
    today = date.today()
    closed = month_index(row["year"], row["month"]) < month_index(today.year, today.month)
    return Month(row["year"], row["month"], row["salary_net"], lines, unplanned, closed)


def list_months(db, user_id: int) -> list:
    return db.execute(
        "SELECT * FROM months WHERE user_id = ? ORDER BY year DESC, month DESC", (user_id,)
    ).fetchall()


def latest_month(db, user_id: int):
    return db.execute(
        "SELECT * FROM months WHERE user_id = ? ORDER BY year DESC, month DESC LIMIT 1", (user_id,)
    ).fetchone()


def history(db, user_id: int) -> dict[int, list[tuple[int, int, int]]]:
    """poste_id -> [(index du mois, prévu, réel)] pour les mois où le réel est saisi."""
    out: dict[int, list[tuple[int, int, int]]] = {}
    rows = db.execute(
        "SELECT l.poste_id, m.year, m.month, l.planned, l.actual FROM lines l "
        "JOIN months m ON m.id = l.month_id "
        "WHERE m.user_id = ? AND l.actual IS NOT NULL ORDER BY m.year, m.month",
        (user_id,),
    )
    for r in rows:
        out.setdefault(r["poste_id"], []).append(
            (month_index(r["year"], r["month"]), r["planned"], r["actual"])
        )
    return out


def decided(db, user_id: int) -> set[tuple[int, int]]:
    rows = db.execute(
        "SELECT poste_id, ref_year, ref_month FROM proposal_decisions WHERE user_id = ?", (user_id,)
    )
    return {(r["poste_id"], month_index(r["ref_year"], r["ref_month"])) for r in rows}


def create_month(db, user_id: int, year: int, month: int, salary_net, net_imposable, pas) -> int:
    """Crée un mois en copiant les postes et montants du mois précédent (sans le réel).

    S'il n'y a pas de mois précédent, part des postes actifs et de leur montant par défaut.
    """
    cur = db.execute(
        "INSERT INTO months (user_id, year, month, salary_net, net_imposable, pas) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, year, month, salary_net, net_imposable, pas),
    )
    month_id = cur.lastrowid
    prev = db.execute(
        "SELECT id FROM months WHERE user_id = ? AND (year * 12 + month) < ? "
        "ORDER BY year DESC, month DESC LIMIT 1",
        (user_id, year * 12 + month),
    ).fetchone()
    if prev:
        db.execute(
            "INSERT INTO lines (month_id, poste_id, planned, info_partner) "
            "SELECT ?, l.poste_id, l.planned, l.info_partner FROM lines l "
            "JOIN postes p ON p.id = l.poste_id WHERE l.month_id = ? AND p.active = 1",
            (month_id, prev["id"]),
        )
    else:
        db.execute(
            "INSERT INTO lines (month_id, poste_id, planned) "
            "SELECT ?, id, default_planned FROM postes WHERE user_id = ? AND active = 1",
            (month_id, user_id),
        )
    return month_id


def credits_with_balances(db, user_id: int) -> list[dict]:
    out = []
    for c in db.execute("SELECT * FROM credits WHERE user_id = ? ORDER BY name", (user_id,)):
        bal = [
            (month_index(b["year"], b["month"]), b["balance"])
            for b in db.execute(
                "SELECT * FROM credit_balances WHERE credit_id = ? ORDER BY year, month", (c["id"],)
            )
        ]
        out.append({"id": c["id"], "name": c["name"], "target_date": c["target_date"], "balances": bal})
    return out


def overdue_cheques(db, user_id: int, year: int, month: int) -> list:
    """Chèques toujours en attente après leur mois prévu."""
    return db.execute(
        "SELECT * FROM cheques WHERE user_id = ? AND status = 'pending' "
        "AND (year * 12 + month) < ? ORDER BY year, month",
        (user_id, year * 12 + month),
    ).fetchall()


def previous_month_row(db, user_id: int, year: int, month: int):
    y, m = prev_month(year, month)
    return month_row(db, user_id, y, m)


def transfers_done(db, month_id: int) -> set[tuple[str, str]]:
    """{(nom du compte, 'debut' | 'fin')} des virements cochés « fait » pour ce mois."""
    rows = db.execute(
        "SELECT a.name, t.kind FROM transfers_done t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.month_id = ?", (month_id,),
    )
    return {(r["name"], r["kind"]) for r in rows}


def toggle_transfer(db, month_id: int, account_id: int, kind: str) -> bool:
    """Bascule l'état d'un virement ; renvoie True s'il est maintenant « fait »."""
    cur = db.execute(
        "DELETE FROM transfers_done WHERE month_id = ? AND account_id = ? AND kind = ?",
        (month_id, account_id, kind),
    )
    if cur.rowcount:
        return False
    db.execute(
        "INSERT INTO transfers_done (month_id, account_id, kind) VALUES (?, ?, ?)",
        (month_id, account_id, kind),
    )
    return True


def purchases(db, month_id: int) -> list:
    """Achats du mois, les plus récents d'abord, avec le nom du poste s'il y en a un."""
    return db.execute(
        "SELECT pu.*, p.name AS poste, a.name AS account FROM purchases pu "
        "LEFT JOIN postes p ON p.id = pu.poste_id LEFT JOIN accounts a ON a.id = p.account_id "
        "WHERE pu.month_id = ? ORDER BY COALESCE(pu.bought_on, pu.created_at) DESC, pu.id DESC",
        (month_id,),
    ).fetchall()


def add_purchase(db, month_id: int, label: str, amount: int, bought_on, poste_id, category: str, photo) -> int:
    """Enregistre un achat. Sur un poste, son montant s'ajoute au réel du poste."""
    if poste_id is not None:
        cur = db.execute(
            "UPDATE lines SET actual = COALESCE(actual, 0) + ? WHERE month_id = ? AND poste_id = ?",
            (amount, month_id, poste_id),
        )
        if cur.rowcount == 0:
            raise ValueError("Ce poste n'est pas dans le budget de ce mois.")
    return db.execute(
        "INSERT INTO purchases (month_id, label, amount, bought_on, poste_id, category, photo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (month_id, label, amount, bought_on, poste_id, category, photo),
    ).lastrowid


def delete_purchase(db, purchase_id: int, user_id: int):
    """Supprime un achat et rend son montant au poste. Renvoie la ligne supprimée (ou None)."""
    pu = db.execute(
        "SELECT pu.* FROM purchases pu JOIN months m ON m.id = pu.month_id WHERE pu.id = ? AND m.user_id = ?",
        (purchase_id, user_id),
    ).fetchone()
    if pu is None:
        return None
    db.execute("DELETE FROM purchases WHERE id = ?", (purchase_id,))
    if pu["poste_id"] is not None:
        db.execute(
            "UPDATE lines SET actual = CASE WHEN COALESCE(actual, 0) > ? THEN COALESCE(actual, 0) - ? ELSE 0 END "
            "WHERE month_id = ? AND poste_id = ?",
            (pu["amount"], pu["amount"], pu["month_id"], pu["poste_id"]),
        )
        # Plus aucun achat et un réel revenu à zéro : le poste redevient « pas encore saisi ».
        db.execute(
            "UPDATE lines SET actual = NULL WHERE month_id = ? AND poste_id = ? AND actual = 0 AND NOT EXISTS "
            "(SELECT 1 FROM purchases WHERE month_id = ? AND poste_id = ?)",
            (pu["month_id"], pu["poste_id"], pu["month_id"], pu["poste_id"]),
        )
    return pu


# ------------------------------------------------------------ photos des tickets


def save_photo(db, data: bytes) -> str:
    import secrets
    import time

    token = secrets.token_hex(16)
    db.execute("INSERT INTO ticket_photos (token, data, created_at) VALUES (?, ?, ?)", (token, data, time.time()))
    return token


def photo(db, token: str | None) -> bytes | None:
    from .receipt import valid_token

    if not valid_token(token):
        return None
    row = db.execute("SELECT data FROM ticket_photos WHERE token = ?", (token,)).fetchone()
    return bytes(row["data"]) if row else None


def photo_exists(db, token: str | None) -> bool:
    from .receipt import valid_token

    return valid_token(token) and db.execute(
        "SELECT 1 FROM ticket_photos WHERE token = ?", (token,)).fetchone() is not None


def delete_photo(db, token: str | None) -> None:
    if token:
        db.execute("DELETE FROM ticket_photos WHERE token = ?", (token,))


def purge_photos(db, max_age_hours: int = 24) -> None:
    """Supprime les photos envoyées mais jamais rattachées à un achat."""
    import time

    db.execute(
        "DELETE FROM ticket_photos WHERE created_at < ? AND token NOT IN "
        "(SELECT photo FROM purchases WHERE photo IS NOT NULL)",
        (time.time() - max_age_hours * 3600,),
    )
