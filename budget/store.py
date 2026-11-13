"""Lecture et écriture en base ; convertit les lignes SQL en objets de rules.py."""
from __future__ import annotations

import sqlite3

from .money import month_index, prev_month
from .rules import Line, Month

LINE_SQL = """
SELECT l.id AS line_id, l.planned, l.actual, l.info_partner,
       p.id AS poste_id, p.name, p.category, p.debit_day, p.seasonal, p.contractual,
       p.is_reserve, a.name AS account
FROM lines l
JOIN postes p ON p.id = l.poste_id
JOIN accounts a ON a.id = p.account_id
WHERE l.month_id = ?
ORDER BY a.sort, p.is_reserve, p.sort, p.name COLLATE NOCASE
"""


def _line(r: sqlite3.Row) -> Line:
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
    return Month(row["year"], row["month"], row["salary_net"], lines)


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
