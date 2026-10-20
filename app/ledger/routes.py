from flask import Blueprint, g, render_template, request, redirect, url_for, flash

from app.util import db, guard, form_str, form_money_cents, form_date, owned

bp = Blueprint('ledger', __name__, url_prefix='/app/<slug>')
guard(bp)

LEDGER_KINDS = ('income', 'expense')
LEDGER_CATEGORIES = {
    'income': ('Trip income', 'Booking fare', 'Rental', 'Other income'),
    'expense': ('Fuel', 'Maintenance', 'Salary', 'Office', 'Insurance', 'Other expense'),
}


def _month_shift(ym, delta):
    year, month = int(ym[:4]), int(ym[5:7])
    month += delta
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1
    return '%04d-%02d' % (year, month)


def _month_label(ym):
    import datetime
    try:
        return datetime.datetime.strptime(ym, '%Y-%m').strftime('%B %Y')
    except ValueError:
        return ym


def _vehicles():
    return db().execute('SELECT id,plate_no FROM vehicles WHERE company_id=? ORDER BY plate_no',
                        (g.company_id,)).fetchall()


@bp.route('/accounting')
def accounting(slug):
    import datetime
    month = (request.args.get('month') or '').strip()
    try:
        datetime.datetime.strptime(month, '%Y-%m')
    except ValueError:
        month = datetime.date.today().strftime('%Y-%m')
    kind = (request.args.get('kind') or '').strip()
    if kind not in LEDGER_KINDS:
        kind = None

    totals = db().execute('''SELECT
          COALESCE(SUM(CASE WHEN kind='income'  THEN amount_cents END),0) AS income_cents,
          COALESCE(SUM(CASE WHEN kind='expense' THEN amount_cents END),0) AS expense_cents
          FROM ledger_entries WHERE company_id=? AND strftime('%Y-%m', entry_date)=?''',
                          (g.company_id, month)).fetchone()

    sql = '''SELECT e.*, v.plate_no FROM ledger_entries e
             LEFT JOIN vehicles v ON e.vehicle_id=v.id
             WHERE e.company_id=? AND strftime('%Y-%m', e.entry_date)=?'''
    params = [g.company_id, month]
    if kind:
        sql += ' AND e.kind=?'
        params.append(kind)
    sql += ' ORDER BY e.entry_date DESC, e.id DESC LIMIT 500'
    rows = db().execute(sql, params).fetchall()

    months = db().execute('''SELECT strftime('%Y-%m', entry_date) AS ym,
             COALESCE(SUM(CASE WHEN kind='income'  THEN amount_cents END),0) AS income_cents,
             COALESCE(SUM(CASE WHEN kind='expense' THEN amount_cents END),0) AS expense_cents
             FROM ledger_entries
             WHERE company_id=? AND entry_date >= date('now','-11 months','start of month')
             GROUP BY ym ORDER BY ym DESC''', (g.company_id,)).fetchall()

    by_category = db().execute('''SELECT kind, category,
             COALESCE(SUM(amount_cents),0) AS total_cents
             FROM ledger_entries WHERE company_id=? AND strftime('%Y-%m', entry_date)=?
             GROUP BY kind, category ORDER BY total_cents DESC''',
                               (g.company_id, month)).fetchall()

    return render_template('ledger/accounting.html',
                           rows=rows, totals=totals, months=months, by_category=by_category,
                           month=month, month_label=_month_label(month),
                           prev_month=_month_shift(month, -1),
                           next_month=_month_shift(month, 1),
                           kind=kind, kinds=LEDGER_KINDS)


@bp.route('/accounting/new', methods=['GET', 'POST'])
def accounting_new(slug):
    return _form(slug)


@bp.route('/accounting/<int:eid>/edit', methods=['GET', 'POST'])
def accounting_edit(slug, eid):
    return _form(slug, eid)


def _form(slug, eid=None):
    row = owned('ledger_entries', eid) if eid is not None else None
    if request.method == 'POST':
        kind = request.form.get('kind')
        if kind not in LEDGER_KINDS:
            kind = 'income'
        category = form_str('category', maxlen=50)
        if category not in LEDGER_CATEGORIES[kind]:
            category = LEDGER_CATEGORIES[kind][-1]
        description = form_str('description', maxlen=200)
        amount = form_money_cents('amount')
        entry_date = form_date('date')
        vehicle_id = _pick('vehicles', request.form.get('vehicle_id'))
        if not description:
            flash('Add a short description', 'error')
        elif amount <= 0:
            flash('Enter an amount greater than zero', 'error')
        else:
            if row is None:
                db().execute('''INSERT INTO ledger_entries
                                (company_id,kind,category,description,amount_cents,entry_date,vehicle_id,created_by)
                                VALUES (?,?,?,?,?,?,?,?)''',
                             (g.company_id, kind, category, description, amount,
                              entry_date, vehicle_id, g.user_id))
                flash('Entry saved', 'ok')
            else:
                db().execute('''UPDATE ledger_entries
                                SET kind=?,category=?,description=?,amount_cents=?,entry_date=?,vehicle_id=?
                                WHERE id=? AND company_id=?''',
                             (kind, category, description, amount, entry_date,
                              vehicle_id, eid, g.company_id))
                flash('Entry updated', 'ok')
            db().commit()
            return redirect(url_for('ledger.accounting', slug=slug))
    return render_template('ledger/accounting_form.html', row=row, vehicles=_vehicles(),
                           kinds=LEDGER_KINDS, categories=LEDGER_CATEGORIES)


@bp.route('/accounting/<int:eid>/delete', methods=['POST'])
def accounting_delete(slug, eid):
    owned('ledger_entries', eid)
    db().execute('DELETE FROM ledger_entries WHERE id=? AND company_id=?', (eid, g.company_id))
    db().commit()
    flash('Entry deleted', 'ok')
    return redirect(url_for('ledger.accounting', slug=slug))


def _pick(table, value):
    try:
        num = int(value)
    except (TypeError, ValueError):
        return None
    if db().execute('SELECT id FROM %s WHERE id=? AND company_id=?' % table, (num, g.company_id)).fetchone():
        return num
    return None
