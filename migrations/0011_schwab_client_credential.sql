-- Phase 8a.5: split Schwab credentials into client (stable) + oauth (rotating).
--
-- 0010 created `credentials` with CHECK including 'schwab_oauth' for the
-- user's access/refresh tokens. Phase 8a.5 needs a second type
-- `schwab_client` to hold the Schwab Developer App's Client ID and Client
-- Secret. These rotate on a different cadence (manual, when the user
-- regenerates them) vs the OAuth tokens (every 30 min / 7 days).
--
-- SQLite requires recreating the table to alter a CHECK constraint, so
-- we copy the existing rows verbatim. Phase 8a hasn't written any rows
-- in production (the page is disabled), but the migration handles them
-- regardless.

PRAGMA foreign_keys = OFF;

CREATE TABLE credentials_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    credential_type TEXT NOT NULL CHECK (credential_type IN (
        'alpaca_paper',
        'alpaca_live',
        'schwab_client',
        'schwab_oauth',
        'finnhub',
        'exa'
    )),
    encrypted_data TEXT NOT NULL,
    expires_at REAL,
    refresh_token_expires_at REAL,
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL,
    last_used_ts REAL,
    created_by_user_id INTEGER,
    notes TEXT,
    UNIQUE(credential_type)
);

INSERT INTO credentials_new (
    id, credential_type, encrypted_data, expires_at, refresh_token_expires_at,
    created_ts, updated_ts, last_used_ts, created_by_user_id, notes
)
SELECT
    id, credential_type, encrypted_data, expires_at, refresh_token_expires_at,
    created_ts, updated_ts, last_used_ts, created_by_user_id, notes
FROM credentials;

DROP TABLE credentials;
ALTER TABLE credentials_new RENAME TO credentials;

CREATE INDEX IF NOT EXISTS idx_credentials_type ON credentials(credential_type);

PRAGMA foreign_keys = ON;
