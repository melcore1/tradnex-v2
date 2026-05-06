-- Phase 8a: encrypted credentials store.
--
-- One row per credential type. The actual secret values live as Fernet-encrypted
-- JSON in `encrypted_data`. Frontend reads metadata only via the API; secrets
-- never leave the DB.
--
-- Future Phase 8b/8c add `alpaca_paper`, `alpaca_live`, `schwab_oauth` as
-- valid credential types. Phase 8a only uses `finnhub`, `exa` for the env→DB
-- migration path; the table itself accepts all six values from day one so we
-- don't need a CHECK-constraint migration later.

CREATE TABLE IF NOT EXISTS credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    credential_type TEXT NOT NULL CHECK (credential_type IN (
        'alpaca_paper',
        'alpaca_live',
        'schwab_oauth',
        'finnhub',
        'exa'
    )),
    -- Fernet-encrypted JSON blob containing the actual secret values.
    encrypted_data TEXT NOT NULL,

    -- For OAuth tokens (Schwab); NULL for plain API keys.
    expires_at REAL,
    refresh_token_expires_at REAL,

    -- Audit
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL,
    last_used_ts REAL,
    created_by_user_id INTEGER,
    notes TEXT,

    -- Exactly one row per type.
    UNIQUE(credential_type)
);

CREATE INDEX IF NOT EXISTS idx_credentials_type ON credentials(credential_type);
