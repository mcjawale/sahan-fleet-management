from flask import Blueprint, render_template, g, url_for
from tenancy import require_auth

bp = Blueprint('dashboard', __name__, url_prefix='/app/<slug>')

@bp.before_request
def ensure_auth():
    if not g.user:
        from flask import redirect, request
        return redirect(url_for('auth.login', next=request.url))

@bp.route('/')
def index(slug):
    db = __import__('app').get_db()
    cid = g.company_id
    def count(q, *p):
        params = p[0] if (len(p) == 1 and isinstance(p[0], (tuple, list))) else p
        return db.execute(q, params).fetchone()[0] or 0
    fleet = count('SELECT COUNT(*) FROM vehicles WHERE company_id=?', (cid,))
    active_trips = count("SELECT COUNT(*) FROM trips WHERE company_id=? AND status IN ('scheduled','in transit')", (cid,))
    pending_b = count("SELECT COUNT(*) FROM bookings WHERE company_id=? AND status='booked'", (cid,))
    rev = db.execute('SELECT COALESCE(SUM(revenue_cents),0) as s, COALESCE(SUM(cost_cents),0) as c FROM trips WHERE company_id=?', (cid,)).fetchone()
    profit_cents = (rev['s'] or 0) - (rev['c'] or 0)
    fuel_mtd = count("SELECT COALESCE(SUM(amount_cents),0) FROM fuel_records WHERE company_id=? AND strftime('%Y-%m', date)=strftime('%Y-%m','now')", (cid,))
    drivers_ready = count("SELECT COUNT(*) FROM drivers WHERE company_id=? AND is_active=1", (cid,))
    maint_open = count("SELECT COUNT(*) FROM maintenance_records WHERE company_id=? AND status!='done'", (cid,))
    recent = db.execute('''SELECT t.trip_no,t.departure_at,r.name as rname,v.plate_no,d.name as dname,t.status,t.seats
                            FROM trips t LEFT JOIN vehicles v ON t.vehicle_id=v.id LEFT JOIN drivers d ON t.driver_id=d.id
                            LEFT JOIN routes r ON t.route_id=r.id WHERE t.company_id=? ORDER BY t.id DESC LIMIT 5''', (cid,)).fetchall()
    upcoming = db.execute('''SELECT t.trip_no,t.departure_at,v.plate_no,d.name as dname,t.seats FROM trips t
                            LEFT JOIN vehicles v ON t.vehicle_id=v.id LEFT JOIN drivers d ON t.driver_id=d.id
                            WHERE t.company_id=? AND t.status IN ('scheduled','in transit') ORDER BY t.departure_at ASC LIMIT 5''', (cid,)).fetchall()
    fuel_top = db.execute('''SELECT COALESCE(v.plate_no,'-') as p, COALESCE(SUM(f.amount_cents),0) as s
                              FROM fuel_records f LEFT JOIN vehicles v ON f.vehicle_id=v.id
                              WHERE f.company_id=? AND f.date >= date('now','-30 day') GROUP BY f.vehicle_id,v.plate_no ORDER BY s DESC LIMIT 5''', (cid,)).fetchall()
    maint_alerts = db.execute('''SELECT v.plate_no,m.work,m.status,m.next_due FROM maintenance_records m
                                 LEFT JOIN vehicles v ON m.vehicle_id=v.id WHERE m.company_id=? AND m.status!='done'
                                 ORDER BY m.id DESC LIMIT 5''', (cid,)).fetchall()
    comp = db.execute("SELECT COALESCE(v.status,'available') as st, COUNT(*) as c FROM vehicles v WHERE v.company_id=? GROUP BY st", (cid,)).fetchall()
    ledger = db.execute('''SELECT
          COALESCE(SUM(CASE WHEN kind='income'  THEN amount_cents END),0) AS income_cents,
          COALESCE(SUM(CASE WHEN kind='expense' THEN amount_cents END),0) AS expense_cents
          FROM ledger_entries WHERE company_id=? AND strftime('%Y-%m', entry_date)=strftime('%Y-%m','now')''',
                        (cid,)).fetchone()
    return render_template('dashboard/index.html',
        fleet=fleet, active_trips=active_trips, pending_b=pending_b,
        profit_cents=profit_cents, rev_cents=rev['s'] or 0, cost_cents=rev['c'] or 0,
        fuel_mtd=fuel_mtd, drivers_ready=drivers_ready, maint_open=maint_open,
        ledger_income=ledger['income_cents'], ledger_expense=ledger['expense_cents'],
        recent=recent, upcoming=upcoming, fuel_top=fuel_top, maint_alerts=maint_alerts, comp=comp)
