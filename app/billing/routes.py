from flask import Blueprint, g, render_template
from tenancy import require_company_admin
from app.util import db, guard
import json

bp = Blueprint('billing', __name__, url_prefix='/app/<slug>')
guard(bp)


def _sub():
    row = db().execute('''SELECT s.*, p.code, p.name, p.price_cents, p.currency, p.max_vehicles,
                                 p.max_users, p.max_trips_per_month, p.features
                          FROM subscriptions s JOIN plans p ON s.plan_id=p.id
                          WHERE s.company_id=? ORDER BY s.id DESC LIMIT 1''', (g.company_id,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    try:
        data['feature_list'] = sorted(json.loads(row['features'] or '{}').keys())
    except ValueError:
        data['feature_list'] = []
    return data


@bp.route('/billing')
@require_company_admin
def index(slug):
    sub = _sub()
    plans = db().execute('SELECT * FROM plans ORDER BY sort_order').fetchall()
    usage = {
        'vehicles': db().execute('SELECT COUNT(*) FROM vehicles WHERE company_id=?', (g.company_id,)).fetchone()[0],
        'users': db().execute('SELECT COUNT(*) FROM users WHERE company_id=? AND is_active=1', (g.company_id,)).fetchone()[0],
        'trips': db().execute("SELECT COUNT(*) FROM trips WHERE company_id=? AND strftime('%Y-%m',created_at)=strftime('%Y-%m','now')",
                              (g.company_id,)).fetchone()[0],
    }
    invoices = db().execute('''SELECT i.number,i.amount_cents,i.currency,i.status,i.period_end
                               FROM invoices i WHERE i.company_id=? ORDER BY i.id DESC LIMIT 12''',
                            (g.company_id,)).fetchall()
    return render_template('billing/index.html', sub=sub, plans=plans, usage=usage, invoices=invoices)