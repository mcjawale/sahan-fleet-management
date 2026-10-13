import csv
import io
from datetime import date

from flask import Blueprint, g, render_template, Response
from app.util import db, guard

bp = Blueprint('export', __name__, url_prefix='/app/<slug>')
guard(bp)


def _summary():
    one = lambda q, p=(): (db().execute(q, p).fetchone()[0] or 0)
    cid = g.company_id
    rev = db().execute('SELECT COALESCE(SUM(revenue_cents),0), COALESCE(SUM(cost_cents),0) FROM trips WHERE company_id=?',
                       (cid,)).fetchone()
    return {
        'vehicles': one('SELECT COUNT(*) FROM vehicles WHERE company_id=?', (cid,)),
        'drivers': one('SELECT COUNT(*) FROM drivers WHERE company_id=? AND is_active=1', (cid,)),
        'routes': one('SELECT COUNT(*) FROM routes WHERE company_id=?', (cid,)),
        'trips': one('SELECT COUNT(*) FROM trips WHERE company_id=?', (cid,)),
        'completed': one("SELECT COUNT(*) FROM trips WHERE company_id=? AND status='completed'", (cid,)),
        'bookings': one('SELECT COUNT(*) FROM bookings WHERE company_id=?', (cid,)),
        'revenue_cents': rev[0] or 0,
        'cost_cents': rev[1] or 0,
        'profit_cents': (rev[0] or 0) - (rev[1] or 0),
        'fuel_cents': one('SELECT COALESCE(SUM(amount_cents),0) FROM fuel_records WHERE company_id=?', (cid,)),
        'maint_cents': one('SELECT COALESCE(SUM(cost_cents),0) FROM maintenance_records WHERE company_id=?', (cid,)),
        'open_maint': one("SELECT COUNT(*) FROM maintenance_records WHERE company_id=? AND status!='done'", (cid,)),
        'distance_km': one('SELECT COALESCE(SUM(distance_km),0) FROM trips WHERE company_id=?', (cid,)),
    }


@bp.route('/reports')
def index(slug):
    cid = g.company_id
    by_status = db().execute('SELECT status, COUNT(*) c FROM trips WHERE company_id=? GROUP BY status', (cid,)).fetchall()
    top_routes = db().execute('''SELECT r.name, COUNT(t.id) c, COALESCE(SUM(t.revenue_cents),0) s
                                 FROM trips t JOIN routes r ON t.route_id=r.id
                                 WHERE t.company_id=? GROUP BY r.id ORDER BY c DESC LIMIT 8''', (cid,)).fetchall()
    monthly = db().execute('''SELECT strftime('%Y-%m', departure_at) m, COUNT(*) c,
                                     COALESCE(SUM(revenue_cents),0) s
                              FROM trips WHERE company_id=? AND departure_at IS NOT NULL
                              GROUP BY m ORDER BY m DESC LIMIT 12''', (cid,)).fetchall()
    return render_template('export/reports.html', summary=_summary(), by_status=by_status,
                           top_routes=top_routes, monthly=monthly)


def _csv(name, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=%s.csv' % name})


@bp.route('/reports/trips.csv')
def trips_csv(slug):
    rows = db().execute('''SELECT t.trip_no,t.departure_at,r.name,v.plate_no,d.name,t.status,t.seats,
                                  t.revenue_cents,t.cost_cents
                           FROM trips t LEFT JOIN routes r ON t.route_id=r.id
                           LEFT JOIN vehicles v ON t.vehicle_id=v.id LEFT JOIN drivers d ON t.driver_id=d.id
                           WHERE t.company_id=? ORDER BY t.id DESC''', (g.company_id,)).fetchall()
    body = [(r['trip_no'], r['departure_at'] or '', r['name'] or '', r['plate_no'] or '', r['dname'] or '',
              r['status'], r['seats'], r['revenue_cents'] / 100, r['cost_cents'] / 100) for r in rows]
    return _csv('trips-%s' % date.today().isoformat(),
                ['trip_no', 'departure_at', 'route', 'vehicle', 'driver', 'status', 'seats', 'revenue', 'cost'], body)


@bp.route('/reports/fuel.csv')
def fuel_csv(slug):
    rows = db().execute('''SELECT f.date,v.plate_no,d.name,f.quantity_l,f.amount_cents,f.odometer,f.notes
                           FROM fuel_records f LEFT JOIN vehicles v ON f.vehicle_id=v.id
                           LEFT JOIN drivers d ON f.driver_id=d.id
                           WHERE f.company_id=? ORDER BY f.date DESC''', (g.company_id,)).fetchall()
    body = [(r['date'], r['plate_no'] or '', r['dname'] or '', r['quantity_l'] or '', r['amount_cents'] / 100,
              r['odometer'] if r['odometer'] is not None else '', r['notes'] or '') for r in rows]
    return _csv('fuel-%s' % date.today().isoformat(),
                ['date', 'vehicle', 'driver', 'litres', 'amount', 'odometer', 'notes'], body)


@bp.route('/reports/vehicles.csv')
def vehicles_csv(slug):
    rows = db().execute('SELECT plate_no,make,model,year,capacity,odometer,status FROM vehicles WHERE company_id=? ORDER BY plate_no',
                        (g.company_id,)).fetchall()
    body = [(r['plate_no'], r['make'] or '', r['model'] or '', r['year'] or '', r['capacity'],
              r['odometer'], r['status']) for r in rows]
    return _csv('vehicles-%s' % date.today().isoformat(),
                ['plate_no', 'make', 'model', 'year', 'capacity', 'odometer', 'status'], body)