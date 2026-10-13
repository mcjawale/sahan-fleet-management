from flask import Blueprint, render_template, request, redirect, url_for, session, g, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from tenancy import require_auth, slugify
from app.auth import service
from datetime import datetime, timedelta, timezone
import re

bp = Blueprint('auth', __name__)

MAX_ATTEMPTS = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 8
ROLES = ('owner','admin','staff','viewer')
USERNAME_RE = re.compile(r'^[A-Za-z0-9._-]{3,32}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s.]+\.[^@\s]+$')

def db():
    from app import get_db
    return get_db()

def _now():
    return datetime.now(timezone.utc)

def _lock_state(row):
    if not row['locked_until']:
        return False
    try:
        until = datetime.fromisoformat(row['locked_until'])
    except ValueError:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > _now()

def unique_slug(name):
    base = slugify(name) or 'company'
    slug = base
    i = 1
    while db().execute('SELECT id FROM companies WHERE slug=?', (slug,)).fetchone():
        slug = f'{base}-{i}'
        i += 1
    return slug

def subscribe(company_id, plan_code='free'):
    plan = db().execute('SELECT id,trial_days FROM plans WHERE code=?', (plan_code,)).fetchone()
    if plan is None:
        plan = db().execute('SELECT id,trial_days FROM plans ORDER BY sort_order LIMIT 1').fetchone()
    if plan is None:
        return
    days = plan['trial_days'] or 0
    status = 'trialing' if days > 0 else 'active'
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days if days > 0 else 365)
    db().execute('''INSERT INTO subscriptions
                    (company_id,plan_id,status,started_at,current_period_start,current_period_end)
                    VALUES (?,?,?,?,?,?)''',
                 (company_id, plan['id'], status,
                  start.strftime('%Y-%m-%d %H:%M:%S'),
                  start.strftime('%Y-%m-%d %H:%M:%S'),
                  end.strftime('%Y-%m-%d %H:%M:%S')))

def log_in(user_id):
    session.clear()
    session.permanent = True
    session['user_id'] = user_id


@bp.route('/auth/login', methods=['GET','POST'])
def login():
    if g.user:
        return redirect(url_for('auth.home_for_user'))

    company_ref = request.values.get('company','').strip()
    identifier = request.values.get('username','').strip() or request.values.get('email','').strip()
    password = request.values.get('password','')

    if request.method == 'POST':
        status, row, message = service.authenticate(company_ref, identifier, password)
        if status == service.OK:
            log_in(row['user_id'])
            nxt = request.args.get('next')
            return redirect(nxt or url_for('dashboard.index', slug=row['slug']))
        flash(message, 'error')
        return render_template('auth/login.html', company_ref=company_ref, identifier=identifier), 401

    return render_template('auth/login.html', company_ref=company_ref, identifier=identifier)

@bp.route('/auth/logout', methods=['GET','POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@bp.route('/auth/signup', methods=['GET','POST'])
def signup():
    if g.user:
        return redirect(url_for('auth.home_for_user'))
    form = {}
    if request.method == 'POST':
        company = request.form.get('company','').strip()
        full_name = request.form.get('full_name','').strip()
        username = request.form.get('username','').strip()
        email = request.form.get('email','').strip()
        phone = request.form.get('phone','').strip()
        pw1 = request.form.get('password1','')
        pw2 = request.form.get('password2','')
        form = dict(company=company, full_name=full_name, username=username,
                    email=email, phone=phone)

        def fail(msg):
            flash(msg, 'error')
            return render_template('auth/signup.html', form=form), 400

        if not company or not full_name or not username or not pw1:
            return fail('All fields are required')
        if not USERNAME_RE.match(username):
            return fail('Username must be 3-32 characters (letters, numbers, . _ -)')
        if email and not EMAIL_RE.match(email):
            return fail('Enter a valid email address')
        if len(pw1) < MIN_PASSWORD:
            return fail('Password must be at least %d characters' % MIN_PASSWORD)
        if pw1 != pw2:
            return fail('Passwords do not match')

        slug = unique_slug(company)
        try:
            db().execute('INSERT INTO companies (name,slug,contact_email,phone) VALUES (?,?,?,?)',
                         (company, slug, email or None, phone or None))
            cid = db().execute('SELECT last_insert_rowid() AS id').fetchone()['id']
            db().execute('''INSERT INTO users (company_id,username,password_hash,full_name,email,role,is_active)
                            VALUES (?,?,?,?,?,'owner',1)''',
                         (cid, username, generate_password_hash(pw1), full_name, email or None))
            uid = db().execute('SELECT last_insert_rowid() AS id').fetchone()['id']
            subscribe(cid)
            db().execute('''INSERT INTO audit_log (company_id,user_id,action,entity,entity_id,ip_address)
                             VALUES (?,?,'company_created','companies',?,?)''',
                         (cid, uid, str(cid), request.remote_addr))
            db().commit()
        except Exception:
            db().rollback()
            return fail('Could not create the company. Please try again.')

        log_in(uid)
        flash('Welcome to %s. Your company workspace is ready.' % company, 'ok')
        return redirect(url_for('dashboard.index', slug=slug))

    return render_template('auth/signup.html', form=form)

@bp.route('/auth/home-for-user')
def home_for_user():
    if g.user and g.company:
        return redirect(url_for('dashboard.index', slug=g.company['slug']))
    if g.user:
        return redirect(url_for('auth.profile'))
    return redirect(url_for('auth.login'))

@bp.route('/auth/profile', methods=['GET','POST'])
@require_auth
def profile():
    from tenancy import active_user_count
    sub = None
    try:
        from tenancy import get_active_sub
        sub = get_active_sub()
    except Exception:
        sub = None

    if request.method == 'POST':
        action = request.form.get('action','')
        conn = db()
        if action == 'details':
            full_name = request.form.get('full_name','').strip()
            email = request.form.get('email','').strip()
            if email and not EMAIL_RE.match(email):
                flash('Enter a valid email address', 'error')
            else:
                clash = conn.execute('SELECT id FROM users WHERE lower(email)=lower(?) AND id!=?',
                                   (email, g.user_id)).fetchone() if email else None
                if clash:
                    flash('That email is already used by another account', 'error')
                else:
                    conn.execute('UPDATE users SET full_name=?, email=? WHERE id=?',
                               (full_name or None, email or None, g.user_id))
                    conn.commit()
                    flash('Profile updated', 'ok')
                    return redirect(url_for('auth.profile'))
        elif action == 'password':
            current = request.form.get('current_password','')
            pw1 = request.form.get('password1','')
            pw2 = request.form.get('password2','')
            row = conn.execute('SELECT password_hash FROM users WHERE id=?', (g.user_id,)).fetchone()
            if not row or not check_password_hash(row['password_hash'], current):
                flash('Your current password is incorrect', 'error')
            elif len(pw1) < MIN_PASSWORD:
                flash('Password must be at least %d characters' % MIN_PASSWORD, 'error')
            elif pw1 != pw2:
                flash('New passwords do not match', 'error')
            else:
                conn.execute('''UPDATE users SET password_hash=?, failed_attempts=0, locked_until=NULL
                              WHERE id=?''', (generate_password_hash(pw1), g.user_id))
                conn.commit()
                flash('Password changed', 'ok')
                return redirect(url_for('auth.profile'))
        else:
            abort(400)

    return render_template('auth/profile.html', user=g.user, sub=sub, user_count=active_user_count())
