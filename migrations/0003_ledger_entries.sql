-- 0003 - Income / expense ledger
--
-- Companies asked for a proper accounting section on the mobile app.
-- Trip revenue/cost, fuel and maintenance money already live on their own
-- tables; this table records everything else: salaries, office costs,
-- rentals, booking fares, one-off income, etc.
--
-- kind  : 'income' or 'expense'
-- category is a free-ish label validated against a fixed list in
-- app/mobile/routes.py (LEDGER_CATEGORIES) so reports stay groupable.
-- All money is integer cents, matching the rest of the schema.

CREATE TABLE IF NOT EXISTS ledger_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('income','expense')),
  category TEXT NOT NULL DEFAULT 'Other income',
  description TEXT NOT NULL,
  amount_cents INTEGER NOT NULL DEFAULT 0,
  entry_date TEXT NOT NULL DEFAULT (date('now')),
  vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ledger_company_date ON ledger_entries(company_id, entry_date);
