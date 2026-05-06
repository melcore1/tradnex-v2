-- Phase 6: single-user auth + sessions + login rate-limit audit.
--
-- Auth model: bcrypt-hashed password; session cookie = random UUID looked
-- up in `sessions`. No JWT, no signed cookies — DB lookup keeps revocation
-- simple. Login rate-limiting reads `login_attempts` to enforce the lockout
-- window (≥5 failures from the same email in 15 min → 1-hour lockout).
--
-- Toggles continue to live in strategy_configs.settings_json. No new
-- columns needed; readers default to the safe value when keys are absent.
-- Canonical keys:
--   paused         (existing, scanner pause)
--   monitor_paused (new, default false)
--   llm_enabled    (new, default true)

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_ts REAL NOT NULL,
    last_login_ts REAL,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until_ts REAL
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_ts REAL NOT NULL,
    expires_ts REAL NOT NULL,
    last_activity_ts REAL NOT NULL,
    user_agent TEXT,
    ip_address TEXT,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1)),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_ts);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(revoked) WHERE revoked = 0;

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    ip_address TEXT,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    timestamp REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_email_time
    ON login_attempts(email, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_login_attempts_time ON login_attempts(timestamp);
