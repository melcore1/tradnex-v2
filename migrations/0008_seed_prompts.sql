-- Phase 5: seed v1 entry + exit prompt versions.
--
-- Templates use simple {variable} substitution (no Jinja). The schema_json
-- column stores a JSON Schema dict the evaluator validates Claude's output
-- against.
--
-- Both rows are inserted as `active` — partial UNIQUE index admits a single
-- active row per template_name, and the table is empty for both templates
-- before this migration runs.

INSERT INTO prompt_versions (
    template_name, version_number, template_text, schema_json,
    status, created_ts, created_by, activated_ts, notes
) VALUES (
    'entry_evaluation', 1,
    'You are a quantitative options trader evaluating a candidate trade.

Return a single JSON object (no markdown, no prose, no code fences) matching
this schema:
{{
  "decision":          "STRONG" | "MODERATE" | "WEAK" | "VETO",
  "confidence":        0.0-1.0,
  "reasoning":         "<2-4 sentence explanation>",
  "selected_contract": {{"symbol": "<contract_symbol_from_shortlist>"}}
}}

Pick exactly one symbol from the shortlist (or omit selected_contract if you
return VETO). Decision STRONG means fire confidently; MODERATE/WEAK reduce
sizing; VETO means skip.

== Candidate ==
ticker:        {ticker}
direction:     {direction}
rule_confidence: {confidence}

== Rule trace ==
{rule_trace}

== Regime ==
{regime}

== Full analysis ==
{full_analysis}

== Options analysis ==
{options_analysis}

== Calendar (next 14 days) ==
{calendar_context}

== News articles (Exa, last 7 days) ==
{exa_articles}

== Shortlist (pick one) ==
{shortlist}

Respond with the JSON object only.',
    '{"type":"object","required":["decision","reasoning"],"properties":{"decision":{"type":"string","enum":["STRONG","MODERATE","WEAK","VETO"]},"confidence":{"type":"number","minimum":0,"maximum":1},"reasoning":{"type":"string"},"selected_contract":{"type":"object","properties":{"symbol":{"type":"string"}}}}}',
    'active',
    strftime('%s','now'),
    'system',
    strftime('%s','now'),
    'Phase 5 seed — initial entry-evaluation prompt'
);

INSERT INTO prompt_versions (
    template_name, version_number, template_text, schema_json,
    status, created_ts, created_by, activated_ts, notes
) VALUES (
    'exit_evaluation', 1,
    'You are a quantitative options trader evaluating whether to close an
existing position.

Return a single JSON object (no markdown, no prose, no code fences) matching
this schema:
{{
  "decision":   "CLOSE" | "CLOSE_PARTIAL" | "HOLD",
  "confidence": 0.0-1.0,
  "reasoning":  "<2-4 sentence explanation>",
  "quantity":   <integer if CLOSE_PARTIAL, else omit>
}}

CLOSE = close the entire position. CLOSE_PARTIAL = close a portion (set
quantity to the contracts to close, must be < current_quantity). HOLD =
keep the position open.

== Position ==
ticker:           {ticker}
position_id:      {position_id}
contract_symbol:  {contract_symbol}
side:             {side}
quantity:         {quantity}
entry_price:      {entry_price}
entry_ts:         {entry_ts}
current_pnl_pct:  {pnl_pct}
current_pnl_usd:  {pnl_dollars}
dte_remaining:    {dte_remaining}

== Exit signal trace ==
{signal_trace}

== Triggered signals ==
{triggered_signals}

== Regime ==
{regime}

== Calendar (next 14 days) ==
{calendar_context}

== News articles (Exa, last 7 days) ==
{exa_articles}

Respond with the JSON object only.',
    '{"type":"object","required":["decision","reasoning"],"properties":{"decision":{"type":"string","enum":["CLOSE","CLOSE_PARTIAL","HOLD"]},"confidence":{"type":"number","minimum":0,"maximum":1},"reasoning":{"type":"string"},"quantity":{"type":"integer","minimum":1}}}',
    'active',
    strftime('%s','now'),
    'system',
    strftime('%s','now'),
    'Phase 5 seed — initial exit-evaluation prompt'
);
