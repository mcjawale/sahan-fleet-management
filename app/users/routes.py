from flask import Blueprint, render_template, request, redirect, url_for, g, flash, abort
from werkzeug.security import generate_password_hash
from tenancy import (require_auth, require_company_admin, active_user_count,
                     user_slots_left, user_quota)
import re

bp = Blueprint('users', __name__, url_prefix='/app/<slug>/users')

ROLES = ('owner','admin','staff','viewer')
USERNAME_RE = re.compile(r'^[A-Za-z0-9._-]{3,32}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s.]+\.[^@\s]+$')
MIN_PASSWORD = 8

def db():
    from app import get_db
    return get_db()

@bp.before_request
def ensure_auth():
    if not g.user:
        from flask import redirect
        return redirect(url_for('auth.login', next=request.url))

def get_user_or_404(user_id):
    row = db().execute('''SELECT id,username,full_name,email,role,is_active,last_login_at,created_at
                          FROM users WHERE id=? AND company_id=?''', (user_id, g.company_id)).fetchone()
    if row is None:
        abort(404)
    return row

def owner_count():
    return db().execute('''SELECT COUNT(*) FROM users
                           WHERE company_id=? AND role='owner' AND is_active=1''', (g.company_id,)).fetchone()[0]

def audit(action, entity_id, detail=None):
    db().execute('''INSERT INTO audit_log (company_id,user_id,action,entity,entity_id,detail,ip_address)
                    VALUES (?,?,?,?,?,?,?)''',
                 (g.company_id, g.user_id, action, 'users', str(entity_id), detail, request.remote_addr))

def back_to_list(msg=None, cat='ok'):
    if msg:
        flash(msg, cat)
    return redirect(url_for('users.list', slug=g.company['slug']))

@bp.route('/')
@require_company_admin
def list(slug):
    rows = db().execute('''SELECT id,username,full_name,email,role,is_active,last_login_at,created_at
                           FROM users WHERE company_id=? ORDER BY
                             CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1
                                       WHEN 'staff' THEN 2 ELSE 3 END, username''', (g.company_id,)).fetchall()
    return render_template('users/list.html', rows=rows,
                           slots=user_slots_left(), quota=user_quota(),
                           user_count=active_user_count())

@bp.route('/new', methods=['GET','POST'])
@require_company_admin
def new(slug):
    slots = user_slots_left()
    if slots is not None and slots <= 0:
        flash('Your plan allows %d active user(s). Upgrade the plan to add more.' % user_quota(), 'error')
        return back_to_list()

    if request.method == 'POST':
        un = request.form.get('username','').strip()
        fn = request.form.get('full_name','').strip()
        em = request.form.get('email','').strip()
        role = request.form.get('role','staff')
        pw1 = request.form.get('password1','')
        pw2 = request.form.get('password2','')

        if not USERNAME_RE.match(un):
            return back_to_list('Username must be 3-32 characters (letters, numbers, . _ -)', 'error')
        if role not in ROLES:
            return back_to_list('Unknown role', 'error')
        if role == 'owner' and g.user['role'] != 'owner':
            return back_to_list('Only the company owner can create another owner', 'error')
        if len(pw1) < MIN_PASSWORD:
            return back_to_list('Password must be at least %d characters' % MIN_PASSWORD, 'error')
        if pw1 != pw2:
            return back_to_list('Passwords do not match', 'error')
        if em and not EMAIL_RE.match(em):
            return back_to_list('Enter a valid email address', 'error')

        slots = user_slots_left()
        if slots is not None and slots <= 0:
            return back_to_list('User limit reached for your plan', 'error')

        try:
            db().execute('''INSERT INTO users (company_id,username,password_hash,full_name,email,role,is_active)
                            VALUES (?,?,?,?,?,?,1)''', (g.company_id, un, generate_password_hash(pw1),
                                                      fn or None, em or None, role))
            uid = db().execute('SELECT last_insert_rowid() AS id').fetchone()['id']
            audit('user_created', uid, '%s as %s' % (un, role))
            db().commit()
        except Exception:
            db().rollback()
            return back_to_list('Could not add user: "%s" is already taken in this company' % un, 'error')
        return back_to_list('User "%s" added as %s' % (un, role))

    return render_template('users/new.html', roles=ROLES)

@bp.route('/<int:user_id>/edit', methods=['GET','POST'])
@require_company_admin
def edit(slug, user_id):
    row = get_user_or_404(user_id)

    if request.method == 'POST':
        fn = request.form.get('full_name','').strip()
        em = request.form.get('email','').strip()
        role = request.form.get('role', row['role'])
        is_active = 1 if request.form.get('is_active') else 0

        if role not in ROLES:
            return back_to_list('Unknown role', 'error')
        if em and not EMAIL_RE.match(em):
            return back_to_list('Enter a valid email address', 'error')
        if role == 'owner' and g.user['role'] != 'owner':
            return back_to_list('Only the company owner can promote someone to owner', 'error')
        if row['id'] == g.user_id and not is_active:
            return back_to_list('You cannot deactivate your own account', 'error')
        was_active_owner = row['role'] == 'owner' and row['is_active'] == 1
        becomes_active_owner = role == 'owner' and is_active == 1
        if was_active_owner and not becomes_active_owner and owner_count() <= 1:
            return back_to_list('A company must keep at least one active owner', 'error')
        if not row['is_active'] and is_active:
            slots = user_slots_left()
            if slots is not None and slots <= 0:
                return back_to_list('User limit reached for your plan', 'error')
        if em:
            clash = db().execute('SELECT id FROM users WHERE lower(email)=lower(?) AND id!=?',
                                 (em, user_id)).fetchone()
            if clash:
                return back_to_list('That email is already used by another account', 'error')

        db().execute('UPDATE users SET full_name=?, email=?, role=?, is_active=? WHERE id=? AND company_id=?',
                     (fn or None, em or None, role, is_active, user_id, g.company_id))
        audit('user_updated', user_id, 'role=%s active=%s' % (role, is_active))
        db().commit()
        return back_to_list('User updated')

    return render_template('users/edit.html', row=row, roles=ROLES)

@bp.route('/<int:user_id>/reset-password', methods=['POST'])
@require_company_admin
def reset_password(slug, user_id):
    row = get_user_or_404(user_id)
    pw1 = request.form.get('password1','')
    pw2 = request.form.get('password2','')
    if len(pw1) < MIN_PASSWORD:
        return back_to_list('Password must be at least %d characters' % MIN_PASSWORD, 'error')
    if pw1 != pw2:
        return back_to_list('Passwords do not match', 'error')
    db().execute('''UPDATE users SET password_hash=?, failed_attempts=0, locked_until=NULL
                   WHERE id=? AND company_id=?''', (generate_password_hash(pw1), user_id, g.company_id))
    audit('user_password_reset', user_id, 'by %s' % g.user['username'])
    db().commit()
    return back_to_list('Password reset for "%s"' % row['username'])

@bp.route('/<int:user_id>/unlock', methods=['POST'])
@require_company_admin
def unlock(slug, user_id):
    row = get_user_or_404(user_id)
    db().execute('UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=? AND company_id=?',
                 (user_id, g.company_id))
    audit('user_unlocked', user_id, 'by %s' % g.user['username'])
    db().commit()
    return back_to_list('"%s" unlocked' % row['username'])

@bp.route('/<int:user_id>/delete', methods=['POST'])
@require_company_admin
def delete(slug, user_id):
    row = get_user_or_404(user_id)
    if user_id == g.user_id:
        return back_to_list('You cannot delete your own account', 'error')
    if row['role'] == 'owner' and owner_count() <= 1:
        return back_to_list('A company must keep at least one active owner', 'error')
    db().execute('DELETE FROM users WHERE id=? AND company_id=?', (user_id, g.company_id))
    audit('user_deleted', user_id, row['username'])
    db().commit()
    return back_to_list('User "%s" removed' % row['username'])