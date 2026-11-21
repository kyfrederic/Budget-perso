"""Écrans de la V1."""
from __future__ import annotations

import calendar
import re
from datetime import date

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template,
                   request, url_for)

from . import receipt, rules, store
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
    # Postes rangés par catégorie (charges fixes, envies, épargne) ; le matelas à part.
    budget_hors_matelas = sum(l.planned for l in ctx["m"].lines if not l.is_reserve) or 1
    cat_groups = []
    for key in rules.CATEGORIES:
        ls = [l for l in ctx["m"].lines if l.category == key and not l.is_reserve]
        if ls:
            total = sum(l.planned for l in ls)
            cat_groups.append({"key": key, "label": rules.CATEGORIES_LABEL[key], "lines": ls,
                               "total": total, "pct": total * 100 / budget_hors_matelas})
    reserve_lines = [l for l in ctx["m"].lines if l.is_reserve]
    done = store.transfers_done(db, row["id"])
    # Ce que je dois : reste dû de chaque crédit au mois affiché (dernier solde connu).
    debts = [
        rules.credit_status(c["name"], c["target_date"], c["balances"], ctx["m"].idx)
        for c in store.credits_with_balances(db, g.user_id)
    ]
    debts = [d for d in debts if d["balance"] is not None and (d["balance"] > 0 or d["target_date"])]
    debts.sort(key=lambda d: (d["balance"] <= 0, -d["balance"]))   # soldés en dernier
    month_delta = sum(d["delta"] for d in debts if d["delta"] and d["balance"] > 0)
    state = _transfer_state(ctx["summary"], row["salary_net"], done)
    progress = [l for l in ctx["m"].lines if l.diff is not None]
    return render_template(
        "month.html", **ctx, cat_groups=cat_groups, reserve_lines=reserve_lines, cheques=cheques,
        done=done, **state,
        debts=debts, debt_total=sum(max(d["balance"], 0) for d in debts), debt_delta=month_delta,
        purchases=store.purchases(db, row["id"]),
        stays=[v for v in ctx["summary"].virements if v.kind == "reste"],
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


def _transfer_state(summary, salary: int | None, done: set) -> dict:
    """Où en sont les virements du mois, et ce qu'il reste du salaire à cet instant.

    Reste = salaire − virements cochés. Le virement de fin de mois (reste du matelas)
    ne part pas du salaire : il n'est pas compté. Le compte du salaire ne reçoit pas
    de virement : ce qui lui revient y reste.
    """
    todo = [v for v in summary.virements if v.kind != "reste"]
    sent = sum(v.amount for v in todo if (v.account, "debut") in done)
    total = sum(v.amount for v in todo)
    return {
        "todo": todo,
        "n_left": sum(1 for v in todo if (v.account, "debut") not in done),
        "sent": sent,
        "to_send": total,
        "remaining": None if salary is None else salary - sent,
        "remaining_end": None if salary is None else salary - total,
    }


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
        m = store.load_month(db, row)
        st = _transfer_state(rules.summarize(m, settings()), row["salary_net"], store.transfers_done(db, row["id"]))
        return {"done": is_done, "left": st["n_left"], "sent": st["sent"], "remaining": st["remaining"]}
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
        "INSERT INTO lines (month_id, poste_id, planned) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
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


# ------------------------------------------------------------------ achats


def _iso_date(text: str | None) -> str | None:
    if not text or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


@bp.route("/mois/<int:year>/<int:month>/achat/photo", methods=["POST"])
def purchase_photo(year: int, month: int):
    """Reçoit la photo d'un ticket, la lit, puis ouvre le formulaire pré-rempli."""
    _month_or_404(year, month)
    f = request.files.get("photo")
    if f is None or not f.filename:
        abort(400, "Aucune photo reçue.")
    try:
        img = receipt.prepare(f.read(receipt.MAX_BYTES + 1))
    except receipt.ReceiptError as exc:
        abort(400, str(exc))
    db = get_db()
    store.purge_photos(db)
    token = store.save_photo(db, receipt.encode(img))
    db.commit()
    # Texte déjà lu dans le navigateur (tesseract.js) ; sinon lecture sur le serveur si possible.
    text = request.form.get("ocr_text", "")[:20000]
    if text.strip():
        r = receipt.extract(text)
    elif "ocr_tried" in request.form:
        r = receipt.Reading()                     # le navigateur a essayé et n'a rien lu
    else:
        r = receipt.ocr(img)
    args = {"photo": token, "lu": "absent" if not r.available else ("oui" if r.amount else "non")}
    if r.amount:
        args["montant"] = r.amount
    if r.bought_on:
        args["date"] = r.bought_on
    if r.label:
        args["libelle"] = r.label
    return redirect(url_for("views.purchase", year=year, month=month, **args))


@bp.route("/mois/<int:year>/<int:month>/achat", methods=["GET", "POST"])
def purchase(year: int, month: int):
    row = _month_or_404(year, month)
    db = get_db()
    m = store.load_month(db, row)
    lines = [l for l in m.lines if not l.is_reserve]
    if request.method == "POST":
        label = request.form.get("label", "").strip()[:120]
        amount = _amount("amount", "montant", required=True)
        if not label or amount <= 0:
            abort(400, "Il faut un libellé et un montant supérieur à zéro.")
        target = request.form.get("target", "matelas")
        poste_id = None
        if target != "matelas":
            poste_id = next((l.poste_id for l in lines if f"poste:{l.poste_id}" == target), None)
            if poste_id is None:
                abort(400, "Poste inconnu pour ce mois.")
        token = request.form.get("photo") or None
        if token and not store.photo_exists(db, token):
            token = None
        category = "besoins" if "besoin" in request.form else "envies"
        try:
            store.add_purchase(db, row["id"], label, amount, _iso_date(request.form.get("bought_on")),
                               poste_id, category, token)
        except ValueError as exc:
            abort(400, str(exc))
        db.commit()
        if poste_id is None:
            flash(f"{label} : {rules.format_eur(amount)} pris sur le matelas.")
        else:
            name = next(l.name for l in lines if l.poste_id == poste_id)
            flash(f"{label} : {rules.format_eur(amount)} ajoutés à {name}.")
        return redirect(url_for("views.month", year=year, month=month) + "#achats")

    token = request.args.get("photo")
    if not store.photo_exists(db, token):
        token = None
    today = date.today()
    default_day = today if (today.year, today.month) == (year, month) else date(year, month, 1)
    groups: dict[str, list] = {}
    for l in lines:
        groups.setdefault(l.account, []).append(l)
    summary = rules.summarize(m, settings())
    return render_template(
        "purchase.html", row=row, m=m, groups=groups, summary=summary, photo=token,
        read=request.args.get("lu") if token else None,
        amount=request.args.get("montant", type=int),
        label=(request.args.get("libelle") or "")[:120],
        bought_on=_iso_date(request.args.get("date")) or default_day.isoformat(),
    )


@bp.route("/achats/<int:purchase_id>/supprimer", methods=["POST"])
def purchase_delete(purchase_id: int):
    db = get_db()
    pu = store.delete_purchase(db, purchase_id, g.user_id)
    if pu is None:
        abort(404)
    store.delete_photo(db, pu["photo"])
    db.commit()
    mrow = db.execute("SELECT year, month FROM months WHERE id = ?", (pu["month_id"],)).fetchone()
    flash(f"{pu['label']} supprimé.")
    return redirect(url_for("views.month", year=mrow["year"], month=mrow["month"]) + "#achats")


@bp.route("/tickets/<token>.jpg")
def ticket_photo(token: str):
    """Photo d'un ticket : jamais servie en fichier statique, connexion exigée."""
    data = store.photo(get_db(), token)
    if data is None:
        abort(404)
    resp = Response(data, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


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
        if l.is_reserve:
            continue
        if l.debit_day:                       # daté : toujours affiché, même à 0 €
            by_day.setdefault(min(l.debit_day, last_day), []).append(l)
        elif l.planned:
            undated.append(l)
    day_totals = {d: sum(l.planned for l in ls) for d, ls in by_day.items()}
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
        days=sorted(by_day), day_totals=day_totals,
        weekday={d: calendar.weekday(year, month, d) for d in by_day}, month_total=sum(day_totals.values()),
        n_debits=sum(len(ls) for ls in by_day.values()),
    )


@bp.route("/mois/<int:year>/<int:month>/calendrier/jours", methods=["POST"])
def calendar_days(year: int, month: int):
    """Fixe d'un coup le jour de prélèvement de plusieurs postes (vaut pour tous les mois)."""
    _month_or_404(year, month)
    db = get_db()
    own = {r["id"] for r in db.execute("SELECT id FROM postes WHERE user_id = ?", (g.user_id,))}
    updates = []
    for key, value in request.form.items():
        if not key.startswith("day_") or not value.strip():
            continue
        try:
            poste_id, day = int(key[4:]), int(value)
        except ValueError:
            abort(400, "Le jour de prélèvement doit être un nombre entre 1 et 31.")
        if poste_id not in own:
            abort(400, "Poste inconnu.")
        if not 1 <= day <= 31:
            abort(400, "Le jour de prélèvement doit être entre 1 et 31.")
        updates.append((day, poste_id))
    for day, poste_id in updates:
        db.execute("UPDATE postes SET debit_day = ? WHERE id = ?", (day, poste_id))
    db.commit()
    if updates:
        flash(f"{len(updates)} jour{'s' if len(updates) > 1 else ''} de prélèvement enregistré{'s' if len(updates) > 1 else ''}.")
    return redirect(url_for("views.calendar_view", year=year, month=month))


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
        "WHERE p.user_id = ? ORDER BY p.is_reserve, p.active DESC, LOWER(p.name)",
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
    message = f"Poste « {f['name']} » mis à jour."
    latest = store.latest_month(db, g.user_id)
    if active and not p["active"] and latest:
        # Réactivé : il rejoint tout de suite le budget du mois le plus récent, avec son
        # dernier montant prévu connu (les mois suivants le reprendront ensuite d'eux-mêmes).
        last = db.execute(
            "SELECT l.planned FROM lines l JOIN months m ON m.id = l.month_id "
            "WHERE l.poste_id = ? AND l.planned > 0 ORDER BY m.year DESC, m.month DESC LIMIT 1",
            (poste_id,),
        ).fetchone()
        planned = last["planned"] if last else p["default_planned"]
        cur = db.execute(
            "INSERT INTO lines (month_id, poste_id, planned) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            (latest["id"], poste_id, planned),
        )
        if cur.rowcount:
            message = (f"Poste « {f['name']} » réactivé et ajouté au budget de "
                       f"{month_label(latest['year'], latest['month'])}.")
    db.commit()
    flash(message)
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
    # En cours d'abord (du plus gros au plus petit), soldés et sans solde ensuite.
    items.sort(key=lambda c: (not (c["balance"] or 0) > 0, -(c["balance"] or 0)))
    total = sum(c["balance"] for c in items if c["balance"] and c["balance"] > 0)
    return render_template("credits.html", credits=items, total=total, default_year=ty, default_month=tm)


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
