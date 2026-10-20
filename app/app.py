from flask import Flask, session, g, redirect, url_for
from datetime import timedelta
import sqlite3
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
INSTANCE_DIR = ROOT_DIR / 'instance'
TEMPLATE_DIR = ROOT_DIR / 'templates'
STATIC_DIR = ROOT_DIR / 'static'
SCHEMA_PATH = ROOT_DIR / 'schema.sql'
DB_PATH = INSTANCE_DIR / 'sahan_fleet.sqlite'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
        db = g._database = sqlite3.connect(DB_PATH, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=30000')
    return db

def init_db(app):
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        db.commit()

def create_app():
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path='/static',
                template_folder=str(TEMPLATE_DIR))
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-key-change-later'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '0') == '1'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=14)
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

    @app.teardown_appcontext
    def close_db(e=None):
        db = getattr(g, '_database', None)
        if db is not None:
            db.close()

    @app.before_request
    def load_user():
        g.user = None
        g.user_id = None
        g.company = None
        g.company_id = None
        uid = session.get('user_id')
        if uid:
            cur = get_db().execute('''SELECT id,company_id,username,full_name,role,is_active,email
                                      FROM users WHERE id=? AND is_active=1''', (uid,))
            u = cur.fetchone()
            if u:
                g.user = dict(u)
                g.user_id = u['id']
                g.company_id = u['company_id']
                c = get_db().execute('SELECT id,name,slug,is_active FROM companies WHERE id=?', (g.company_id,))
                cr = c.fetchone()
                if cr and cr['is_active'] == 1:
                    g.company = dict(cr)

        from tenancy import resolve_from_url
        resolve_from_url()

    from .auth.routes import bp as auth_bp
    from .dashboard.routes import bp as dash_bp
    from .users.routes import bp as users_bp
    from .fleet.routes import bp as fleet_bp
    from .ops.routes import bp as ops_bp
    from .records.routes import bp as rec_bp
    from .export.routes import bp as exp_bp
    from .billing.routes import bp as bill_bp
    from .ledger.routes import bp as ledger_bp
    from .mobile.routes import bp as mobile_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(dash_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(fleet_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(rec_bp)
    app.register_blueprint(exp_bp)
    app.register_blueprint(bill_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(mobile_bp)

    @app.route('/sw.js')
    def service_worker():
        return app.send_static_file('sw.js')

    @app.route('/m')
    def mobile_home():
        return redirect(url_for('mobile.index'))

    @app.route('/')
    def home():
        if g.user:
            if g.company and g.company.get('slug'):
                return redirect(url_for('dashboard.index', slug=g.company['slug']))
            return redirect(url_for('auth.profile'))
        return redirect(url_for('auth.login'))

    app.init_db = lambda: init_db(app)
    return app
