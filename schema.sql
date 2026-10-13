-- MCJ Sahan Fleet Management System - Schema
-- Multi-tenant + billing scaffolding

PRAGMA foreign_keys=ON;

-- Companies (tenants)
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  contact_email TEXT,
  phone TEXT,
  country TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Users
-- A user belongs to exactly one company. Usernames are unique WITHIN a company
-- (not globally) so every company can have its own "admin" / "dispatcher".
CREATE TABLE IF NOT EXISTS users (
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
CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(lower(email));

-- Audit
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  entity TEXT,
  entity_id TEXT,
  detail TEXT,
  ip_address TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_company ON audit_log(company_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity  ON audit_log(company_id, entity, entity_id);

-- Plans
CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  price_cents INTEGER NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
  currency TEXT NOT NULL DEFAULT 'USD',
  trial_days INTEGER NOT NULL DEFAULT 0,
  max_vehicles INTEGER NOT NULL DEFAULT -1,
  max_users INTEGER NOT NULL DEFAULT -1,
  max_trips_per_month INTEGER NOT NULL DEFAULT -1,
  max_storage_mb INTEGER NOT NULL DEFAULT -1,
  features TEXT NOT NULL DEFAULT '{}',
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  sort_order INTEGER NOT NULL DEFAULT 0
);

-- Subscriptions
CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  plan_id INTEGER NOT NULL REFERENCES plans(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('trialing','active','past_due','canceled','expired')),
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  current_period_start TEXT NOT NULL,
  current_period_end TEXT NOT NULL,
  cancel_at_period_end INTEGER NOT NULL DEFAULT 0 CHECK (cancel_at_period_end IN (0,1)),
  canceled_at TEXT,
  provider TEXT,
  provider_customer_id TEXT,
  provider_subscription_id TEXT UNIQUE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sub_active_company ON subscriptions(company_id)
  WHERE status IN ('trialing','active','past_due');

-- Invoices
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
  number TEXT NOT NULL UNIQUE,
  amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
  currency TEXT NOT NULL DEFAULT 'USD',
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','open','paid','void','uncollectible')),
  period_start TEXT,
  period_end TEXT,
  issued_at TEXT,
  paid_at TEXT,
  provider_invoice_id TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_invoices_company ON invoices(company_id, issued_at DESC);

-- Fleet
CREATE TABLE IF NOT EXISTS vehicles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  plate_no TEXT NOT NULL,
  make TEXT,
  model TEXT,
  year INTEGER,
  capacity INTEGER DEFAULT 0,
  odometer INTEGER NOT NULL DEFAULT 0,
  status TEXT DEFAULT 'available' CHECK (status IN ('available','in service','maintenance','retired')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(company_id, plate_no)
);
CREATE INDEX IF NOT EXISTS idx_vehicles_company ON vehicles(company_id);

CREATE TABLE IF NOT EXISTS drivers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  phone TEXT,
  licence_no TEXT,
  licence_expiry TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_drivers_company ON drivers(company_id);

CREATE TABLE IF NOT EXISTS routes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  origin TEXT,
  destination TEXT,
  distance_km REAL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(company_id, name)
);
CREATE INDEX IF NOT EXISTS idx_routes_company ON routes(company_id);

-- Ops
CREATE TABLE IF NOT EXISTS trips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  trip_no TEXT NOT NULL,
  vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
  driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
  route_id INTEGER REFERENCES routes(id) ON DELETE SET NULL,
  departure_at TEXT,
  arrival_at TEXT,
  distance_km REAL DEFAULT 0,
  seats INTEGER DEFAULT 0,
  revenue_cents INTEGER NOT NULL DEFAULT 0,
  cost_cents INTEGER NOT NULL DEFAULT 0,
  fuel_cents INTEGER DEFAULT 0,
  status TEXT DEFAULT 'scheduled' CHECK (status IN ('scheduled','in transit','completed','cancelled')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(company_id, trip_no)
);
CREATE INDEX IF NOT EXISTS idx_trips_company ON trips(company_id);
CREATE INDEX IF NOT EXISTS idx_trips_status ON trips(company_id, status);

CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  booking_no TEXT NOT NULL,
  trip_id INTEGER REFERENCES trips(id) ON DELETE SET NULL,
  passenger_name TEXT NOT NULL,
  phone TEXT,
  pickup TEXT,
  dropoff TEXT,
  seats INTEGER NOT NULL DEFAULT 1,
  fare_cents INTEGER NOT NULL DEFAULT 0,
  status TEXT DEFAULT 'booked' CHECK (status IN ('booked','cancelled','completed')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(company_id, booking_no)
);
CREATE INDEX IF NOT EXISTS idx_bookings_company ON bookings(company_id);

-- Records
CREATE TABLE IF NOT EXISTS fuel_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
  driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
  trip_id INTEGER REFERENCES trips(id) ON DELETE SET NULL,
  amount_cents INTEGER NOT NULL DEFAULT 0,
  quantity_l REAL,
  odometer INTEGER,
  date TEXT NOT NULL DEFAULT (date('now')),
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fuel_company ON fuel_records(company_id);

CREATE TABLE IF NOT EXISTS maintenance_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
  work TEXT NOT NULL,
  status TEXT DEFAULT 'open' CHECK (status IN ('open','in progress','done')),
  cost_cents INTEGER DEFAULT 0,
  date TEXT NOT NULL DEFAULT (date('now')),
  next_due TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_maint_company ON maintenance_records(company_id);

INSERT OR IGNORE INTO plans (code,name,price_cents,trial_days,max_vehicles,max_users,max_trips_per_month,features,sort_order)
VALUES
('free','Free',0,0,2,2,-1,'{}',1),
('standard','Standard',2900,14,25,10,500,'{"pdf_exports":true,"maintenance_scheduling":true}',2),
('fleet','Fleet',9900,14,-1,-1,-1,'{"pdf_exports":true,"maintenance_scheduling":true,"gps_tracking":true,"fuel_analytics":true,"api_access":true,"multi_branch":true}',3);
