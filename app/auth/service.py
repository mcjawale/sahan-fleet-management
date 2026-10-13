"""Shared credential verification for the web and mobile sign-in screens.

Both entry points call :func:`authenticate` so the same company code,
username and password always work on either surface.
"""
from datetime import datetime, timedelta, timezone

from flask import request, session

MAX_ATTEMPTS = 5
LOCK_MINUTES = 15

LOCKED = 'locked'
SUSPENDED = 'suspended'
BAD_CREDENTIALS = 'bad_credentials'
MISSING_FIELDS = 'missing_fields'
OK = 'ok'


def db():
    from app import get_db
    return get_db()


def _now():
    return datetime.now(timezone.utc)


def _parse(stamp):
    try:
        value = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def is_locked(row):
    until = _parse(row['locked_until'])
    return bool(until and until > _now())


def lookup(company_ref, identifier):
    """Find the user row for a company code/name plus username."""
    return db().execute('''SELECT c.id AS company_id, c.slug AS slug, c.name AS company_name,
                                  c.is_active AS company_active,
                                  u.id AS user_id, u.password_hash, u.is_active, u.role,
                                  u.failed_attempts, u.locked_until
                           FROM companies c
                           JOIN users u ON u.company_id = c.id
                           WHERE (c.slug = ? OR lower(c.name) = ?) AND lower(u.username) = ?
                           LIMIT 1''',
                        (company_ref, company_ref.lower(), identifier.lower())).fetchone()


def record_failure(row):
    attempts = (row['failed_attempts'] or 0) + 1
    conn = db()
    if attempts >= MAX_ATTEMPTS:
        conn.execute('UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?',
                     (attempts, (_now() + timedelta(minutes=LOCK_MINUTES)).strftime('%Y-%m-%d %H:%M:%S'),
                      row['user_id']))
    else:
        conn.execute('UPDATE users SET failed_attempts=? WHERE id=?', (attempts, row['user_id']))
    conn.commit()
    return max(0, MAX_ATTEMPTS - attempts)


def record_success(row):
    conn = db()
    conn.execute('''UPDATE users SET failed_attempts=0, locked_until=NULL,
                    last_login_at=datetime('now') WHERE id=?''', (row['user_id'],))
    conn.execute('''INSERT INTO audit_log (company_id,user_id,action,entity,entity_id,ip_address)
                    VALUES (?,?,'login','users',?,?)''',
                 (row['company_id'], row['user_id'], str(row['user_id']), request.remote_addr))
    conn.commit()


def log_in(user_id):
    session.clear()
    session.permanent = True
    session['user_id'] = user_id


def authenticate(company_ref, identifier, password):
    """Verify credentials. Returns (status, row, message)."""
    from werkzeug.security import check_password_hash

    company_ref = (company_ref or '').strip()
    identifier = (identifier or '').strip()
    password = password or ''

    if not company_ref or not identifier or not password:
        return MISSING_FIELDS, None, 'Enter your company, username and password'

    row = lookup(company_ref, identifier)
    if row is None:
        return BAD_CREDENTIALS, None, 'Invalid company, username or password'

    if row['company_active'] == 0:
        return SUSPENDED, row, 'This company account is suspended. Contact support.'

    if not row['is_active']:
        return BAD_CREDENTIALS, row, 'Invalid company, username or password'

    if is_locked(row):
        return LOCKED, row, 'Too many failed attempts. Try again in a few minutes.'

    if check_password_hash(row['password_hash'], password):
        record_success(row)
        return OK, row, ''

    left = record_failure(row)
    if left == 0:
        return LOCKED, row, 'Too many failed attempts. Account locked for %d minutes.' % LOCK_MINUTES
    return BAD_CREDENTIALS, row, 'Invalid company, username or password. %d attempt(s) left.' % left