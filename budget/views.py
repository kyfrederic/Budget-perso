"""Écrans de la V1."""
from __future__ import annotations

import calendar
import re
from datetime import date

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template,
                   request, url_for)

from . import rules, store
from .db import get_db
from .money import (MOIS_FR, from_index, month_index, month_label, next_month, parse_amount,
                    prev_month)

bp = Blueprint("views", __name__)


def settings():
    return current_app.config["SETTINGS"]


def _amount(field: str, label: str | None = None, required: bool = False) -> int | None:
    try:
        v = parse_amount(request.form.get(field))
    except ValueError:
        abort(400, f"Montant invalide pour « {label or field} ».")
    if v is None and required:
        abort(400, f"Montant manquant pour « {label or field} ».")
    if v is not None and not (-10**10 < v < 10**10):
        abort(400, "Montant hors limites.")
    return v


def _month_or_404(year: int, month: int):
    row = store.month_row(get_db(), g.user_id, year, month)
    if row is None:
        abort(404)
    return row


def _accounts():
    rows = get_db().execute(
        "SELECT * FROM accounts WHERE user_id = ? ORDER BY sort, name", (g.user_id,)
    ).fetchall()
    known = {c.nom for c in settings().comptes}
    return [r for r in rows if r["name"] in known]


@bp.app_context_processor
def inject():
    def account_class(name: str) -> str:
        noms = [c.nom for c in settings().comptes]
        return f"cpt-{noms.index(name)}" if name in noms else "cpt-x"
    return {"account_class": account_class, "MOIS_FR": MOIS_FR, "today": date.today()}


@bp.route("/sante")
def sante():
    return "ok"


@bp.route("/couleurs.css")
def couleurs():
    """Couleurs des banques (settings.toml), servies en CSS pour garder une CSP stricte."""
    css = [
        f".cpt-{i}{{--cpt:{c.couleur}}}"
        for i, c in enumerate(settings().comptes)
        if re.fullmatch(r"#[0-9a-fA-F]{3,8}", c.couleur)
    ]
    return Response("\n".join(css), mimetype="text/css")


# ------------------------------------------------------------------- mois


@bp.route("/")
def home():
    row = store.latest_month(get_db(), g.user_id)
    if row is None:
        return redirect(url_for("views.new_month"))
    today = date.today()
    cur = store.month_row(get_db(), g.user_id, today.year, today.month) or row
    return redirect(url_for("views.month", year=cur["year"], month=cur["month"]))


def _context(row) -> dict:
    """Tout ce qui se calcule pour un mois : synthèse, propositions, alertes."""
    db = get_db()
    s = settings()
    m = store.load_month(db, row)
    summary = rules.summarize(m, s)
    hist = store.history(db, g.user_id)
    latest = store.latest_month(db, g.user_id)
    is_latest = latest["id"] == row["id"]
    proposals = rules.compute_proposals(m, hist, store.decided(db, g.user_id), s) if is_latest else []
    return {
        "row": row, "m": m, "summary": summary, "history": hist, "is_latest": is_latest,
        "proposals": proposals,
        "seasonal": rules.seasonal_alerts(m, hist, s),
        "overdue": store.overdue_cheques(db, g.user_id, *_today_ym()),
        "prev": prev_month(m.year, m.month), "next": next_month(m.year, m.month),
        "has_prev": store.month_row(db, g.user_id, *prev_month(m.year, m.month)) is not None,
        "has_next": store.month_row(db, g.user_id, *next_month(m.year, m.month)) is not None,
        "settings": s,
    }


def _today_ym() -> tuple[int, int]:
    t = date.today()
    return t.year, t.month


@bp.route("/mois/<int:year>/<int:month>")
def month(year: int, month: int):
    row = _month_or_404(year, month)
    ctx = _context(row)
    db = get_db()
    cheques = db.execute(
        "SELECT * FROM cheques WHERE user_id = ? AND year = ? AND month = ? AND status = 'pending'",
        (g.user_id, year, month),
    ).fetchall()
    groups: dict[str, list] = {}
    for l in ctx["m"].lines:
        groups.setdefault(l.account, []).append(l)
    done = store.transfers_done(db, row["id"])
    # Le compte du salaire ne reçoit pas de virement : l'argent y reste.
    todo = [v for v in ctx["summary"].virements if v.kind != "reste"]
    progress = [l for l in ctx["m"].lines if l.diff is not None]
    return render_template(
        "month.html", **ctx, groups=groups, cheques=cheques, done=done, todo=todo,
        stays=[v for v in ctx["summary"].virements if v.kind == "reste"],
        n_left=sum(1 for v in todo if (v.account, "debut") not in done),
        progress=sorted(progress, key=lambda l: -(l.actual / l.planned if l.planned else 9)),
        reserve_account=next((l.account for l in ctx["m"].lines if l.is_reserve), None),
        cheques_total=sum(c["amount"] for c in cheques),
        salary_month=month_label(*prev_month(year, month)),
        available_postes=db.execute(
            "SELECT p.id, p.name FROM postes p WHERE p.user_id = ? AND p.active = 1 AND p.id NOT IN "
            "(SELECT poste_id FROM lines WHERE month_id = ?) ORDER BY p.name",
            (g.user_id, row["id"]),
        ).fetchall(),
    )


@bp.route("/mois/<int:year>/<int:month>", methods=["POST"])
def month_save(year: int, month: int):
    row = _month_or_404(year, month)
    db = get_db()
    db.execute(
        "UPDATE months SET salary_net = ?, net_imposable = ?, pas = ?, notes = ? WHERE id = ?",
        (_amount("salary_net", "salaire net"), _amount("net_imposable", "net imposable"),
         _amount("pas", "prélèvement à la source"), request.form.get("notes", "")[:2000], row["id"]),
    )
    for l in store.load_month(db, row).lines:
        key = str(l.line_id)
        if f"planned_{key}" not in request.form:
            continue
        planned = _amount(f"planned_{key}", l.name) or 0
        actual = None if l.is_reserve else _amount(f"actual_{key}", l.name)
        partner = _amount(f"partner_{key}", l.name)
        db.execute(
            "UPDATE lines SET planned = ?, actual = ?, info_partner = ? WHERE id = ? AND month_id = ?",
            (planned, actual, partner, l.line_id, row["id"]),
        )
    db.commit()
    flash("Mois enregistré.")
    return redirect(url_for("views.month", year=year, month=month))


@bp.route("/mois/<int:year>/<int:month>/virement", methods=["POST"])
def transfer_toggle(year: int, month: int):
    """Coche ou décoche un virement (« fait »)."""
    row = _month_or_404(year, month)
    db = get_db()
    kind = request.form.get("kind", "debut")
    acc = next((a for a in _accounts() if a["name"] == request.form.get("account")), None)
    if acc is None or kind not in ("debut", "fin"):
        abort(400, "Virement inconnu.")
    is_done = store.toggle_transfer(db, row["id"], acc["id"], kind)
    db.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return {"done": is_done}
    return redirect(url_for("views.month", year=year, month=month) + "#virements")


@bp.route("/mois/<int:year>/<int:month>/ligne", methods=["POST"])
def line_add(year: int, month: int):
    row = _month_or_404(year, month)
    db = get_db()
    p = db.execute(
        "SELECT * FROM postes WHERE id = ? AND user_id = ?",
        (request.form.get("poste_id", type=int), g.user_id),
    ).fetchone()
    if p is None:
        abort(400)
    db.execute(
        "INSERT OR IGNORE INTO lines (month_id, poste_id, planned) VALUES (?, ?, ?)",
        (row["id"], p["id"], p["default_planned"]),
    )
    db.commit()
    return redirect(url_for("views.month", year=year, month=month))


@bp.route("/mois/<int:year>/<int:month>/ligne/<int:line_id>/retirer", methods=["POST"])
def line_remove(year: int, month: int, line_id: int):
    row = _month_or_404(year, month)
    db = get_db()
    db.execute("DELETE FROM lines WHERE id = ? AND month_id = ?", (line_id, row["id"]))
    db.commit()
    flash("Poste retiré de ce mois.")
    return redirect(url_for("views.month", year=year, month=month))


@bp.route("/mois/nouveau", methods=["GET", "POST"])
def new_month():
    db = get_db()
    latest = store.latest_month(db, g.user_id)
    if latest:
        y, m = next_month(latest["year"], latest["month"])
    else:
        y, m = _today_ym()
    if request.method == "POST":
        y = request.form.get("year", type=int) or y
        m = request.form.get("month", type=int) or m
        if not (2000 <= y <= 2100 and 1 <= m <= 12):
            abort(400)
        if store.month_row(db, g.user_id, y, m):
            flash(f"Le mois de {month_label(y, m)} existe déjà.")
            return redirect(url_for("views.month", year=y, month=m))
        store.create_month(
            db, g.user_id, y, m,
            _amount("salary_net", "salaire net"), _amount("net_imposable", "net imposable"),
            _amount("pas", "prélèvement à la source"),
        )
        db.commit()
        flash(f"Mois de {month_label(y, m)} créé à partir du mois précédent.")
        return redirect(url_for("views.month", year=y, month=m))
    n_postes = db.execute(
        "SELECT COUNT(*) FROM postes WHERE user_id = ? AND active = 1", (g.user_id,)
    ).fetchone()[0]
    return render_template(
        "new_month.html", year=y, month=m, latest=latest, n_postes=n_postes,
        salary_month=month_label(*prev_month(y, m)),
    )


@bp.route("/mois")
def months():
    db = get_db()
    out = []
    for row in store.list_months(db, g.user_id):
        m = store.load_month(db, row)
        out.append({"row": row, "summary": rules.summarize(m, settings())})
    return render_template("months.html", months=out)


# ----------------------------------------------------------- propositions


@bp.route("/propositions/<int:poste_id>/<int:ref_idx>/<action>", methods=["POST"])
def proposal_decide(poste_id: int, ref_idx: int, action: str):
    if action not in ("accepter", "refuser"):
        abort(404)
    db = get_db()
    row = store.latest_month(db, g.user_id)
    if row is None:
        abort(404)
    m = store.load_month(db, row)
    props = rules.compute_proposals(m, store.history(db, g.user_id), store.decided(db, g.user_id), settings())
    prop = next((p for p in props if p.poste_id == poste_id and p.ref_idx == ref_idx), None)
    if prop is None:
        flash("Cette proposition n'est plus d'actualité.")
        return redirect(url_for("views.month", year=row["year"], month=row["month"]))
    ry, rm = from_index(ref_idx)
    db.execute(
        "INSERT INTO proposal_decisions (user_id, poste_id, ref_year, ref_month, current, proposed, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (g.user_id, poste_id, ry, rm, prop.current, prop.proposed,
         "accepted" if action == "accepter" else "refused"),
    )
    if action == "accepter":
        # Décision de Fred : le nouveau montant s'applique au mois en cours,
        # puis il est copié dans les mois suivants.
        db.execute(
            "UPDATE lines SET planned = ? WHERE month_id = ? AND poste_id = ?",
            (prop.proposed, row["id"], poste_id),
        )
        db.execute("UPDATE postes SET default_planned = ? WHERE id = ?", (prop.proposed, poste_id))
        flash(f"{prop.name} : prévu passé à {rules.format_eur(prop.proposed)}. Pense à ajuster le virement.")
    else:
        flash(f"{prop.name} : proposition refusée.")
    db.commit()
    return redirect(url_for("views.month", year=row["year"], month=row["month"]))


# ---------------------------------------------------------------- analyse


@bp.route("/mois/<int:year>/<int:month>/analyse")
def analysis(year: int, month: int):
    row = _month_or_404(year, month)
    ctx = _context(row)
    db = get_db()
    s = settings()
    m, summary = ctx["m"], ctx["summary"]
    split = rules.split_503020(m, summary, s)
    credits = [
        rules.credit_status(c["name"], c["target_date"], c["balances"], m.idx)
        for c in store.credits_with_balances(db, g.user_id)
    ]
    prev_row = store.previous_month_row(db, g.user_id, year, month)
    prev_summary = rules.summarize(store.load_month(db, prev_row), s) if prev_row else None
    notes = rules.analysis_notes(m, summary, split, credits, prev_summary, len(ctx["proposals"]), s)
    notes += ctx["seasonal"]
    ecarts = sorted((l for l in m.lines if l.diff), key=lambda l: -abs(l.diff))
    return render_template(
        "analysis.html", **ctx, split=split, credits=credits, notes=notes, ecarts=ecarts,
        prev_summary=prev_summary,
    )


# ------------------------------------------------------------- calendrier


@bp.route("/mois/<int:year>/<int:month>/calendrier")
def calendar_view(year: int, month: int):
    row = _month_or_404(year, month)
    ctx = _context(row)
    db = get_db()
    last_day = calendar.monthrange(year, month)[1]
    by_day: dict[int, list] = {}
    undated = []
    for l in ctx["m"].lines:
        if l.is_reserve or not l.planned:
            continue
        if l.debit_day:
            by_day.setdefault(min(l.debit_day, last_day), []).append(l)
        else:
            undated.append(l)
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    cheques = db.execute(
        "SELECT c.*, a.name AS account FROM cheques c LEFT JOIN accounts a ON a.id = c.account_id "
        "WHERE c.user_id = ? AND c.year = ? AND c.month = ? ORDER BY c.status DESC, c.id",
        (g.user_id, year, month),
    ).fetchall()
    pending = sum(c["amount"] for c in cheques if c["status"] == "pending")
    t = date.today()
    return render_template(
        "calendar.html", **ctx, weeks=weeks, by_day=by_day, undated=undated, cheques=cheques,
        cheques_pending=pending, today_day=t.day if (t.year, t.month) == (year, month) else None,
        days=sorted(by_day),
    )


# ---------------------------------------------------------------- chèques


@bp.route("/cheques", methods=["GET", "POST"])
def cheques():
    db = get_db()
    if request.method == "POST":
        amount = _amount("amount", "montant", required=True)
        payee = request.form.get("payee", "").strip()[:120]
        y = request.form.get("year", type=int)
        m = request.form.get("month", type=int)
        if not payee or not y or not m or not (1 <= m <= 12) or not (2000 <= y <= 2100):
            abort(400, "Bénéficiaire et mois prévu sont obligatoires.")
        acc = request.form.get("account_id", type=int)
        if acc and acc not in {a["id"] for a in _accounts()}:
            abort(400)
        db.execute(
            "INSERT INTO cheques (user_id, amount, payee, year, month, note, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (g.user_id, amount, payee, y, m, request.form.get("note", "").strip()[:300], acc or None),
        )
        db.commit()
        flash("Chèque ajouté.")
        return redirect(url_for("views.cheques"))
    rows = db.execute(
        "SELECT c.*, a.name AS account FROM cheques c LEFT JOIN accounts a ON a.id = c.account_id "
        "WHERE c.user_id = ? ORDER BY c.status DESC, c.year DESC, c.month DESC, c.id DESC LIMIT 200",
        (g.user_id,),
    ).fetchall()
    ty, tm = _today_ym()
    return render_template(
        "cheques.html", cheques=rows, accounts=_accounts(), now_idx=month_index(ty, tm),
        month_index=month_index, default_year=ty, default_month=tm,
    )


@bp.route("/cheques/<int:cheque_id>/<action>", methods=["POST"])
def cheque_action(cheque_id: int, action: str):
    db = get_db()
    if action == "debite":
        db.execute("UPDATE cheques SET status = 'debited' WHERE id = ? AND user_id = ?", (cheque_id, g.user_id))
    elif action == "attente":
        db.execute("UPDATE cheques SET status = 'pending' WHERE id = ? AND user_id = ?", (cheque_id, g.user_id))
    elif action == "supprimer":
        db.execute("DELETE FROM cheques WHERE id = ? AND user_id = ?", (cheque_id, g.user_id))
    else:
        abort(404)
    db.commit()
    return redirect(request.form.get("next") if _safe_next(request.form.get("next")) else url_for("views.cheques"))


def _safe_next(target: str | None) -> bool:
    return bool(target) and target.startswith("/") and not target.startswith("//") and "\\" not in target


# ----------------------------------------------------------------- postes


def _poste_form() -> dict:
    name = request.form.get("name", "").strip()[:120]
    account_id = request.form.get("account_id", type=int)
    category = request.form.get("category", "besoins")
    day = request.form.get("debit_day", type=int)
    if not name or category not in rules.CATEGORIES:
        abort(400, "Nom et catégorie sont obligatoires.")
    if account_id not in {a["id"] for a in _accounts()}:
        abort(400, "Compte inconnu.")
    if day is not None and not (1 <= day <= 31):
        abort(400, "Le jour de prélèvement doit être entre 1 et 31.")
    return {
        "name": name, "account_id": account_id, "category": category, "debit_day": day,
        "seasonal": int("seasonal" in request.form), "contractual": int("contractual" in request.form),
    }


@bp.route("/postes", methods=["GET", "POST"])
def postes():
    db = get_db()
    if request.method == "POST":
        f = _poste_form()
        planned = _amount("planned", "montant prévu") or 0
        cur = db.execute(
            "INSERT INTO postes (user_id, name, account_id, category, debit_day, seasonal, contractual, default_planned) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (g.user_id, f["name"], f["account_id"], f["category"], f["debit_day"], f["seasonal"],
             f["contractual"], planned),
        )
        latest = store.latest_month(db, g.user_id)
        if latest:
            db.execute(
                "INSERT INTO lines (month_id, poste_id, planned) VALUES (?, ?, ?)",
                (latest["id"], cur.lastrowid, planned),
            )
        db.commit()
        flash(f"Poste « {f['name']} » ajouté" + (f" au mois de {month_label(latest['year'], latest['month'])}." if latest else "."))
        return redirect(url_for("views.postes"))
    rows = db.execute(
        "SELECT p.*, a.name AS account FROM postes p JOIN accounts a ON a.id = p.account_id "
        "WHERE p.user_id = ? ORDER BY p.active DESC, a.sort, p.is_reserve, p.name COLLATE NOCASE",
        (g.user_id,),
    ).fetchall()
    return render_template("postes.html", postes=rows, accounts=_accounts(), categories=rules.CATEGORIES_LABEL)


@bp.route("/postes/<int:poste_id>", methods=["POST"])
def poste_update(poste_id: int):
    db = get_db()
    p = db.execute("SELECT * FROM postes WHERE id = ? AND user_id = ?", (poste_id, g.user_id)).fetchone()
    if p is None:
        abort(404)
    f = _poste_form()
    active = int("active" in request.form) if not p["is_reserve"] else 1
    db.execute(
        "UPDATE postes SET name = ?, account_id = ?, category = ?, debit_day = ?, seasonal = ?, "
        "contractual = ?, active = ? WHERE id = ?",
        (f["name"], f["account_id"], f["category"], f["debit_day"], f["seasonal"], f["contractual"],
         active, poste_id),
    )
    db.commit()
    flash(f"Poste « {f['name']} » mis à jour.")
    return redirect(url_for("views.postes"))


# ---------------------------------------------------------------- crédits


@bp.route("/credits", methods=["GET", "POST"])
def credits():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:120]
        target = request.form.get("target_date", "").strip() or None
        if not name or (target and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target)):
            abort(400, "Nom obligatoire ; date au format AAAA-MM-JJ.")
        db.execute(
            "INSERT INTO credits (user_id, name, target_date) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, name) DO UPDATE SET target_date = excluded.target_date",
            (g.user_id, name, target),
        )
        db.commit()
        return redirect(url_for("views.credits"))
    ty, tm = _today_ym()
    items = []
    for c in store.credits_with_balances(db, g.user_id):
        st = rules.credit_status(c["name"], c["target_date"], c["balances"], 10**6)
        st["id"] = c["id"]
        st["rows"] = [(from_index(i), b) for i, b in reversed(c["balances"])][:12]
        items.append(st)
    return render_template("credits.html", credits=items, default_year=ty, default_month=tm)


@bp.route("/credits/<int:credit_id>/solde", methods=["POST"])
def credit_balance(credit_id: int):
    db = get_db()
    c = db.execute("SELECT id FROM credits WHERE id = ? AND user_id = ?", (credit_id, g.user_id)).fetchone()
    if c is None:
        abort(404)
    y = request.form.get("year", type=int)
    m = request.form.get("month", type=int)
    if not y or not m or not (1 <= m <= 12) or not (2000 <= y <= 2100):
        abort(400)
    db.execute(
        "INSERT INTO credit_balances (credit_id, year, month, balance) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(credit_id, year, month) DO UPDATE SET balance = excluded.balance",
        (credit_id, y, m, _amount("balance", "reste dû", required=True)),
    )
    db.commit()
    return redirect(url_for("views.credits"))


@bp.route("/credits/<int:credit_id>/supprimer", methods=["POST"])
def credit_delete(credit_id: int):
    db = get_db()
    db.execute("DELETE FROM credits WHERE id = ? AND user_id = ?", (credit_id, g.user_id))
    db.commit()
    return redirect(url_for("views.credits"))


# ---------------------------------------------------------------- erreurs


@bp.app_errorhandler(400)
def bad_request(exc):
    return render_template("error.html", titre="Saisie refusée", message=exc.description), 400


@bp.app_errorhandler(404)
def not_found(_exc):
    return render_template("error.html", titre="Page introuvable", message="Ce mois ou cette page n'existe pas."), 404
