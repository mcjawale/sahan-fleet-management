from flask import Blueprint, g, render_template, request, redirect, url_for, flash
from app.util import db, guard, form_str, form_int, form_money_cents, form_date, owned

bp = Blueprint('records', __name__, url_prefix='/app/<slug>')
guard(bp)

MAINT_STATUS = ('open', 'in progress', 'done')


def _vehicles():
    return db().execute('SELECT id,plate_no FROM vehicles WHERE company_id=? ORDER BY plate_no',
                        (g.company_id,)).fetchall()


def _drivers():
    return db().execute('SELECT id,name FROM drivers WHERE company_id=? ORDER BY name',
                        (g.company_id,)).fetchall()


@bp.route('/fuel')
def fuel(slug):
    rows = db().execute('''SELECT f.*, v.plate_no, d.name as dname FROM fuel_records f
                           LEFT JOIN vehicles v ON f.vehicle_id=v.id
                           LEFT JOIN drivers d ON f.driver_id=d.id
                           WHERE f.company_id=? ORDER BY f.id DESC LIMIT 200''', (g.company_id,)).fetchall()
    total = db().execute("SELECT COALESCE(SUM(amount_cents),0) FROM fuel_records WHERE company_id=? AND strftime('%Y-%m',date)=strftime('%Y-%m','now')",
                         (g.company_id,)).fetchone()[0]
    return render_template('records/fuel.html', rows=rows, mtd=total)


@bp.route('/fuel/new', methods=['GET', 'POST'])
def fuel_new(slug):
    if request.method == 'POST':
        db().execute('''INSERT INTO fuel_records (company_id,vehicle_id,driver_id,amount_cents,quantity_l,odometer,date,notes)
                        VALUES (?,?,?,?,?,?,?,?)''',
                     (g.company_id, _pick('vehicles', request.form.get('vehicle_id')),
                      _pick('drivers', request.form.get('driver_id')), form_money_cents('amount'),
                      float(form_str('quantity_l') or 0) or None, form_int('odometer', 0, 0),
                      form_date('date'), form_str('notes', maxlen=500) or None))
        db().commit()
        flash('Fuel record saved', 'ok')
        return redirect(url_for('records.fuel', slug=slug))
    return render_template('records/fuel_form.html', row=None, vehicles=_vehicles(), drivers=_drivers())


@bp.route('/fuel/<int:fid>/delete', methods=['POST'])
def fuel_delete(slug, fid):
    owned('fuel_records', fid)
    db().execute('DELETE FROM fuel_records WHERE id=? AND company_id=?', (fid, g.company_id))
    db().commit()
    flash('Fuel record removed', 'ok')
    return redirect(url_for('records.fuel', slug=slug))


@bp.route('/maintenance')
def maintenance(slug):
    rows = db().execute('''SELECT m.*, v.plate_no FROM maintenance_records m
                           LEFT JOIN vehicles v ON m.vehicle_id=v.id
                           WHERE m.company_id=? ORDER BY m.id DESC LIMIT 200''', (g.company_id,)).fetchall()
    return render_template('records/maintenance.html', rows=rows, statuses=MAINT_STATUS)


@bp.route('/maintenance/new', methods=['GET', 'POST'])
def maintenance_new(slug):
    if request.method == 'POST':
        work = form_str('work', maxlen=200)
        if not work:
            flash('Describe the work required', 'error')
        else:
            db().execute('''INSERT INTO maintenance_records (company_id,vehicle_id,work,status,cost_cents,date,next_due,notes)
                            VALUES (?,?,?,?,?,?,?,?)''',
                         (g.company_id, _pick('vehicles', request.form.get('vehicle_id')), work,
                          request.form.get('status') if request.form.get('status') in MAINT_STATUS else 'open',
                          form_money_cents('cost'), form_date('date'),
                          form_date('next_due', default=''), form_str('notes', maxlen=500) or None))
            db().commit()
            flash('Maintenance item added', 'ok')
            return redirect(url_for('records.maintenance', slug=slug))
    return render_template('records/maintenance_form.html', row=None, vehicles=_vehicles(), statuses=MAINT_STATUS)


@bp.route('/maintenance/<int:mid>/edit', methods=['GET', 'POST'])
def maintenance_edit(slug, mid):
    row = owned('maintenance_records', mid)
    if request.method == 'POST':
        work = form_str('work', maxlen=200)
        if not work:
            flash('Describe the work required', 'error')
        else:
            db().execute('''UPDATE maintenance_records SET vehicle_id=?,work=?,status=?,cost_cents=?,date=?,next_due=?,notes=?
                            WHERE id=? AND company_id=?''',
                         (_pick('vehicles', request.form.get('vehicle_id')), work,
                          request.form.get('status') if request.form.get('status') in MAINT_STATUS else row['status'],
                          form_money_cents('cost', row['cost_cents'] or 0), form_date('date'),
                          form_date('next_due', default=''), form_str('notes', maxlen=500) or None,
                          mid, g.company_id))
            db().commit()
            flash('Maintenance item updated', 'ok')
            return redirect(url_for('records.maintenance', slug=slug))
    return render_template('records/maintenance_form.html', row=row, vehicles=_vehicles(), statuses=MAINT_STATUS)


@bp.route('/maintenance/<int:mid>/delete', methods=['POST'])
def maintenance_delete(slug, mid):
    owned('maintenance_records', mid)
    db().execute('DELETE FROM maintenance_records WHERE id=? AND company_id=?', (mid, g.company_id))
    db().commit()
    flash('Maintenance item removed', 'ok')
    return redirect(url_for('records.maintenance', slug=slug))


def _pick(table, value):
    try:
        num = int(value)
    except (TypeError, ValueError):
        return None
    if db().execute('SELECT id FROM %s WHERE id=? AND company_id=?' % table, (num, g.company_id)).fetchone():
        return num
    return None