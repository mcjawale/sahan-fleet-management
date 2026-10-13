-- 0002 - Per-company user accounts
--
-- Why: the users table had `username TEXT NOT NULL UNIQUE`, a GLOBAL constraint.
-- On a multi-tenant system that means only one company in the whole platform can
-- own the username "admin". With ~200 self-registered companies the second
-- signup would fail on a name everybody wants.
--
-- This migration:
--   1. adds failed_attempts / locked_until for brute-force protection,
--   2. rebuilds users with UNIQUE(company_id, username) instead of a global
--      UNIQUE(username),
--   3. keeps every existing user row and its company_id.
--
-- SQLite cannot drop a UNIQUE constraint in place, so the standard
-- create-new / copy / drop / rename dance is used. The rebuild is done inside
-- a transaction and disables foreign_keys only for the swap; audit_log.user_id
-- is remapped by id so no audit history is lost.

PRAGMA foreign_keys=OFF;

BEGIN;

CREATE TABLE IF NOT EXISTS users_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  username TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT,
  email TEXT,
  role TEXT NOT NULL DEFAULT 'staff' CHECK (role IN ('owner','admin','staff','viewer')),
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  last_login_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (company_id, username)
);

INSERT INTO users_new
  (id, company_id, username, password_hash, full_name, email, role, is_active,
   failed_attempts, locked_until, last_login_at, created_at)
SELECT
  id, company_id, username, password_hash, full_name, email, role, is_active,
  0, NULL, last_login_at, created_at
FROM users;

DROP TABLE users;
ALTER TABLE users_new RENAME TO users;

CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(lower(email));

COMMIT;

PRAGMA foreign_keys=ON;

-- After this migration, a company can be registered even when another company
-- already has a user called "admin":
--
--   INSERT INTO users (company_id, username, password_hash, role)
--   SELECT id, 'admin', '<hash>', 'owner' FROM companies WHERE slug = 'acme';