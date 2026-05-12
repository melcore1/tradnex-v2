-- Phase 8.7: add 'mcp_api_key' credential type for the MCP server.
--
-- The MCP server (services/mcp/) authenticates remote callers (Claude.ai)
-- via a single shared Bearer token. We persist that token through the
-- existing encrypted credentials store. Same CHECK-widening pattern used in
-- Phases 4, 5, 8a, and 8a.5.

PRAGMA foreign_keys = OFF;

CREATE TABLE credentials_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    credential_type TEXT NOT NULL CHECK (credential_type IN (
        'alpaca_paper',
        'alpaca_live',
        'schwab_client',
        'schwab_oauth',
        'finnhub',
        'exa',
        'mcp_api_key'
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
