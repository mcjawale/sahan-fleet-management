from flask import Blueprint, request, redirect, url_for, g, flash, abort
from functools import wraps
from typing import Optional
import re
import json

bp = Blueprint('tenancy', __name__)

def db():
    from app import get_db
    return get_db()

def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'[\s_-]+', '-', s)
    return s.strip('-')

def resolve_from_url():
    g.url_company = None
    m = re.match(r'^/app/([a-z0-9\-]+)/?', request.path)
    if not m:
        return
    slug = m.group(1)
    cur = db().execute('SELECT id,name,slug,is_active FROM companies WHERE slug=?', (slug,))
    row = cur.fetchone()
    if not row or row['is_active'] == 0:
        abort(404)
    if g.user is None:
        return
    if row['id'] != g.company_id:
        abort(404)
    g.url_company = dict(row)

def require_auth(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return wrap

def require_company_admin(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('auth.login', next=request.url))
        if g.company is None:
            abort(403)
        if g.user['role'] not in ('owner','admin'):
            abort(403)
        return f(*args, **kwargs)
    return wrap

def require_owner(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('auth.login', next=request.url))
        if g.company is None:
            abort(403)
        if g.user['role'] != 'owner':
            abort(403)
        return f(*args, **kwargs)
    return wrap

def plan_allows(feature: str) -> bool:
    cid = g.company_id
    if not cid:
        return False
    cur = db().execute('''SELECT p.features FROM subscriptions s JOIN plans p ON s.plan_id=p.id
                           WHERE s.company_id=? AND s.status IN ('trialing','active','past_due') LIMIT 1''', (cid,))
    row = cur.fetchone()
    if not row:
        return False
    try:
        feats = json.loads(row['features'] or '{}')
    except Exception:
        feats = {}
    return bool(feats.get(feature, False))

def get_active_sub():
    cid = g.company_id
    cur = db().execute('''SELECT s.id,s.status,p.code,p.name,p.max_vehicles,p.max_users,p.max_trips_per_month,p.features
                           FROM subscriptions s JOIN plans p ON s.plan_id=p.id
                           WHERE s.company_id=? AND s.status IN ('trialing','active','past_due') LIMIT 1''', (cid,))
    return cur.fetchone() if cid else None

def active_user_count() -> int:
    if not g.company_id:
        return 0
    return db().execute('SELECT COUNT(*) FROM users WHERE company_id=? AND is_active=1',
                        (g.company_id,)).fetchone()[0]

def user_quota() -> Optional[int]:
    sub = get_active_sub()
    if sub is None:
        return 0
    return sub['max_users']

def user_slots_left() -> Optional[int]:
    limit = user_quota()
    if limit is None or limit < 0:
        return None
    return max(0, limit - active_user_count())
