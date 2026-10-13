"""Small shared helpers for the company scoped CRUD blueprints."""
import re
from flask import g, redirect, request, url_for
from werkzeug.exceptions import abort

from tenancy import require_auth


def db():
    from app import get_db
    return get_db()


def guard(bp):
    """Attach the standard auth + tenancy guard to a blueprint."""
    @bp.before_request
    @require_auth
    def _guard():
        if g.company is None:
            abort(403)
        if g.user['role'] not in ('owner', 'admin', 'staff'):
            abort(403)
    return bp


def form_str(name, default='', maxlen=200):
    value = request.form.get(name, default)
    return (value or '').strip()[:maxlen]


def form_int(name, default=0, minimum=None, maximum=None):
    raw = (request.form.get(name) or '').strip()
    try:
        value = int(float(raw)) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def form_money_cents(name, default=0):
    """Accepts '1,250.50' or '1250' and returns integer cents."""
    raw = (request.form.get(name) or '').strip().replace(',', '')
    try:
        return int(round(float(raw) * 100)) if raw else default
    except ValueError:
        return default


def form_date(name, default=None):
    """Return an ISO date string, falling back to today.

    The schema declares these columns NOT NULL DEFAULT (date('now')), so an
    explicit NULL would fail instead of using the default.
    """
    import datetime
    raw = (request.form.get(name) or '').strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}', raw):
        return raw[:10]
    if default:
        return default
    return datetime.date.today().isoformat()


def form_choice(name, allowed, default):
    value = (request.form.get(name) or '').strip()
    return value if value in allowed else default


def next_no(conn, table, column, cid, prefix):
    """Generate TRIP-2026-0001 style sequential numbers per company."""
    import datetime
    year = datetime.date.today().year
    like = '%s-%d-%%' % (prefix, year)
    row = conn.execute(
        'SELECT %s FROM %s WHERE company_id=? AND %s LIKE ? ORDER BY %s DESC LIMIT 1'
        % (column, table, column, column), (cid, like)).fetchone()
    seq = 0
    if row:
        m = re.search(r'(\d+)$', row[0] or '')
        if m:
            seq = int(m.group(1))
    return '%s-%d-%04d' % (prefix, year, seq + 1)


def owned(table, item_id, key='id'):
    """Fetch a row scoped to the signed in company or abort 404."""
    row = db().execute('SELECT * FROM %s WHERE %s=? AND company_id=?' % (table, key),
                       (item_id, g.company_id)).fetchone()
    if row is None:
        abort(404)
    return row


def choices(query, params=()):
    return db().execute(query, params).fetchall()


def back_to(endpoint, **kw):
    flash_kw = dict(slug=g.company.slug)
    flash_kw.update(kw)
    return redirect(url_for(endpoint, **flash_kw))