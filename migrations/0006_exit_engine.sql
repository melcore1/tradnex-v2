-- Phase 3.5: exit engine — position lifecycle events + monitor evaluations.
--
-- Note: positions.status CHECK ('open'|'closed') is intentionally NOT widened.
-- Intermediate lifecycle states (exit_candidate_pending, closing, etc.) live
-- in position_lifecycle_events.event_type. Phase 3.5 writes only 'open' and
-- 'closed' to positions.status; the lifecycle table is the source of truth
-- for granular state.

CREATE TABLE IF NOT EXISTS position_lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'opened',
        'monitor_evaluated',
        'signal_fired',
        'auto_close_triggered',
        'exit_candidate_created',
        'claude_evaluated',
        'human_approved',
        'human_rejected',
        'closing',
        'closed',
        'close_failed'
    )),
    cycle_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    timestamp REAL NOT NULL,
    FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pos_lifecycle_position
    ON position_lifecycle_events(position_id);
CREATE INDEX IF NOT EXISTS idx_pos_lifecycle_timestamp
    ON position_lifecycle_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_pos_lifecycle_event_type
    ON position_lifecycle_events(event_type);

CREATE TABLE IF NOT EXISTS monitor_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    cycle_id TEXT NOT NULL,
    current_pnl_pct REAL,
    current_pnl_dollars REAL,
    current_delta REAL,
    current_iv REAL,
    dte_remaining INTEGER,
    signal_trace_json TEXT NOT NULL,
    signals_fired_count INTEGER NOT NULL,
    auto_close_triggered INTEGER NOT NULL DEFAULT 0
        CHECK (auto_close_triggered IN (0, 1)),
    exit_candidate_id INTEGER,
    underlying_summary TEXT,
    halt_status_at_eval TEXT,
    timestamp REAL NOT NULL,
    FOREIGN KEY (position_id) REFERENCES positions(id) ON DELETE CASCADE,
    FOREIGN KEY (exit_candidate_id) REFERENCES candidates(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_monitor_eval_position
    ON monitor_evaluations(position_id);
CREATE INDEX IF NOT EXISTS idx_monitor_eval_cycle
    ON monitor_evaluations(cycle_id);
CREATE INDEX IF NOT EXISTS idx_monitor_eval_timestamp
    ON monitor_evaluations(timestamp DESC);

ALTER TABLE positions ADD COLUMN entry_candidate_id INTEGER REFERENCES candidates(id);
ALTER TABLE positions ADD COLUMN exit_candidate_id INTEGER REFERENCES candidates(id);
ALTER TABLE positions ADD COLUMN strategy_name TEXT NOT NULL DEFAULT 'long_options_momentum';
ALTER TABLE positions ADD COLUMN entry_iv REAL;
ALTER TABLE positions ADD COLUMN entry_delta REAL;
ALTER TABLE positions ADD COLUMN entry_dte INTEGER;
