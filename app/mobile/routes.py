"""Mobile (PWA) front end for the MCJ Sahan Fleet Management System.

Mounted at /m. Uses the same session cookie and the same credential check as
the desktop site, so one company code + username + password signs in to both.
"""
from flask import Blueprint, g, render_template, request, redirect, url_for, flash, abort

from tenancy import require_auth
from app.auth import service
from app.util import (db, form_str, form_int, form_money_cents, form_date, owned, next_no)

bp = Blueprint('mobile', __name__, url_prefix='/m')

TRIP_STATUS = ('scheduled', 'in transit', 'completed', 'cancelled')
BOOKING_STATUS = ('booked', 'cancelled', 'completed')
MAINT_STATUS = ('open', 'in progress', 'done')
VEHICLE_STATUS = ('available', 'in service', 'maintenance', 'retired')


@bp.before_request
def load_company():
    """Mobile URLs carry no slug, so resolve the company from the session."""
    g.url_company = g.company


def _wants_json():
    return request.headers.get('X-Requested-With') == 'fetch' or request.accept_mimetypes.best == 'application/json'


def _pick(table, value):
    try:
        num = int(value)
    except (TypeError, ValueError):
        return None
    if db().execute('SELECT id FROM %s WHERE id=? AND company_id=?' % table, (num, g.company_id)).fetchone():
        return num
    return None


def _flash_json(message, category='ok'):
    if _wants_json():
        return {'ok': category != 'error', 'message': message}
    flash(message, category)
    return None


# --------------------------------------------------------------------------
# Sign in / out
# --------------------------------------------------------------------------

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if g.user and g.company:
        return redirect(url_for('mobile.index'))

    company_ref = (request.values.get('company') or '').strip()
    identifier = (request.values.get('username') or '').strip()

    if request.method == 'POST':
        status, row, message = service.authenticate(
            company_ref, identifier, request.values.get('password', ''))
        if status == service.OK:
            service.log_in(row['user_id'])
            nxt = request.args.get('next')
            return redirect(nxt or url_for('mobile.index'))
        flash(message, 'error')
        return render_template('mobile/login.html', company_ref=company_ref, identifier=identifier), 401

    return render_template('mobile/login.html', company_ref=company_ref, identifier=identifier)


@bp.route('/logout', methods=['GET', 'POST'])
def logout():
    from flask import session
    session.clear()
    return redirect(url_for('mobile.login'))


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

@bp.route('/')
@require_auth
def index():
    if g.company is None:
        abort(403)
    conn = db()
    cid = g.company_id
    one = lambda q: conn.execute(q, (cid,)).fetchone()[0] or 0

    summary = {
        'vehicles': one('SELECT COUNT(*) FROM vehicles WHERE company_id=?'),
        'available': one("SELECT COUNT(*) FROM vehicles WHERE company_id=? AND status='available'"),
        'in_service': one("SELECT COUNT(*) FROM vehicles WHERE company_id=? AND status='in service'"),
        'maintenance': one("SELECT COUNT(*) FROM vehicles WHERE company_id=? AND status='maintenance'"),
        'drivers': one('SELECT COUNT(*) FROM drivers WHERE company_id=? AND is_active=1'),
        'trips_live': one("SELECT COUNT(*) FROM trips WHERE company_id=? AND status IN ('scheduled','in transit')"),
        'bookings': one("SELECT COUNT(*) FROM bookings WHERE company_id=? AND status='booked'"),
        'maint_open': one("SELECT COUNT(*) FROM maintenance_records WHERE company_id=? AND status!='done'"),
    }
    rev = conn.execute('''SELECT COALESCE(SUM(revenue_cents),0) s, COALESCE(SUM(cost_cents),0) c
                          FROM trips WHERE company_id=?''', (cid,)).fetchone()
    summary['profit_cents'] = (rev['s'] or 0) - (rev['c'] or 0)
    summary['revenue_cents'] = rev['s'] or 0
    summary['fuel_mtd'] = one("SELECT COALESCE(SUM(amount_cents),0) FROM fuel_records WHERE company_id=? AND strftime('%Y-%m',date)=strftime('%Y-%m','now')")

    live = conn.execute('''SELECT t.id,t.trip_no,t.status,t.seats,t.departure_at,v.plate_no,d.name dname,r.name rname
                           FROM trips t LEFT JOIN vehicles v ON t.vehicle_id=v.id
                           LEFT JOIN drivers d ON t.driver_id=d.id LEFT JOIN routes r ON t.route_id=r.id
                           WHERE t.company_id=? AND t.status IN ('scheduled','in transit')
                           ORDER BY t.departure_at IS NULL, t.departure_at LIMIT 20''', (cid,)).fetchall()
    alerts = conn.execute('''SELECT m.id,m.work,m.status,m.next_due,v.plate_no FROM maintenance_records m
                             LEFT JOIN vehicles v ON m.vehicle_id=v.id
                             WHERE m.company_id=? AND m.status!='done' ORDER BY m.id DESC LIMIT 10''', (cid,)).fetchall()
    return render_template('mobile/index.html', summary=summary, live=live, alerts=alerts)


# --------------------------------------------------------------------------
# Vehicles
# --------------------------------------------------------------------------

@bp.route('/vehicles')
@require_auth
def vehicles():
    if g.company is None:
        abort(403)
    rows = db().execute('SELECT * FROM vehicles WHERE company_id=? ORDER BY plate_no', (g.company_id,)).fetchall()
    return render_template('mobile/vehicles.html', rows=rows)


@bp.route('/vehicles/new', methods=['GET', 'POST'])
@require_auth
def vehicles_new():
    if g.company is None:
        abort(403)
    if request.method == 'POST':
        plate = form_str('plate_no', maxlen=32)
        status = request.form.get('status') if request.form.get('status') in VEHICLE_STATUS else 'available'
        if not plate:
            message = 'Plate number is required'
        elif db().execute('SELECT id FROM vehicles WHERE company_id=? AND lower(plate_no)=lower(?)',
                          (g.company_id, plate)).fetchone():
            message = 'That plate number already exists'
        else:
            db().execute('''INSERT INTO vehicles (company_id,plate_no,make,model,year,capacity,odometer,status)
                            VALUES (?,?,?,?,?,?,?,?)''',
                         (g.company_id, plate, form_str('make', maxlen=60) or None,
                          form_str('model', maxlen=60) or None, form_int('year', 0, 1900, 2100),
                          form_int('capacity', 0, 0, 200), form_int('odometer', 0, 0), status))
            db().commit()
            if _wants_json():
                return _flash_json('Vehicle %s added' % plate)
            flash('Vehicle %s added' % plate, 'ok')
            return redirect(url_for('mobile.vehicles'))
        if _wants_json():
            return _flash_json(message, 'error')
        flash(message, 'error')
    return render_template('mobile/vehicle_form.html', row=None, statuses=VEHICLE_STATUS)


@bp.route('/vehicles/<int:vid>/edit', methods=['GET', 'POST'])
@require_auth
def vehicles_edit(vid):
    if g.company is None:
        abort(403)
    row = owned('vehicles', vid)
    if request.method == 'POST':
        plate = form_str('plate_no', maxlen=32)
        clash = db().execute('SELECT id FROM vehicles WHERE company_id=? AND lower(plate_no)=lower(?) AND id!=?',
                             (g.company_id, plate, vid)).fetchone()
        if not plate:
            message = 'Plate number is required'
        elif clash:
            message = 'That plate number already exists'
        else:
            status = request.form.get('status')
            db().execute('''UPDATE vehicles SET plate_no=?,make=?,model=?,year=?,capacity=?,odometer=?,status=?
                            WHERE id=? AND company_id=?''',
                         (plate, form_str('make', maxlen=60) or None, form_str('model', maxlen=60) or None,
                          form_int('year', 0, 1900, 2100), form_int('capacity', 0, 0, 200),
                          form_int('odometer', 0, 0), status if status in VEHICLE_STATUS else 'available',
                          vid, g.company_id))
            db().commit()
            if _wants_json():
                return _flash_json('Vehicle updated')
            flash('Vehicle updated', 'ok')
            return redirect(url_for('mobile.vehicles'))
        if _wants_json():
            return _flash_json(message, 'error')
        flash(message, 'error')
    return render_template('mobile/vehicle_form.html', row=row, statuses=VEHICLE_STATUS)


# --------------------------------------------------------------------------
# Drivers
# --------------------------------------------------------------------------

@bp.route('/drivers')
@require_auth
def drivers():
    if g.company is None:
        abort(403)
    rows = db().execute('SELECT * FROM drivers WHERE company_id=? ORDER BY name', (g.company_id,)).fetchall()
    return render_template('mobile/drivers.html', rows=rows)


@bp.route('/drivers/new', methods=['GET', 'POST'])
@require_auth
def drivers_new():
    if g.company is None:
        abort(403)
    if request.method == 'POST':
        name = form_str('name', maxlen=120)
        if not name:
            message = 'Driver name is required'
        else:
            db().execute('''INSERT INTO drivers (company_id,name,phone,licence_no,licence_expiry,is_active)
                            VALUES (?,?,?,?,?,1)''',
                         (g.company_id, name, form_str('phone', maxlen=40) or None,
                          form_str('licence_no', maxlen=60) or None, form_str('licence_expiry', maxlen=20) or None))
            db().commit()
            if _wants_json():
                return _flash_json('Driver %s added' % name)
            flash('Driver %s added' % name, 'ok')
            return redirect(url_for('mobile.drivers'))
        if _wants_json():
            return _flash_json(message, 'error')
        flash(message, 'error')
    return render_template('mobile/driver_form.html', row=None)


@bp.route('/drivers/<int:did>/edit', methods=['GET', 'POST'])
@require_auth
def drivers_edit(did):
    if g.company is None:
        abort(403)
    row = owned('drivers', did)
    if request.method == 'POST':
        name = form_str('name', maxlen=120)
        if not name:
            message = 'Driver name is required'
        else:
            db().execute('''UPDATE drivers SET name=?,phone=?,licence_no=?,licence_expiry=?,is_active=?
                            WHERE id=? AND company_id=?''',
                         (name, form_str('phone', maxlen=40) or None, form_str('licence_no', maxlen=60) or None,
                          form_str('licence_expiry', maxlen=20) or None,
                          1 if request.form.get('is_active') else 0, did, g.company_id))
            db().commit()
            if _wants_json():
                return _flash_json('Driver updated')
            flash('Driver updated', 'ok')
            return redirect(url_for('mobile.drivers'))
        if _wants_json():
            return _flash_json(message, 'error')
        flash(message, 'error')
    return render_template('mobile/driver_form.html', row=row)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@bp.route('/routes')
@require_auth
def routes():
    if g.company is None:
        abort(403)
    rows = db().execute('SELECT * FROM routes WHERE company_id=? ORDER BY name', (g.company_id,)).fetchall()
    return render_template('mobile/routes.html', rows=rows)


@bp.route('/routes/new', methods=['GET', 'POST'])
@require_auth
def routes_new():
    if g.company is None:
        abort(403)
    if request.method == 'POST':
        name = form_str('name', maxlen=120)
        if not name:
            message = 'Route name is required'
        elif db().execute('SELECT id FROM routes WHERE company_id=? AND lower(name)=lower(?)',
                          (g.company_id, name)).fetchone():
            message = 'That route already exists'
        else:
            db().execute('''INSERT INTO routes (company_id,name,origin,destination,distance_km)
                            VALUES (?,?,?,?,?)''',
                         (g.company_id, name, form_str('origin', maxlen=120) or None,
                          form_str('dropoff', maxlen=120) or form_str('destination', maxlen=120) or None,
                          form_int('distance_km', 0, 0)))
            db().commit()
            if _wants_json():
                return _flash_json('Route %s added' % name)
            flash('Route %s added' % name, 'ok')
            return redirect(url_for('mobile.routes'))
        if _wants_json():
            return _flash_json(message, 'error')
        flash(message, 'error')
    return render_template('mobile/route_form.html', row=None)


@bp.route('/routes/<int:rid>/edit', methods=['GET', 'POST'])
@require_auth
def routes_edit(rid):
    if g.company is None:
        abort(403)
    row = owned('routes', rid)
    if request.method == 'POST':
        name = form_str('name', maxlen=120)
        clash = db().execute('SELECT id FROM routes WHERE company_id=? AND lower(name)=lower(?) AND id!=?',
                             (g.company_id, name, rid)).fetchone()
        if not name:
            message = 'Route name is required'
        elif clash:
            message = 'That route already exists'
        else:
            db().execute('''UPDATE routes SET name=?,origin=?,destination=?,distance_km=?
                            WHERE id=? AND company_id=?''',
                         (name, form_str('origin', maxlen=120) or None,
                          form_str('destination', maxlen=120) or None, form_int('distance_km', 0, 0),
                          rid, g.company_id))
            db().commit()
            if _wants_json():
                return _flash_json('Route updated')
            flash('Route updated', 'ok')
            return redirect(url_for('mobile.routes'))
        if _wants_json():
            return _flash_json(message, 'error')
        flash(message, 'error')
    return render_template('mobile/route_form.html', row=row)


# --------------------------------------------------------------------------
# Trips
# --------------------------------------------------------------------------

def _refs():
    return {
        'vehicles': db().execute('SELECT id,plate_no FROM vehicles WHERE company_id=? ORDER BY plate_no',
                                 (g.company_id,)).fetchall(),
        'drivers': db().execute('SELECT id,name FROM drivers WHERE company_id=? ORDER BY name',
                                (g.company_id,)).fetchall(),
        'routes': db().execute('SELECT id,name FROM routes WHERE company_id=? ORDER BY name',
                               (g.company_id,)).fetchall(),
    }


@bp.route('/trips')
@require_auth
def trips():
    if g.company is None:
        abort(403)
    status = request.args.get('status', '')
    sql = '''SELECT t.*, v.plate_no, d.name dname, r.name rname
             FROM trips t LEFT JOIN vehicles v ON t.vehicle_id=v.id
             LEFT JOIN drivers d ON t.driver_id=d.id LEFT JOIN routes r ON t.route_id=r.id
             WHERE t.company_id=?'''
    params = [g.company_id]
    if status in TRIP_STATUS:
        sql += ' AND t.status=?'
        params.append(status)
    sql += " ORDER BY CASE t.status WHEN 'in transit' THEN 0 WHEN 'scheduled' THEN 1 ELSE 2 END, t.id DESC LIMIT 100"
    rows = db().execute(sql, params).fetchall()
    return render_template('mobile/trips.html', rows=rows, statuses=TRIP_STATUS, active=status)


@bp.route('/trips/new', methods=['GET', 'POST'])
@require_auth
def trips_new():
    if g.company is None:
        abort(403)
    if request.method == 'POST':
        trip_no = next_no(db(), 'trips', 'trip_no', g.company_id, 'TRIP')
        db().execute('''INSERT INTO trips (company_id,trip_no,vehicle_id,driver_id,route_id,departure_at,
                                            arrival_at,distance_km,seats,revenue_cents,cost_cents,fuel_cents,status)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                     (g.company_id, trip_no, _pick('vehicles', request.form.get('vehicle_id')),
                      _pick('drivers', request.form.get('driver_id')), _pick('routes', request.form.get('route_id')),
                      form_str('departure_at', maxlen=40) or None, form_str('arrival_at', maxlen=40) or None,
                      form_int('distance_km', 0, 0), form_int('seats', 0, 0, 200),
                      form_money_cents('revenue'), form_money_cents('cost'), form_money_cents('fuel'),
                      request.form.get('status') if request.form.get('status') in TRIP_STATUS else 'scheduled'))
        db().commit()
        if _wants_json():
            return _flash_json('Trip %s created' % trip_no)
        flash('Trip %s created' % trip_no, 'ok')
        return redirect(url_for('mobile.trips'))
    return render_template('mobile/trip_form.html', row=None, statuses=TRIP_STATUS, **_refs())


@bp.route('/trips/<int:tid>/edit', methods=['GET', 'POST'])
@require_auth
def trips_edit(tid):
    if g.company is None:
        abort(403)
    row = owned('trips', tid)
    if request.method == 'POST':
        db().execute('''UPDATE trips SET vehicle_id=?,driver_id=?,route_id=?,departure_at=?,arrival_at=?,
                        distance_km=?,seats=?,revenue_cents=?,cost_cents=?,fuel_cents=?,status=?
                        WHERE id=? AND company_id=?''',
                     (_pick('vehicles', request.form.get('vehicle_id')),
                      _pick('drivers', request.form.get('driver_id')), _pick('routes', request.form.get('route_id')),
                      form_str('departure_at', maxlen=40) or None, form_str('arrival_at', maxlen=40) or None,
                      form_int('distance_km', 0, 0), form_int('seats', 0, 0, 200),
                      form_money_cents('revenue', row['revenue_cents']), form_money_cents('cost', row['cost_cents']),
                      form_money_cents('fuel', row['fuel_cents'] or 0),
                      request.form.get('status') if request.form.get('status') in TRIP_STATUS else row['status'],
                      tid, g.company_id))
        db().commit()
        if _wants_json():
            return _flash_json('Trip updated')
        flash('Trip updated', 'ok')
        return redirect(url_for('mobile.trips'))
    return render_template('mobile/trip_form.html', row=row, statuses=TRIP_STATUS, **_refs())


@bp.route('/trips/<int:tid>/status', methods=['POST'])
@require_auth
def trips_status(tid):
    if g.company is None:
        abort(403)
    row = owned('trips', tid)
    new = request.form.get('status')
    if new not in TRIP_STATUS:
        abort(400)
    db().execute('UPDATE trips SET status=? WHERE id=? AND company_id=?', (new, tid, g.company_id))
    db().commit()
    flash('%s is now %s' % (row['trip_no'], new), 'ok')
    return redirect(request.referrer or url_for('mobile.trips'))


# --------------------------------------------------------------------------
# Fuel + maintenance
# --------------------------------------------------------------------------

@bp.route('/fuel')
@require_auth
def fuel():
    if g.company is None:
        abort(403)
    rows = db().execute('''SELECT f.*, v.plate_no FROM fuel_records f
                           LEFT JOIN vehicles v ON f.vehicle_id=v.id
                           WHERE f.company_id=? ORDER BY f.id DESC LIMIT 100''', (g.company_id,)).fetchall()
    mtd = db().execute("SELECT COALESCE(SUM(amount_cents),0) FROM fuel_records WHERE company_id=? AND strftime('%Y-%m',date)=strftime('%Y-%m','now')",
                       (g.company_id,)).fetchone()[0]
    return render_template('mobile/fuel.html', rows=rows, mtd=mtd)


@bp.route('/fuel/new', methods=['GET', 'POST'])
@require_auth
def fuel_new():
    if g.company is None:
        abort(403)
    vehicles = db().execute('SELECT id,plate_no FROM vehicles WHERE company_id=? ORDER BY plate_no',
                            (g.company_id,)).fetchall()
    if request.method == 'POST':
        db().execute('''INSERT INTO fuel_records (company_id,vehicle_id,driver_id,amount_cents,quantity_l,odometer,date,notes)
                        VALUES (?,?,?,?,?,?,?,?)''',
                     (g.company_id, _pick('vehicles', request.form.get('vehicle_id')),
                      _pick('drivers', request.form.get('driver_id')), form_money_cents('amount'),
                      float(form_str('quantity_l') or 0) or None, form_int('odometer', 0, 0),
                      form_date('date'), form_str('notes', maxlen=500) or None))
        db().commit()
        if _wants_json():
            return _flash_json('Fuel entry saved')
        flash('Fuel entry saved', 'ok')
        return redirect(url_for('mobile.fuel'))
    return render_template('mobile/fuel_form.html', vehicles=vehicles)


@bp.route('/maintenance')
@require_auth
def maintenance():
    if g.company is None:
        abort(403)
    rows = db().execute('''SELECT m.*, v.plate_no FROM maintenance_records m
                           LEFT JOIN vehicles v ON m.vehicle_id=v.id
                           WHERE m.company_id=? ORDER BY m.status='done', m.id DESC LIMIT 100''',
                        (g.company_id,)).fetchall()
    return render_template('mobile/maintenance.html', rows=rows)


@bp.route('/maintenance/new', methods=['GET', 'POST'])
@require_auth
def maintenance_new():
    if g.company is None:
        abort(403)
    vehicles = db().execute('SELECT id,plate_no FROM vehicles WHERE company_id=? ORDER BY plate_no',
                            (g.company_id,)).fetchall()
    if request.method == 'POST':
        work = form_str('work', maxlen=200)
        if not work:
            message = 'Describe the work required'
        else:
            db().execute('''INSERT INTO maintenance_records (company_id,vehicle_id,work,status,cost_cents,date,next_due,notes)
                            VALUES (?,?,?,?,?,?,?,?)''',
                         (g.company_id, _pick('vehicles', request.form.get('vehicle_id')), work,
                          request.form.get('status') if request.form.get('status') in MAINT_STATUS else 'open',
                          form_money_cents('cost'), form_date('date'),
                          form_date('next_due', default=''), form_str('notes', maxlen=500) or None))
            db().commit()
            if _wants_json():
                return _flash_json('Maintenance item added')
            flash('Maintenance item added', 'ok')
            return redirect(url_for('mobile.maintenance'))
        if _wants_json():
            return _flash_json(message, 'error')
        flash(message, 'error')
    return render_template('mobile/maintenance_form.html', row=None, vehicles=vehicles, statuses=MAINT_STATUS)


@bp.route('/maintenance/<int:mid>/status', methods=['POST'])
@require_auth
def maintenance_status(mid):
    if g.company is None:
        abort(403)
    owned('maintenance_records', mid)
    new = request.form.get('status')
    if new not in MAINT_STATUS:
        abort(400)
    db().execute('UPDATE maintenance_records SET status=? WHERE id=? AND company_id=?', (new, mid, g.company_id))
    db().commit()
    flash('Marked as %s' % new, 'ok')
    return redirect(request.referrer or url_for('mobile.maintenance'))


# --------------------------------------------------------------------------
# Account
# --------------------------------------------------------------------------

@bp.route('/account')
@require_auth
def account():
    if g.company is None:
        abort(403)
    counts = {
        'vehicles': db().execute('SELECT COUNT(*) FROM vehicles WHERE company_id=?', (g.company_id,)).fetchone()[0],
        'drivers': db().execute('SELECT COUNT(*) FROM drivers WHERE company_id=?', (g.company_id,)).fetchone()[0],
        'trips': db().execute('SELECT COUNT(*) FROM trips WHERE company_id=?', (g.company_id,)).fetchone()[0],
    }
    return render_template('mobile/account.html', counts=counts)