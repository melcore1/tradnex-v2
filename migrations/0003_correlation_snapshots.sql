CREATE TABLE IF NOT EXISTS correlation_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ticker_a TEXT NOT NULL,
    ticker_b TEXT NOT NULL,
    correlation REAL NOT NULL,
    lookback_days INTEGER NOT NULL,
    computed_ts REAL NOT NULL,
    UNIQUE(date, ticker_a, ticker_b)
);

CREATE INDEX IF NOT EXISTS idx_correlation_date
    ON correlation_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_correlation_ticker_a
    ON correlation_snapshots(ticker_a);
