from flask import Blueprint, g, render_template, request, redirect, url_for, flash
from app.util import db, guard, form_str, form_int, owned

bp = Blueprint('fleet', __name__, url_prefix='/app/<slug>')
guard(bp)

VEHICLE_STATUS = ('available', 'in service', 'maintenance', 'retired')


@bp.route('/vehicles')
def vehicles(slug):
    rows = db().execute('''SELECT v.*, (SELECT COUNT(*) FROM trips t WHERE t.vehicle_id=v.id) as trips
                           FROM vehicles v WHERE v.company_id=? ORDER BY v.plate_no''', (g.company_id,)).fetchall()
    return render_template('fleet/vehicles.html', rows=rows, statuses=VEHICLE_STATUS)


@bp.route('/vehicles/new', methods=['GET', 'POST'])
def vehicles_new(slug):
    if request.method == 'POST':
        plate = form_str('plate_no', maxlen=32)
        if not plate:
            flash('Plate number is required', 'error')
        elif db().execute('SELECT id FROM vehicles WHERE company_id=? AND lower(plate_no)=lower(?)',
                          (g.company_id, plate)).fetchone():
            flash('That plate number already exists', 'error')
        else:
            db().execute('''INSERT INTO vehicles (company_id,plate_no,make,model,year,capacity,odometer,status)
                            VALUES (?,?,?,?,?,?,?,?)''',
                         (g.company_id, plate, form_str('make', maxlen=60) or None,
                          form_str('model', maxlen=60) or None, form_int('year', 0, 1900, 2100),
                          form_int('capacity', 0, 0, 200), form_int('odometer', 0, 0),
                          form_str('status', 'available') if request.form.get('status') in VEHICLE_STATUS else 'available'))
            db().commit()
            flash('Vehicle %s added' % plate, 'ok')
            return redirect(url_for('fleet.vehicles', slug=slug))
    return render_template('fleet/vehicle_form.html', row=None, statuses=VEHICLE_STATUS)


@bp.route('/vehicles/<int:vid>/edit', methods=['GET', 'POST'])
def vehicles_edit(slug, vid):
    row = owned('vehicles', vid)
    if request.method == 'POST':
        plate = form_str('plate_no', maxlen=32)
        clash = db().execute('SELECT id FROM vehicles WHERE company_id=? AND lower(plate_no)=lower(?) AND id!=?',
                             (g.company_id, plate, vid)).fetchone()
        if not plate:
            flash('Plate number is required', 'error')
        elif clash:
            flash('That plate number already exists', 'error')
        else:
            status = request.form.get('status')
            db().execute('''UPDATE vehicles SET plate_no=?,make=?,model=?,year=?,capacity=?,odometer=?,status=?
                            WHERE id=? AND company_id=?''',
                         (plate, form_str('make', maxlen=60) or None, form_str('model', maxlen=60) or None,
                          form_int('year', 0, 1900, 2100), form_int('capacity', 0, 0, 200),
                          form_int('odometer', 0, 0), status if status in VEHICLE_STATUS else 'available',
                          vid, g.company_id))
            db().commit()
            flash('Vehicle updated', 'ok')
            return redirect(url_for('fleet.vehicles', slug=slug))
    return render_template('fleet/vehicle_form.html', row=row, statuses=VEHICLE_STATUS)


@bp.route('/vehicles/<int:vid>/delete', methods=['POST'])
def vehicles_delete(slug, vid):
    owned('vehicles', vid)
    db().execute('DELETE FROM vehicles WHERE id=? AND company_id=?', (vid, g.company_id))
    db().commit()
    flash('Vehicle removed', 'ok')
    return redirect(url_for('fleet.vehicles', slug=slug))


@bp.route('/drivers')
def drivers(slug):
    rows = db().execute('''SELECT d.*, (SELECT COUNT(*) FROM trips t WHERE t.driver_id=d.id AND t.status IN ('scheduled','in transit')) as live
                           FROM drivers d WHERE d.company_id=? ORDER BY d.name''', (g.company_id,)).fetchall()
    return render_template('fleet/drivers.html', rows=rows)


@bp.route('/drivers/new', methods=['GET', 'POST'])
def drivers_new(slug):
    if request.method == 'POST':
        name = form_str('name', maxlen=120)
        if not name:
            flash('Driver name is required', 'error')
        else:
            db().execute('''INSERT INTO drivers (company_id,name,phone,licence_no,licence_expiry,is_active)
                            VALUES (?,?,?,?,?,?)''',
                         (g.company_id, name, form_str('phone', maxlen=40) or None,
                          form_str('licence_no', maxlen=60) or None, form_str('licence_expiry', maxlen=20) or None,
                          1 if request.form.get('is_active') else 0))
            db().commit()
            flash('Driver %s added' % name, 'ok')
            return redirect(url_for('fleet.drivers', slug=slug))
    return render_template('fleet/driver_form.html', row=None)


@bp.route('/drivers/<int:did>/edit', methods=['GET', 'POST'])
def drivers_edit(slug, did):
    row = owned('drivers', did)
    if request.method == 'POST':
        name = form_str('name', maxlen=120)
        if not name:
            flash('Driver name is required', 'error')
        else:
            db().execute('''UPDATE drivers SET name=?,phone=?,licence_no=?,licence_expiry=?,is_active=?
                            WHERE id=? AND company_id=?''',
                         (name, form_str('phone', maxlen=40) or None, form_str('licence_no', maxlen=60) or None,
                          form_str('licence_expiry', maxlen=20) or None,
                          1 if request.form.get('is_active') else 0, did, g.company_id))
            db().commit()
            flash('Driver updated', 'ok')
            return redirect(url_for('fleet.drivers', slug=slug))
    return render_template('fleet/driver_form.html', row=row)


@bp.route('/routes')
def routes(slug):
    rows = db().execute('SELECT * FROM routes WHERE company_id=? ORDER BY name', (g.company_id,)).fetchall()
    return render_template('fleet/routes.html', rows=rows)


@bp.route('/routes/new', methods=['GET', 'POST'])
def routes_new(slug):
    if request.method == 'POST':
        name = form_str('name', maxlen=120)
        if not name:
            flash('Route name is required', 'error')
        elif db().execute('SELECT id FROM routes WHERE company_id=? AND lower(name)=lower(?)',
                          (g.company_id, name)).fetchone():
            flash('That route already exists', 'error')
        else:
            db().execute('''INSERT INTO routes (company_id,name,origin,destination,distance_km)
                            VALUES (?,?,?,?,?)''',
                         (g.company_id, name, form_str('origin', maxlen=120) or None,
                          form_str('destination', maxlen=120) or None, form_int('distance_km', 0, 0)))
            db().commit()
            flash('Route %s added' % name, 'ok')
            return redirect(url_for('fleet.routes', slug=slug))
    return render_template('fleet/route_form.html', row=None)


@bp.route('/routes/<int:rid>/edit', methods=['GET', 'POST'])
def routes_edit(slug, rid):
    row = owned('routes', rid)
    if request.method == 'POST':
        name = form_str('name', maxlen=120)
        clash = db().execute('SELECT id FROM routes WHERE company_id=? AND lower(name)=lower(?) AND id!=?',
                             (g.company_id, name, rid)).fetchone()
        if not name:
            flash('Route name is required', 'error')
        elif clash:
            flash('That route already exists', 'error')
        else:
            db().execute('''UPDATE routes SET name=?,origin=?,destination=?,distance_km=?
                            WHERE id=? AND company_id=?''',
                         (name, form_str('origin', maxlen=120) or None,
                          form_str('destination', maxlen=120) or None, form_int('distance_km', 0, 0),
                          rid, g.company_id))
            db().commit()
            flash('Route updated', 'ok')
            return redirect(url_for('fleet.routes', slug=slug))
    return render_template('fleet/route_form.html', row=row)


@bp.route('/routes/<int:rid>/delete', methods=['POST'])
def routes_delete(slug, rid):
    owned('routes', rid)
    db().execute('DELETE FROM routes WHERE id=? AND company_id=?', (rid, g.company_id))
    db().commit()
    flash('Route removed', 'ok')
    return redirect(url_for('fleet.routes', slug=slug))