-- 0004 - Per-company ledger categories
CREATE TABLE IF NOT EXISTS ledger_categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('income','expense')),
  name TEXT NOT NULL,
  sort_order INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,
  UNIQUE(company_id, kind, lower(name))
);

CREATE INDEX IF NOT EXISTS idx_ledger_cat_company ON ledger_categories(company_id, kind, active);
