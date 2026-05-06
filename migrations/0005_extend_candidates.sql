-- Phase 3: extend candidates for entry/exit + introduce scanner_evaluations.
--
-- Existing candidates columns (indicators_json, veto_trace_json, llm_decision_json,
-- direction, status, etc.) are preserved untouched. Phase 3 inserts use the
-- new *_json columns; status defaults to 'pending'.
--
-- Position lifecycle: Phase 3 only ever writes 'open' to positions.status.
-- Phase 3.5 will need its own migration to widen the existing CHECK to admit
-- 'closing_pending_approval', 'closing', and 'closed'.

ALTER TABLE candidates ADD COLUMN candidate_kind TEXT NOT NULL DEFAULT 'entry'
    CHECK (candidate_kind IN ('entry', 'exit'));
ALTER TABLE candidates ADD COLUMN strategy_name TEXT NOT NULL DEFAULT 'long_options_momentum';
ALTER TABLE candidates ADD COLUMN rule_trace_json TEXT;
ALTER TABLE candidates ADD COLUMN regime_snapshot_json TEXT;
ALTER TABLE candidates ADD COLUMN overrides_applied_json TEXT;
ALTER TABLE candidates ADD COLUMN shortlist_json TEXT;
ALTER TABLE candidates ADD COLUMN full_analysis_json TEXT;
ALTER TABLE candidates ADD COLUMN options_analysis_json TEXT;
ALTER TABLE candidates ADD COLUMN position_id INTEGER REFERENCES positions(id);

CREATE INDEX IF NOT EXISTS idx_candidates_kind ON candidates(candidate_kind);
CREATE INDEX IF NOT EXISTS idx_candidates_strategy ON candidates(strategy_name);

CREATE TABLE IF NOT EXISTS scanner_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    fired INTEGER NOT NULL CHECK (fired IN (0, 1)),
    rule_trace_json TEXT NOT NULL,
    full_analysis_summary TEXT,
    options_analysis_summary TEXT,
    regime_summary TEXT,
    candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
    timestamp REAL NOT NULL,
    cycle_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scanner_eval_ticker ON scanner_evaluations(ticker);
CREATE INDEX IF NOT EXISTS idx_scanner_eval_cycle ON scanner_evaluations(cycle_id);
CREATE INDEX IF NOT EXISTS idx_scanner_eval_timestamp ON scanner_evaluations(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_scanner_eval_fired ON scanner_evaluations(fired);
