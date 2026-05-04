CREATE TABLE IF NOT EXISTS events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  service         TEXT NOT NULL,
  level           TEXT NOT NULL CHECK (level IN ('info','warn','error','critical')),
  event_type      TEXT NOT NULL,
  payload         TEXT NOT NULL DEFAULT '{}',
  timestamp       REAL NOT NULL,
  idempotency_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_events_service_ts ON events(service, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type       ON events(event_type);

CREATE TABLE IF NOT EXISTS candidates (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker             TEXT NOT NULL,
  direction          TEXT NOT NULL CHECK (direction IN ('long_call','long_put')),
  status             TEXT NOT NULL CHECK (status IN (
                       'pending','rules_passed','vetoed','evaluated',
                       'approved','rejected','pending_human_approval','placed','failed')),
  created_ts         REAL NOT NULL,
  updated_ts         REAL NOT NULL,
  indicators_json    TEXT NOT NULL DEFAULT '{}',
  veto_trace_json    TEXT NOT NULL DEFAULT '{}',
  llm_decision_json  TEXT NOT NULL DEFAULT '{}',
  human_decision     TEXT,
  human_decision_ts  REAL,
  order_id           TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_ticker ON candidates(ticker);

CREATE TABLE IF NOT EXISTS strategy_configs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,
  settings_json TEXT NOT NULL DEFAULT '{}',
  is_active     INTEGER NOT NULL DEFAULT 0,
  created_ts    REAL NOT NULL,
  updated_ts    REAL NOT NULL
);

INSERT OR IGNORE INTO strategy_configs (name, settings_json, is_active, created_ts, updated_ts)
VALUES ('default', '{}', 1, strftime('%s','now'), strftime('%s','now'));

CREATE TABLE IF NOT EXISTS positions (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  candidate_id     INTEGER REFERENCES candidates(id),
  ticker           TEXT NOT NULL,
  contract_symbol  TEXT NOT NULL,
  side             TEXT NOT NULL,
  quantity         INTEGER NOT NULL,
  entry_price      REAL NOT NULL,
  entry_ts         REAL NOT NULL,
  exit_price       REAL,
  exit_ts          REAL,
  exit_reason      TEXT,
  pnl              REAL,
  status           TEXT NOT NULL CHECK (status IN ('open','closed'))
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker);

CREATE TABLE IF NOT EXISTS daily_iv_snapshots (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker       TEXT NOT NULL,
  date         TEXT NOT NULL,
  iv_30d       REAL NOT NULL,
  iv_60d       REAL,
  iv_90d       REAL,
  atm_iv       REAL,
  recorded_ts  REAL NOT NULL,
  UNIQUE (ticker, date)
);
