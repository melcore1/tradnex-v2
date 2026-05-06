-- Phase 4: orchestrator routing layer.
--
-- 1. Recreate `candidates` to widen the status CHECK admitting the new
--    orchestrator states (processing_vetoes, pending_llm_evaluation,
--    rejected_by_llm, rejected_by_user). The recreation runs with
--    foreign_keys OFF so existing FK references from positions /
--    scanner_evaluations / monitor_evaluations survive intact.
-- 2. Add calendar_cache (Finnhub-backed economic + earnings events).
-- 3. Add veto_traces (full trace per candidate, queryable separately
--    from the JSON column on candidates).

PRAGMA foreign_keys = OFF;

CREATE TABLE candidates_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long_call','long_put')),
    status TEXT NOT NULL CHECK (status IN (
        'pending',
        'processing_vetoes',
        'rules_passed',
        'vetoed',
        'evaluated',
        'pending_llm_evaluation',
        'pending_human_approval',
        'rejected_by_llm',
        'rejected',
        'rejected_by_user',
        'approved',
        'placed',
        'failed'
    )),
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL,
    indicators_json TEXT NOT NULL DEFAULT '{}',
    veto_trace_json TEXT NOT NULL DEFAULT '{}',
    llm_decision_json TEXT NOT NULL DEFAULT '{}',
    human_decision TEXT,
    human_decision_ts REAL,
    order_id TEXT,
    candidate_kind TEXT NOT NULL DEFAULT 'entry'
        CHECK (candidate_kind IN ('entry', 'exit')),
    strategy_name TEXT NOT NULL DEFAULT 'long_options_momentum',
    rule_trace_json TEXT,
    regime_snapshot_json TEXT,
    overrides_applied_json TEXT,
    shortlist_json TEXT,
    full_analysis_json TEXT,
    options_analysis_json TEXT,
    position_id INTEGER REFERENCES positions(id)
);

INSERT INTO candidates_new (
    id, ticker, direction, status, created_ts, updated_ts,
    indicators_json, veto_trace_json, llm_decision_json,
    human_decision, human_decision_ts, order_id,
    candidate_kind, strategy_name, rule_trace_json, regime_snapshot_json,
    overrides_applied_json, shortlist_json, full_analysis_json,
    options_analysis_json, position_id
)
SELECT
    id, ticker, direction, status, created_ts, updated_ts,
    indicators_json, veto_trace_json, llm_decision_json,
    human_decision, human_decision_ts, order_id,
    candidate_kind, strategy_name, rule_trace_json, regime_snapshot_json,
    overrides_applied_json, shortlist_json, full_analysis_json,
    options_analysis_json, position_id
FROM candidates;

DROP TABLE candidates;
ALTER TABLE candidates_new RENAME TO candidates;

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_ticker ON candidates(ticker);
CREATE INDEX IF NOT EXISTS idx_candidates_kind ON candidates(candidate_kind);
CREATE INDEX IF NOT EXISTS idx_candidates_strategy ON candidates(strategy_name);

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS calendar_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL CHECK (event_type IN ('economic', 'earnings')),
    ticker TEXT,
    event_name TEXT NOT NULL,
    event_datetime_utc REAL NOT NULL,
    impact TEXT CHECK (impact IN ('low', 'medium', 'high', 'unknown')),
    source TEXT NOT NULL,
    payload_json TEXT,
    fetched_ts REAL NOT NULL,
    UNIQUE(event_type, ticker, event_name, event_datetime_utc)
);
CREATE INDEX IF NOT EXISTS idx_calendar_datetime ON calendar_cache(event_datetime_utc);
CREATE INDEX IF NOT EXISTS idx_calendar_ticker ON calendar_cache(ticker);
CREATE INDEX IF NOT EXISTS idx_calendar_event_type ON calendar_cache(event_type);

CREATE TABLE IF NOT EXISTS veto_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    veto_set TEXT NOT NULL CHECK (veto_set IN ('entry', 'exit')),
    trace_json TEXT NOT NULL,
    any_failed INTEGER NOT NULL CHECK (any_failed IN (0, 1)),
    failed_veto_names_json TEXT,
    timestamp REAL NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_veto_trace_candidate ON veto_traces(candidate_id);
CREATE INDEX IF NOT EXISTS idx_veto_trace_failed ON veto_traces(any_failed);
