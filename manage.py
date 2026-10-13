"""Command line admin for the MCJ Sahan Fleet Management System.

Usage:
    python manage.py init-db
    python manage.py seed --company "MCJ Sahan" --username mcj --password mcj12345
    python manage.py add-user --company mcj-sahan --username dispatcher --password pass12345
    python manage.py list-users
    python manage.py reset-password --company mcj-sahan --username mcj --password newpass123
    python manage.py unlock --company mcj-sahan --username mcj
"""
import argparse
import sqlite3
import sys
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from werkzeug.security import generate_password_hash  # noqa: E402

DB_PATH = ROOT / 'instance' / 'sahan_fleet.sqlite'
SCHEMA_PATH = ROOT / 'schema.sql'

MIN_PASSWORD = 8


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def cmd_init_db(args):
    db = connect()
    db.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
    db.commit()
    db.close()
    print('Schema applied to %s' % DB_PATH)


def cmd_seed(args):
    if len(args.password) < MIN_PASSWORD:
        sys.exit('Password must be at least %d characters' % MIN_PASSWORD)

    from tenancy import slugify

    db = connect()
    base = slugify(args.company) or 'company'
    slug = base
    i = 1
    while db.execute('SELECT id FROM companies WHERE slug=?', (slug,)).fetchone():
        slug = '%s-%d' % (base, i)
        i += 1

    db.execute('INSERT INTO companies (name,slug,contact_email,phone) VALUES (?,?,?,?)',
               (args.company, slug, args.email, args.phone))
    cid = db.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
    db.execute('''INSERT INTO users (company_id,username,password_hash,full_name,email,role,is_active)
                  VALUES (?,?,?,?,?,'owner',1)''',
               (cid, args.username, generate_password_hash(args.password),
                args.full_name or args.username, args.email))

    plan = db.execute("SELECT id FROM plans WHERE code='free'").fetchone()
    if plan is None:
        plan = db.execute('SELECT id FROM plans ORDER BY sort_order LIMIT 1').fetchone()
    if plan is not None:
        from datetime import datetime, timedelta, timezone
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=365)
        db.execute('''INSERT INTO subscriptions
                      (company_id,plan_id,status,started_at,current_period_start,current_period_end)
                      VALUES (?,?,'active',?,?,?)''',
                   (cid, plan['id'], start.strftime('%Y-%m-%d %H:%M:%S'),
                    start.strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S')))

    db.commit()
    db.close()
    print('Company : %s' % args.company)
    print('Code    : %s' % slug)
    print('Username: %s' % args.username)
    print('Password: %s' % args.password)


def cmd_add_user(args):
    password = args.password or getpass('New password: ')
    if len(password) < MIN_PASSWORD:
        sys.exit('Password must be at least %d characters' % MIN_PASSWORD)

    role = args.role
    if role not in ('owner', 'admin', 'staff', 'viewer'):
        sys.exit('Unknown role %r (choose owner, admin, staff or viewer)' % role)

    db = connect()
    company = resolve_company(db, args.company)
    exists = db.execute('SELECT id FROM users WHERE company_id=? AND lower(username)=lower(?)',
                        (company['id'], args.username)).fetchone()
    if exists:
        db.close()
        sys.exit('User %r already exists in %s' % (args.username, company['name']))

    db.execute('''INSERT INTO users (company_id,username,password_hash,full_name,email,role,is_active)
                  VALUES (?,?,?,?,?,?,1)''',
               (company['id'], args.username, generate_password_hash(password),
                args.full_name or args.username, args.email, role))
    db.commit()
    db.close()
    print('Company : %s' % company['name'])
    print('Username: %s' % args.username)
    print('Role    : %s' % role)
    print('Password: %s' % password)


def cmd_list_users(args):
    db = connect()
    rows = db.execute('''SELECT c.slug, c.name, u.username, u.role, u.is_active,
                                u.failed_attempts, u.locked_until, u.last_login_at
                         FROM companies c LEFT JOIN users u ON u.company_id = c.id
                         ORDER BY c.id, u.id''').fetchall()
    if not rows:
        print('No companies or users found.')
    for r in rows:
        print('company=%-16s slug=%-16s user=%-14s role=%-7s active=%s failed=%s locked=%s last_login=%s'
              % (r['name'], r['slug'], r['username'], r['role'], r['is_active'],
                 r['failed_attempts'], r['locked_until'] or '-', r['last_login_at'] or '-'))
    db.close()


def resolve_company(db, ref):
    """Look a company up by id, slug or name. Company references are not unique
    enough to guess, so an unknown reference is a hard error."""
    ref = (ref or '').strip()
    row = None
    if ref.isdigit():
        row = db.execute('SELECT id,name,slug FROM companies WHERE id=?', (int(ref),)).fetchone()
    if row is None:
        row = db.execute('SELECT id,name,slug FROM companies WHERE slug=? OR lower(name)=lower(?) LIMIT 1',
                         (ref.lower(), ref.lower())).fetchone()
    if row is None:
        sys.exit('No company found matching %r' % ref)
    return row


def target_users(db, username, company_ref):
    """Return the user rows a command should act on, scoped to one company.

    Users are only unique per company, so the same username can exist in several
    companies. When --company is given we narrow to that tenant. When it is
    omitted we still act if the username is unique platform-wide, but refuse
    rather than touch every company that happens to share the name.
    """
    sql = '''SELECT u.id, u.username, c.name AS company
             FROM users u JOIN companies c ON c.id = u.company_id
             WHERE lower(u.username)=lower(?)'''
    params = [username]
    if company_ref:
        company = resolve_company(db, company_ref)
        sql += ' AND u.company_id=?'
        params.append(company['id'])
    rows = db.execute(sql, params).fetchall()
    if not rows:
        where = ' in company %r' % company_ref if company_ref else ''
        sys.exit('No user found with username %r%s' % (username, where))
    if not company_ref:
        companies = sorted({r['company'] for r in rows})
        if len(companies) > 1:
            sys.exit('Username %r exists in several companies (%s). '
                     'Re-run with --company to pick one.' % (username, ', '.join(companies)))
    return rows


def cmd_reset_password(args):
    password = args.password or getpass('New password: ')
    if len(password) < MIN_PASSWORD:
        sys.exit('Password must be at least %d characters' % MIN_PASSWORD)
    db = connect()
    rows = target_users(db, args.username, args.company)
    ids = [r['id'] for r in rows]
    placeholders = ','.join('?' * len(ids))
    db.execute('''UPDATE users SET password_hash=?, failed_attempts=0,
                  locked_until=NULL, is_active=1 WHERE id IN (%s)''' % placeholders,
               [generate_password_hash(password)] + ids)
    db.commit()
    companies = ', '.join(sorted({r['company'] for r in rows}))
    db.close()
    print('Password reset for %r in %s (%d account/s).' % (args.username, companies, len(ids)))


def cmd_unlock(args):
    db = connect()
    rows = target_users(db, args.username, args.company)
    ids = [r['id'] for r in rows]
    placeholders = ','.join('?' * len(ids))
    db.execute('UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id IN (%s)' % placeholders,
               ids)
    db.commit()
    companies = ', '.join(sorted({r['company'] for r in rows}))
    db.close()
    print('Unlocked %r in %s (%d account/s).' % (args.username, companies, len(ids)))


def main():
    p = argparse.ArgumentParser(description='MCJ Sahan Fleet admin CLI')
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('init-db', help='Create/upgrade the database schema').set_defaults(fn=cmd_init_db)

    s = sub.add_parser('seed', help='Create a company with an owner login')
    s.add_argument('--company', required=True)
    s.add_argument('--username', required=True)
    s.add_argument('--password', required=True)
    s.add_argument('--full-name', dest='full_name')
    s.add_argument('--email')
    s.add_argument('--phone')
    s.set_defaults(fn=cmd_seed)

    s = sub.add_parser('add-user', help='Create a user in an existing company')
    s.add_argument('--company', required=True, help='Company slug, name or id')
    s.add_argument('--username', required=True)
    s.add_argument('--password', help='Omit to be prompted without echo')
    s.add_argument('--role', default='staff', help='owner, admin, staff or viewer (default: staff)')
    s.add_argument('--full-name', dest='full_name')
    s.add_argument('--email')
    s.set_defaults(fn=cmd_add_user)

    sub.add_parser('list-users', help='Show every company and user').set_defaults(fn=cmd_list_users)

    s = sub.add_parser('reset-password', help='Set a new password for one company\'s user')
    s.add_argument('--company', help='Company slug, name or id (required if the username is not unique)')
    s.add_argument('--username', required=True)
    s.add_argument('--password', help='Omit to be prompted without echo')
    s.set_defaults(fn=cmd_reset_password)

    s = sub.add_parser('unlock', help='Clear failed attempts and lockout for one company\'s user')
    s.add_argument('--company', help='Company slug, name or id (required if the username is not unique)')
    s.add_argument('--username', required=True)
    s.set_defaults(fn=cmd_unlock)

    args = p.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()