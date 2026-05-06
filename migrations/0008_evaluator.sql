-- Phase 5: Claude evaluator + Exa news + prompt versioning.
--
-- 1. Recreate `candidates` to (a) widen status CHECK with
--    `processing_llm_evaluation` and `held`, and (b) add a new
--    `selected_contract_json` column (the chosen option contract from
--    shortlist; written by either the LLM evaluator or the rule-based
--    fallback).
-- 2. Add `prompt_versions` (frontend-editable, history-preserving).
-- 3. Add `llm_evaluations` (one row per evaluation attempt — Claude
--    success, Claude failure, fallback path, all persisted).

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
        'processing_llm_evaluation',
        'pending_human_approval',
        'rejected_by_llm',
        'held',
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
    position_id INTEGER REFERENCES positions(id),
    selected_contract_json TEXT
);

INSERT INTO candidates_new (
    id, ticker, direction, status, created_ts, updated_ts,
    indicators_json, veto_trace_json, llm_decision_json,
    human_decision, human_decision_ts, order_id,
    candidate_kind, strategy_name, rule_trace_json, regime_snapshot_json,
    overrides_applied_json, shortlist_json, full_analysis_json,
    options_analysis_json, position_id, selected_contract_json
)
SELECT
    id, ticker, direction, status, created_ts, updated_ts,
    indicators_json, veto_trace_json, llm_decision_json,
    human_decision, human_decision_ts, order_id,
    candidate_kind, strategy_name, rule_trace_json, regime_snapshot_json,
    overrides_applied_json, shortlist_json, full_analysis_json,
    options_analysis_json, position_id, NULL
FROM candidates;

DROP TABLE candidates;
ALTER TABLE candidates_new RENAME TO candidates;

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_ticker ON candidates(ticker);
CREATE INDEX IF NOT EXISTS idx_candidates_kind ON candidates(candidate_kind);
CREATE INDEX IF NOT EXISTS idx_candidates_strategy ON candidates(strategy_name);

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name TEXT NOT NULL CHECK (template_name IN
        ('entry_evaluation', 'exit_evaluation')),
    version_number INTEGER NOT NULL,
    template_text TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('active', 'pending', 'deprecated', 'archived')),
    created_ts REAL NOT NULL,
    created_by TEXT NOT NULL,
    activated_ts REAL,
    deprecated_ts REAL,
    notes TEXT,
    UNIQUE(template_name, version_number)
);

-- Partial UNIQUE: at most one active per template at all times.
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_one_active
    ON prompt_versions(template_name)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_prompt_template_status
    ON prompt_versions(template_name, status);

CREATE TABLE IF NOT EXISTS llm_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    prompt_version_id INTEGER NOT NULL,
    prompt_template_name TEXT NOT NULL,
    full_prompt_text TEXT NOT NULL,
    raw_response_text TEXT NOT NULL,
    parsed_response_json TEXT NOT NULL,
    decision TEXT NOT NULL,
    confidence REAL,
    reasoning TEXT NOT NULL,
    exa_articles_json TEXT,
    elapsed_ms INTEGER NOT NULL,
    model_used TEXT NOT NULL,
    fallback_used INTEGER NOT NULL DEFAULT 0
        CHECK (fallback_used IN (0, 1)),
    fallback_reason TEXT,
    error TEXT,
    timestamp REAL NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_version_id) REFERENCES prompt_versions(id)
);

CREATE INDEX IF NOT EXISTS idx_llm_eval_candidate ON llm_evaluations(candidate_id);
CREATE INDEX IF NOT EXISTS idx_llm_eval_decision  ON llm_evaluations(decision);
CREATE INDEX IF NOT EXISTS idx_llm_eval_timestamp ON llm_evaluations(timestamp DESC);
