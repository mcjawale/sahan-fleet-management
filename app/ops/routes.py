from flask import Blueprint, g, render_template, request, redirect, url_for, flash
from app.util import db, guard, form_str, form_int, form_money_cents, owned, next_no

bp = Blueprint('ops', __name__, url_prefix='/app/<slug>')
guard(bp)

TRIP_STATUS = ('scheduled', 'in transit', 'completed', 'cancelled')
BOOKING_STATUS = ('booked', 'cancelled', 'completed')


def _refs():
    return {
        'vehicles': db().execute('SELECT id,plate_no FROM vehicles WHERE company_id=? ORDER BY plate_no',
                                 (g.company_id,)).fetchall(),
        'drivers': db().execute('SELECT id,name FROM drivers WHERE company_id=? ORDER BY name',
                                (g.company_id,)).fetchall(),
        'routes': db().execute('SELECT id,name FROM routes WHERE company_id=? ORDER BY name',
                               (g.company_id,)).fetchall(),
    }


def _pick(table, value):
    try:
        num = int(value)
    except (TypeError, ValueError):
        return None
    if db().execute('SELECT id FROM %s WHERE id=? AND company_id=?' % table, (num, g.company_id)).fetchone():
        return num
    return None


@bp.route('/trips')
def trips(slug):
    status = request.args.get('status', '')
    sql = '''SELECT t.*, v.plate_no, d.name as dname, r.name as rname
             FROM trips t LEFT JOIN vehicles v ON t.vehicle_id=v.id
             LEFT JOIN drivers d ON t.driver_id=d.id LEFT JOIN routes r ON t.route_id=r.id
             WHERE t.company_id=?'''
    params = [g.company_id]
    if status in TRIP_STATUS:
        sql += ' AND t.status=?'
        params.append(status)
    sql += ' ORDER BY t.id DESC LIMIT 200'
    rows = db().execute(sql, params).fetchall()
    return render_template('ops/trips.html', rows=rows, statuses=TRIP_STATUS, active=status)


@bp.route('/trips/new', methods=['GET', 'POST'])
def trips_new(slug):
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
        flash('Trip %s created' % trip_no, 'ok')
        return redirect(url_for('ops.trips', slug=slug))
    return render_template('ops/trip_form.html', row=None, statuses=TRIP_STATUS, **_refs())


@bp.route('/trips/<int:tid>/edit', methods=['GET', 'POST'])
def trips_edit(slug, tid):
    row = owned('trips', tid)
    if request.method == 'POST':
        db().execute('''UPDATE trips SET vehicle_id=?,driver_id=?,route_id=?,departure_at=?,arrival_at=?,
                        distance_km=?,seats=?,revenue_cents=?,cost_cents=?,fuel_cents=?,status=?
                        WHERE id=? AND company_id=?''',
                     (_pick('vehicles', request.form.get('vehicle_id')),
                      _pick('drivers', request.form.get('driver_id')), _pick('routes', request.form.get('route_id')),
                      form_str('departure_at', maxlen=40) or None, form_str('arrival_at', maxlen=40) or None,
                      form_int('distance_km', 0, 0), form_int('seats', 0, 0, 200),
                      form_money_cents('revenue', row['revenue_cents']),
                      form_money_cents('cost', row['cost_cents']),
                      form_money_cents('fuel', row['fuel_cents'] or 0),
                      request.form.get('status') if request.form.get('status') in TRIP_STATUS else row['status'],
                      tid, g.company_id))
        db().commit()
        flash('Trip updated', 'ok')
        return redirect(url_for('ops.trips', slug=slug))
    return render_template('ops/trip_form.html', row=row, statuses=TRIP_STATUS, **_refs())


@bp.route('/bookings')
def bookings(slug):
    status = request.args.get('status', '')
    sql = 'SELECT * FROM bookings WHERE company_id=?'
    params = [g.company_id]
    if status in BOOKING_STATUS:
        sql += ' AND status=?'
        params.append(status)
    sql += ' ORDER BY id DESC LIMIT 200'
    rows = db().execute(sql, params).fetchall()
    return render_template('ops/bookings.html', rows=rows, statuses=BOOKING_STATUS, active=status)


@bp.route('/bookings/new', methods=['GET', 'POST'])
def bookings_new(slug):
    if request.method == 'POST':
        name = form_str('passenger_name', maxlen=120)
        if not name:
            flash('Passenger name is required', 'error')
        else:
            booking_no = next_no(db(), 'bookings', 'booking_no', g.company_id, 'BKG')
            db().execute('''INSERT INTO bookings (company_id,booking_no,trip_id,passenger_name,phone,pickup,
                                                dropoff,seats,fare_cents,status)
                            VALUES (?,?,?,?,?,?,?,?,?,?)''',
                         (g.company_id, booking_no, _pick('trips', request.form.get('trip_id')), name,
                          form_str('phone', maxlen=40) or None, form_str('pickup', maxlen=120) or None,
                          form_str('dropoff', maxlen=120) or None, max(1, form_int('seats', 1, 1, 200)),
                          form_money_cents('fare'),
                          request.form.get('status') if request.form.get('status') in BOOKING_STATUS else 'booked'))
            db().commit()
            flash('Booking %s created' % booking_no, 'ok')
            return redirect(url_for('ops.bookings', slug=slug))
    trips_rows = db().execute("SELECT id,trip_no FROM trips WHERE company_id=? AND status IN ('scheduled','in transit') ORDER BY id DESC",
                              (g.company_id,)).fetchall()
    return render_template('ops/booking_form.html', row=None, statuses=BOOKING_STATUS, trips_rows=trips_rows)


@bp.route('/bookings/<int:bid>/edit', methods=['GET', 'POST'])
def bookings_edit(slug, bid):
    row = owned('bookings', bid)
    trips_rows = db().execute('SELECT id,trip_no FROM trips WHERE company_id=? ORDER BY id DESC LIMIT 100',
                              (g.company_id,)).fetchall()
    if request.method == 'POST':
        name = form_str('passenger_name', maxlen=120)
        if not name:
            flash('Passenger name is required', 'error')
        else:
            db().execute('''UPDATE bookings SET trip_id=?,passenger_name=?,phone=?,pickup=?,dropoff=?,
                            seats=?,fare_cents=?,status=? WHERE id=? AND company_id=?''',
                         (_pick('trips', request.form.get('trip_id')), name,
                          form_str('phone', maxlen=40) or None, form_str('pickup', maxlen=120) or None,
                          form_str('dropoff', maxlen=120) or None, max(1, form_int('seats', 1, 1, 200)),
                          form_money_cents('fare', row['fare_cents']),
                          request.form.get('status') if request.form.get('status') in BOOKING_STATUS else row['status'],
                          bid, g.company_id))
            db().commit()
            flash('Booking updated', 'ok')
            return redirect(url_for('ops.bookings', slug=slug))
    return render_template('ops/booking_form.html', row=row, statuses=BOOKING_STATUS, trips_rows=trips_rows)


@bp.route('/bookings/<int:bid>/delete', methods=['POST'])
def bookings_delete(slug, bid):
    owned('bookings', bid)
    db().execute('DELETE FROM bookings WHERE id=? AND company_id=?', (bid, g.company_id))
    db().commit()
    flash('Booking removed', 'ok')
    return redirect(url_for('ops.bookings', slug=slug))