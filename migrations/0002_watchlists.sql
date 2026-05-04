CREATE TABLE IF NOT EXISTS watchlists (
  id                          INTEGER PRIMARY KEY AUTOINCREMENT,
  date                        TEXT NOT NULL UNIQUE,
  tickers_json                TEXT NOT NULL DEFAULT '[]',
  per_ticker_overrides_json   TEXT NOT NULL DEFAULT '{}',
  notes                       TEXT,
  created_ts                  REAL NOT NULL,
  created_by                  TEXT NOT NULL CHECK (created_by IN
                                ('manual','auto_carry_forward','system'))
);
CREATE INDEX IF NOT EXISTS idx_watchlists_date_desc ON watchlists(date DESC);
