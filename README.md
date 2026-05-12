# TradNex 2

Personal autonomous paper-options-trading research system.
A scanner generates candidates, an LLM evaluator filters them with calendar + news context, and a human approves before any paper order is placed.

## Run locally

Two paths — Docker (with the dev override) or a Python venv. The venv path is what Phase 0 verification used and works without any container runtime.

### Docker (with the dev override)

    cp .env.example .env
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

The override builds the image as `tradnex:dev`, bind-mounts your source tree (so edits reflect without rebuild), and runs the container as your host uid (default 1000) to avoid bind-mount permission issues. If your host uid differs, set `TRADNEX_UID` / `TRADNEX_GID` in `.env`.

Without the override, `docker compose up` pulls `ghcr.io/melcore1/tradnex-v2:latest` from GHCR — the same path Dockge uses in production.

### Python venv

    python3 -m venv .venv
    .venv/bin/pip install ".[dev]"
    cp .env.example .env
    DATABASE_PATH=./data/tradnex.db .venv/bin/python -m services.data.main

## Run smoke test

With the venv:

    .venv/bin/python -m pytest tests/

With Docker:

    docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm data python -m pytest

## Deployment

The backend is published as a single container image to GitHub Container Registry on every push to `main`:

- Image: `ghcr.io/melcore1/tradnex-v2`
- Tags: `latest` (always points at most recent main) + `sha-<short>` (immutable per commit)
- Platform: `linux/amd64`
- Visibility: **public** — no auth needed to pull

All five backend services run from the same image; they differ only by the `command:` in compose.

### TrueNAS Dockge

1. In Dockge → Stacks → New Stack, paste the contents of [`deploy/dockge-stack.yml`](deploy/dockge-stack.yml).
2. Edit the volume bind paths to match your TrueNAS dataset (default placeholder is `/mnt/tank/tradnex/...`).
3. Place a `.env` file at the path referenced under `env_file` (see `.env.example` for the variable list).
4. Ensure the host data dir is writable by uid 1001 (the container's non-root user):

       mkdir -p /mnt/tank/tradnex/data
       chown -R 1001:1001 /mnt/tank/tradnex/data

5. Click Deploy. To pick up new image versions: Dockge → Stack → Pull → Up.

## CI/CD

- **Pull requests** → [`pr-checks.yml`](.github/workflows/pr-checks.yml) runs ruff, mypy, and pytest. All three must pass before merge.
- **Push to main** → [`build-and-publish.yml`](.github/workflows/build-and-publish.yml) re-runs the same checks, then builds and publishes the image with `latest` and `sha-<short>` tags.
- Cache: GitHub Actions caches Docker layers (`type=gha`); a typical no-deps-changed build takes ~30s, cold builds ~3-4 min.

Both jobs target Python 3.12 (production target). Local dev was verified on 3.14 too.

## Data CLI

Once the venv is set up, the data service has a CLI for sanity checks against
whichever client `DATA_CLIENT` selects (mock or schwab):

    DATABASE_PATH=./data/tradnex.db DATA_CLIENT=mock \
        .venv/bin/python -m services.data.cli quote NVDA

Subcommands: `quote <T>`, `quotes <T1> <T2>...`, `bars <T> --timeframe 1d --limit 50`,
`chain <T> --min-dte 3 --max-dte 14 --type call`, `account`, `movers`, `status`.
Append `--json` to any command for raw JSON output.

## Activating Schwab data

Phase 8a.5 wires Schwab OAuth into the Settings → Credentials page. The
old `scripts/schwab_auth.py` flow still works as an emergency bootstrap
but is no longer the primary path.

### Prerequisites

1. Create a Schwab Developer App at `developer.schwab.com`:
   - Products: Accounts and Trading Production + Market Data Production
   - Callback URL: `https://<your-domain>/api/schwab/oauth/callback`
     (must be HTTPS — Schwab rejects plain HTTP except for explicit
     loopback grants)
   - Order Limit: 120
2. Wait for "Ready For Use" status, then copy Client ID + Client Secret.
3. In `.env`, set `SCHWAB_REDIRECT_URI` to match the callback URL above.
   For local development, run the frontend + API behind Caddy with a
   local TLS cert so the redirect URI is reachable over HTTPS.

### UI flow (recommended)

1. Open `Settings → Credentials → Schwab` — the card initially shows
   "Connect your account."
2. Paste Client ID + Client Secret, save. The card transitions to
   "Ready to connect."
3. Click **Connect Schwab**. The browser redirects to Schwab; log in and
   approve. You'll land back on `/settings/credentials?schwab=connected`
   with the card now showing **Connected** plus token expirations.
4. Flip `DATA_CLIENT=schwab` in `.env`.
5. Restart the data service:

       docker compose restart data

6. Verify the data layer end-to-end:

       .venv/bin/python -m services.data.cli smoke-test

   This walks every analytic tier against SPY / NVDA / AAPL and prints
   PASS/FAIL per check. Add `--calibration` to print expected-range
   comparisons.

7. Confirm via the API:

       curl -b cookies.txt http://localhost/api/system/data-status

   Should return `active_client: "schwab"` with `is_configured: true`
   and non-null `schwab_token_status` expirations.

Access tokens auto-refresh every 25 minutes via the data service's
scheduler. Refresh tokens have a 7-day rolling window: the UI shows a
warning banner under 24 hours remaining, and you can disconnect from the
Credentials page to invalidate the session entirely.

### Fallback: import an existing token file

If you still have a token file from a previous `scripts/schwab_auth.py`
bootstrap and frontend OAuth is unavailable, import it directly:

    .venv/bin/python -m services.api.cli import-schwab-token \
        --file /data/schwab_token.json

After import, the file can be deleted — tokens live encrypted in the DB.

## Analytics

Tier 2 analytics live under `shared/analytics/` and consume the `Bar` schema from
the data layer. Each indicator returns a Pydantic result struct with `latest`,
`series`, and `@computed_field` derived signals; pure functions, Decimal in/out,
no global state. Module layout:

- `momentum.py` — RSI, MACD (with bullish-divergence detection)
- `trend.py` — EMA, SMA, ADX, crossover detection, `above_200_sma`
- `volatility.py` — ATR, Bollinger Bands, GARCH(1,1), Monte Carlo paths
- `levels.py` — Fibonacci retracements/extensions, support/resistance
- `volume.py` — VWAP, volume-vs-average
- `full_analysis.py` — `compute_full_analysis()` aggregator (async; GARCH on a
  worker thread)

Sanity-check from the CLI:

    DATABASE_PATH=./data/tradnex.db DATA_CLIENT=mock \
        .venv/bin/python -m services.data.cli analyze NVDA --timeframe 1d --bars 300

Add `--json` for raw output suitable for piping to `jq`.

## Options analytics (Tier 3)

`shared/analytics/options/` consumes an `OptionsChain` and produces every
options-derived signal the scanner / evaluator / dashboard needs:

- `gex.py` — GEX per-strike and per-expiration (SpotGamma sign convention:
  calls +, puts −), call / put walls, gamma flip, dealer-position regime.
- `iv.py` — IV rank, IV percentile, 25Δ skew, ATM term structure, volatility
  risk premium (VRP = IV − GARCH-realized).
- `pain.py` — Max pain by expiration, P/C OI and volume ratios.
- `flow.py` — ATM-straddle expected move, unusual-activity heuristic
  (volume/OI flagging), net premium flow direction.
- `zero_dte.py` — pin risk, expected move, gamma concentration, key strikes
  for today's expiry. Returns `None` if today isn't an expiration day.
- `greeks_aggregation.py` — second-order Greeks (vanna, charm, vomma, speed)
  via closed-form Black-Scholes; net chain Greeks weighted by OI; portfolio
  Greeks across open positions with concentration warnings.
- `full_options_analysis.py` — `compute_options_analysis(chain, conn, garch)`
  aggregator. Sequential — pure CPU.

CLI demos:

    python -m services.data.cli analyze-options NVDA
    python -m services.data.cli iv-rank NVDA --lookback 252
    python -m services.data.cli gex NVDA
    python -m services.data.cli snapshot-iv NVDA SPY AAPL

`MockDataClient.seed_iv_history()` populates 252 days of synthetic ATM IV into
`daily_iv_snapshots` so `iv_rank` works in dev immediately. Production runs
populate the same table via `services/data/iv_snapshot_task.py` (~15:55 ET
daily for the static universe).

## Tier 4 analytics (Phase 1d)

Closes out the data layer. Five focused modules:

- `shared/analytics/regime.py` — composite categorical state per ticker
  (`trending_bullish` / `breakout_up` / `capitulation` / etc.) with confidence
  in [0, 1]. Combines Tier 2 + Tier 3 into one label that's the headline
  input to Claude's evaluation prompt.
- `shared/analytics/gap.py` — pre-market / overnight gap severity (none /
  minor / moderate / severe / extreme).
- `shared/analytics/correlation.py` — pairwise Pearson on log returns,
  cached in `correlation_snapshots` (migration 0003), refreshed nightly.
- `shared/clients/halt_feed.py` + `mock_halt_feed.py` + `nasdaq_halt_feed.py` —
  abstract `HaltFeed` interface, mock for dev, NASDAQ RSS impl for prod.
- `shared/analytics/options/portfolio_greeks_real.py` — wires Phase 1c's
  pure `portfolio_greeks()` to the open-positions table.

Background scheduler in the data service (`AsyncIOScheduler`) runs three jobs:
IV snapshot at 15:55 ET weekdays, halt monitor every `HALT_POLL_MARKET_SECONDS`
(self-rate-limits off-hours), correlation matrix nightly at 02:00 ET.

CLI extensions:

    python -m services.data.cli regime NVDA
    python -m services.data.cli gap NVDA
    python -m services.data.cli halts
    python -m services.data.cli correlation NVDA AMD
    python -m services.data.cli correlation-matrix
    python -m services.data.cli compute-correlations
    python -m services.data.cli portfolio-greeks

## Watchlist management (Phase 2)

The system separates **universe** (set of allowed tickers) from **watchlist**
(today's targeted subset, with optional per-ticker overrides). Universe lives
in `strategy_configs.settings_json["universe"]` and is the source of truth —
every watchlist ticker must be in the universe.

Daily watchlist auto-carries forward from the most recent prior day if today
hasn't been set yet (`created_by="auto_carry_forward"`). Per-ticker overrides
are NOT carried — they're tactical and reset daily.

CLI:

    python -m services.data.cli universe list
    python -m services.data.cli universe add MSCI
    python -m services.data.cli universe remove NFLX

    python -m services.data.cli watchlist show
    python -m services.data.cli watchlist set NVDA AMD SPY
    python -m services.data.cli watchlist add MSFT
    python -m services.data.cli watchlist remove SPY
    python -m services.data.cli watchlist history --days 7
    python -m services.data.cli watchlist override NVDA \
        --rsi-min 60 --min-dte 3 --set bias=long

The override command takes convenience flags (`--rsi-min`, `--rsi-max`,
`--min-dte`, `--max-dte`, `--notes`) plus repeatable `--set KEY=VALUE` for
arbitrary strategy-rule overrides. Numeric values auto-coerced.

The data service performs a watchlist↔universe drift check at startup and
emits `watchlist_universe_drift` if any active watchlist references a ticker
no longer in the universe.

## Scanner + strategy (Phase 3)

`shared/strategy/` defines the entry decision logic. The headline strategy is
**Long Options Momentum** — three hard rules (must all pass) plus three soft
rules (scored 0/1/2 each, summing to 0–6) that map to a confidence label and
position-sizing multiplier:

| Rule | Source | Threshold |
|------|--------|-----------|
| H1 above-200-SMA on daily | `full_analysis.above_200_sma` | strict |
| H2 EMA9 > EMA21 on 5-min | `ema(bars_5m, 9/21)` | strict |
| H3 MACD bullish divergence on 5-min | `macd(bars_5m).bullish_divergence_at_pullback_low` | strict |
| S1 volume confirmation | `volume_vs_avg(bars_daily, 30)` | base 1.2x, bonus 2.0x |
| S2 RSI rising | `full_analysis.rsi.trend` + `.latest` | base rising, bonus 50–65 sweet spot |
| S3 ADX strength | `full_analysis.adx` | base ADX>20, bonus ADX>25 + +DI>−DI |

Soft score → confidence:

- **5–6** → STRONG (1.0× max premium)
- **3–4** → MODERATE (0.66×)
- **1–2** → WEAK (0.4×)
- **0** → no candidate (insufficient supplemental confirmation)

A fired candidate gets a DTE-bucketed shortlist (3–6 / 7–10 / 11–14 days)
filtered by delta in [0.25, 0.35] and OI×volume ≥ 1000, requiring at least 2
buckets populated for diversity. Empty shortlist → candidate downgraded to
evaluation-only with `fire_decision_reason='shortlist_empty_insufficient_dte_diversity'`.

The `scanner` service runs an `AsyncIOScheduler` cron — every 10 minutes during
09:45–15:00 ET on weekdays, skipping US holidays via
`shared.util.dates.is_trading_day`. Each cycle iterates the active watchlist,
applies per-ticker overrides, and persists every evaluation (fired or not) to
the `scanner_evaluations` table for observability. Fired candidates also
append to the `candidates` table (extended in migration 0005 with new
`*_json` columns + `candidate_kind` for Phase 3.5).

CLI:

    python -m services.scanner.cli scan-now
    python -m services.scanner.cli scan-ticker NVDA
    python -m services.scanner.cli evaluations --hours 24
    python -m services.scanner.cli evaluations --ticker NVDA --hours 24
    python -m services.scanner.cli candidates --status pending
    python -m services.scanner.cli candidate <id>

Per-ticker overrides flow through the existing watchlist override CLI; e.g.

    python -m services.data.cli watchlist override NVDA --set volume_mult_min=1.5

makes S1 require 1.5× average volume (instead of 1.2×) for NVDA today only.
The override appears in `RuleResult.details.base_threshold` of the trace.

## Exit engine (Phase 3.5)

`shared/strategy/exit_signals/` is a 15-signal observation layer that watches
each open position and reports state. Signals are pure functions: position +
market state in, `ExitSignal` out (with category, severity, triggered flag,
description, details). They never decide — they describe.

Categories and severities:

| Category | Signals |
|----------|---------|
| pnl | take_profit, stop_loss, trailing_stop |
| greek | delta_too_high, delta_too_low, theta_acceleration, vega_exposure, charm_acceleration |
| volatility | iv_crush, iv_spike |
| time | dte_critical, friday_short_dte |
| underlying | underlying_halted, adverse_gap |
| setup_invalidated | setup_invalidated (re-evaluates the 6 entry rules) |

Severity ladder: `INFO < WARNING < URGENT < AUTO_CLOSE`. The
`evaluate_position_for_exit()` aggregator runs all signals into one
`ExitSignalTrace` and computes routing flags:

- **AUTO_CLOSE triggered** (P&L > +50% or < −40%) → exit candidate emitted
  with `is_auto_close=True`. Bypasses Claude evaluation but still requires
  human approval.
- **`needs_claude=True`** (any URGENT or WARNING fired, no AUTO_CLOSE) → exit
  candidate emitted with `needs_claude=True`. Routes through Claude in
  Phase 4.
- **No alerts** → only the per-cycle `monitor_evaluations` row is written;
  no candidate, no Claude.

The `monitor` service runs an `AsyncIOScheduler` cron — every 5 minutes
during 09:30–15:55 ET on weekdays. It's the architectural mirror of the
scanner. `services/tripwire/` was retired in this phase; the 5-min monitor
cadence subsumes the tripwire concept.

Position lifecycle audit lives in `position_lifecycle_events` (event_type
∈ opened / monitor_evaluated / signal_fired / auto_close_triggered /
exit_candidate_created / claude_evaluated / human_approved/rejected /
closing / closed / close_failed). Append-only; never updated. Note:
`positions.status` stays simple (`'open'` | `'closed'`) — intermediate
state lives only in lifecycle events.

CLI:

    python -m services.monitor.cli monitor-now
    python -m services.monitor.cli evaluate-position <id>
    python -m services.monitor.cli evaluations [--position <id>] [--hours H]
    python -m services.monitor.cli lifecycle <id>
    python -m services.monitor.cli open-positions
    python -m services.monitor.cli exit-candidates [--status pending]

Configurable thresholds live in `shared/strategy/exit_settings.py`
(`auto_close_profit_pct`, `tp_zone_pct`, `delta_take_profit`,
`iv_crush_critical_pct`, `monitor_window_start_et`, `monitor_enabled`,
etc.). Phase 7 will load them from `strategy_configs.settings_json`.

## Orchestrator + hard vetoes (Phase 4)

`services/orchestrator/` is the routing layer between detection (scanner /
monitor) and decision (Phase 5 Claude). It picks up candidates in
`pending` status, runs hard vetoes, persists the trace, and transitions
them to `pending_llm_evaluation`, `pending_human_approval` (exit
auto-close), or `vetoed`.

**Asymmetric veto sets**: 10 entry vetoes (V1–V10), 2 exit vetoes
(V_E1–V_E2). Exit set is light because events block new exposure, not
closing existing exposure.

| | Entry vetoes | Exit vetoes |
|--|--|--|
| V1 | strategy_paused (config flag) | |
| V2 | outside_market_window (09:45–15:00 ET) | |
| V3 | weekly_trade_cap (default 10) | |
| V4 | weekly_loss_circuit_breaker (default −3% of notional) | |
| V5 | concurrent_positions_cap (default 5) | |
| V6 | earnings_blackout (−7 days … +1 day) | |
| V7 | macro_event_window (24h around FOMC/CPI/NFP) | |
| V8 | active_halt (HaltFeed) | |
| V9 | vix_spike (deferred — config-flag-disabled in v1) | |
| V10 | duplicate_candidate (30-min window) | |
| V_E1 | | outside_close_window (after 15:55 ET) |
| V_E2 | | duplicate_exit (5-min window per position) |

Vetoes are pure async functions: `(candidate, ctx) -> VetoResult`. A
buggy veto raising an exception is caught by the runner and converted
into a `failed=False` result with the error in details — never crashes
the orchestrator.

**Triggering**: scanner / monitor call `asyncio.create_task(...)` after
persisting a candidate, so the orchestrator runs immediately. A backup
poller every 5 min catches stragglers stuck in `pending` (e.g. if the
inline trigger errored).

**Calendar**: a nightly job at 06:00 ET pulls the next 14 days of
economic + earnings events from Finnhub (or `MockCalendarClient` when no
`FINNHUB_API_KEY`) into the `calendar_cache` table. Vetoes V6 and V7
read from the cache — they don't hit the network on the hot path.

CLI:

    python -m services.orchestrator.cli process <candidate_id>
    python -m services.orchestrator.cli process-pending
    python -m services.orchestrator.cli vetoes <candidate_id>
    python -m services.orchestrator.cli calendar [--days 14]
    python -m services.orchestrator.cli refresh-calendar

The `candidates.status` CHECK was widened in migration 0007 to admit the
new orchestrator states (`processing_vetoes`, `pending_llm_evaluation`,
`rejected_by_llm`, `rejected_by_user`); the recreation runs inside
`PRAGMA foreign_keys = OFF` so existing FK references survive intact.

## Claude evaluator (Phase 5)

The evaluator is the LLM judgment layer between the orchestrator
(Phase 4) and human approval. Candidates that pass hard vetoes land in
`pending_llm_evaluation` — the evaluator picks them up, pre-fetches Exa
news context, renders a versioned prompt, calls `claude -p` as a
subprocess, validates the JSON response against a stored JSON-Schema,
persists a full evaluation row (`llm_evaluations`), and transitions the
candidate to one of:

| Kind  | Decision                | New status               |
|-------|-------------------------|--------------------------|
| Entry | STRONG / MODERATE / WEAK | `pending_human_approval` |
| Entry | VETO                    | `rejected_by_llm`        |
| Exit  | CLOSE / CLOSE_PARTIAL   | `pending_human_approval` |
| Exit  | HOLD                    | `held`                   |

Routing is fired immediately by the orchestrator
(`asyncio.create_task(safe_evaluator_call(...))`) and a 5-min poller
catches stragglers. Workers race-safely — the queue claims a candidate
via an atomic `UPDATE … WHERE status='pending_llm_evaluation'` checking
`rowcount==1`. Bootstrap on restart resets stranded
`processing_llm_evaluation` rows back to pending and re-enqueues
everything.

**Exa is pre-fetch only** — top 3 articles (last 7 days) are embedded in
the prompt JSON before Claude runs. No live MCP tool access.

**LLM bypass switch** (`StrategySettings.evaluator.llm_enabled = False`)
skips Claude entirely: the scanner pre-picks a contract via
`select_default_contract` and the evaluator runs a rule-based fallback
(`fallback_used=true`). Same end-state for the candidate
(`pending_human_approval` / `held`); no Claude call billed.

**Prompt versioning** is in-DB (`prompt_versions` table, partial UNIQUE
index ensures ≤1 active per template). Migration `0008_seed_prompts.sql`
seeds v1 entry + exit. CLI:

```bash
python -m services.evaluator.cli prompt show entry_evaluation
python -m services.evaluator.cli prompt history entry_evaluation
python -m services.evaluator.cli prompt activate <version_id>
python -m services.evaluator.cli prompt rollback entry_evaluation 1
python -m services.evaluator.cli evaluate <candidate_id>
python -m services.evaluator.cli queue
python -m services.evaluator.cli evaluations --hours 24
python -m services.evaluator.cli health
```

`migrations/0008_evaluator.sql` widens `candidates.status` with
`processing_llm_evaluation` and `held`, adds `selected_contract_json`
column, and creates `prompt_versions` + `llm_evaluations`. Both LLM and
rule-fallback writes go to `selected_contract_json` for the future
executor to read.

## API (Phase 6)

The FastAPI service exposes the full decision pipeline over HTTP +
Server-Sent Events. Single-user auth via `bcrypt` + DB-backed session
cookies (HTTP-only, SameSite=Strict). OpenAPI docs at
`http://localhost:8080/api/docs`.

Auth flow:

```bash
# Seed your user (interactive password prompt)
python -m services.api.cli create-user --email me@example.com

# Run the API
uvicorn services.api.main:app --host 0.0.0.0 --port 8080

# Login (sets tradnex_session cookie)
curl -c cookies.txt -X POST http://localhost:8080/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"email":"me@example.com","password":"..."}'

# Use the cookie on subsequent requests
curl -b cookies.txt http://localhost:8080/api/dashboard/summary
```

Endpoint groups:

- `/api/auth/*` — login / logout / me
- `/api/candidates` — list, get, full-context, approve, reject
- `/api/positions` — list, get, lifecycle
- `/api/evaluations/{scanner,monitor,llm}` — read-side history
- `/api/watchlist` — get/set today, history
- `/api/universe` — list/add/remove
- `/api/settings` — read/patch the active strategy_configs.settings_json
- `/api/system/status` + `/api/system/toggle` — system on/off switches
- `/api/prompts` — Phase 5 prompt versioning surfaced over HTTP
- `/api/dashboard/{summary,morning-view,active-trades,journal}` — aggregating endpoints
- `/api/events/stream` — SSE feed of every event row

Login attempts are rate-limited via the `login_attempts` table —
`LOGIN_LOCKOUT_THRESHOLD` failures inside `LOGIN_LOCKOUT_WINDOW_SECONDS`
locks the account for `LOGIN_LOCKOUT_DURATION_SECONDS` (defaults: 5 in
15 min → 1-hour lockout). Successful logins don't clear the audit
trail; they just stop adding new failure rows.

System toggles (`paused`, `monitor_paused`, `llm_enabled`) live in
`strategy_configs.settings_json`. The V1 strategy_paused veto, the
evaluator's LLM bypass, and the monitor cycle's runtime check all read
the same row — flipping a toggle via `/api/system/toggle` propagates on
the next scanner / evaluator / monitor tick.

`/api/events/stream` polls the `events` table every
`SSE_POLL_INTERVAL_SECONDS` (default 1.0s) and emits new rows as SSE
messages. Pass `?since_id=<int>` or set `Last-Event-ID` to replay on
reconnect. Phase 8/9 can swap the polling tail for an in-process
pub/sub bus if event volume grows.

## Frontend (Phase 7)

Next.js 15 (App Router) + TypeScript + shadcn/ui + Tailwind. Mobile-first,
dark mode, served by a Caddy reverse proxy alongside the API. SSE-driven
live updates: every event invalidates the relevant TanStack Query keys.

```
   ┌─────────────┐         ┌──────────┐
   │  Caddy :80  │  ──/api──> tradnex_api (uvicorn :8080)
   │             │  ──else──> tradnex_frontend (next :3000)
   └─────────────┘
```

### Dev flows

Two flows, both supported. Use whichever feels right.

```bash
# A — full stack containerized (frontend with HMR via bind-mount)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
# → http://localhost

# B — frontend on host, backend in docker (faster inner-loop iteration)
docker compose -f docker-compose.yml \
               -f docker-compose.dev.yml \
               -f docker-compose.dev-host.yml \
               up -d data scanner orchestrator monitor evaluator api
cd frontend
NEXT_PUBLIC_API_BASE=http://localhost:8080 npm run dev
# → http://localhost:3000
```

### Production

```bash
# Pulls ghcr.io/melcore1/tradnex-v2 (backend) and
#       ghcr.io/melcore1/tradnex-v2-frontend (frontend)
docker compose up -d
# → http://<host>/  (Caddy fronts both)
```

### Routes

`/` dashboard · `/login` · `/approvals` · `/trades` · `/watchlist` ·
`/journal` · `/settings/{system,strategy,prompts,universe}`. Auth-gated
by Next.js `middleware.ts`; `/login` is the only public route. The
"Copy Full Context" button on each candidate hits
`/api/candidates/{id}/full-context` — paste-ready markdown for
Claude.ai.

### Backend additions in Phase 7

Two additive endpoints to support UI features:

- `GET /api/candidates/{id}/full-context` — returns just `{copyable_text}`
- `GET /api/system/status` — extended with `trading_mode`
  (`"paper"` until Phase 8) and `override_reasons` (e.g.
  *"Monitor forced active — 2 open positions"*).

No schema migrations.

See [`frontend/README.md`](frontend/README.md) for layout, scripts,
testing philosophy, and the SSE→TanStack Query bridge.

## Credentials (Phase 8a)

Provider keys (Finnhub, Exa, Alpaca paper/live, Schwab OAuth tokens) live
in the encrypted `credentials` table — not in `.env`. The frontend's
`/settings/credentials` page is the source of truth: keys are
write-only over the wire, encrypted at rest with Fernet, and never
echoed back.

The only env-resident credential is the **master key**:

```bash
# One-time: generate the master Fernet key
python -m services.api.cli generate-encryption-key
# → ENCRYPTION_KEY=<base64>
# Add that line to .env, then restart the stack.
```

Rotating `ENCRYPTION_KEY` invalidates every existing credentials row.
Back it up alongside the `.env` file.

### Auto-migration from env

Existing installs with `FINNHUB_API_KEY` / `EXA_API_KEY` set in `.env`
get auto-migrated on first startup with `ENCRYPTION_KEY` configured —
the API lifespan reads the env values, encrypts them, inserts into the
`credentials` table, and emits an `env_credential_migrated` event per
key. Subsequent restarts skip migration when DB rows already exist; env
values are ignored from then on.

After migration, leave the `FINNHUB_API_KEY` / `EXA_API_KEY` lines in
`.env` blank and rotate the keys via the UI.

### Endpoints (auth required)

- `GET /api/credentials` — list metadata for all configured types
- `GET /api/credentials/{type}` — single record (404 when not configured)
- `PUT /api/credentials/{type}` — upsert; body `{secrets: {...}, notes?}`
- `DELETE /api/credentials/{type}`

Valid types: `alpaca_paper`, `alpaca_live`, `schwab_client`,
`schwab_oauth`, `finnhub`, `exa`, `mcp_api_key`. Alpaca paper/live are
scaffolding in 8a (broker integration lands in 8b).

## MCP server (Phase 8.7)

The `services/mcp/` package is a remote MCP server that exposes the
TradNex analytics layer as tools consumable by Claude.ai (or any other
MCP client). Replaces the legacy Scout server at
`scoutv2.meltradingmcp.uk` with Schwab-backed data instead of the
Alpaca-backed predecessor.

### Tools

| Tool | Purpose |
|---|---|
| `quick_check(ticker)` | Lightweight per-ticker snapshot — price, RSI, ATR, support/resistance. Accepts a list (parallel, max 10). |
| `scout(ticker, days_history=60)` | Full Tier 2 + Tier 3 + regime analysis. List input parallel. |
| `market_overview(market_type='stocks')` | Top gainers / losers / most active. |
| `regime_check(ticker)` | Categorical market regime classification. |
| `correlation_check(ticker_a, ticker_b)` | Pairwise correlation from cached overnight matrix. |
| `position_check()` | Open positions with current monitor evaluation. Sensitive — auth-gated. |
| `calendar_check(days_ahead=14, ticker=None)` | Upcoming economic / earnings events. |

### Setup

1. **Generate an API key** (one time):
   ```bash
   docker exec -it tradnex_mcp python -m services.mcp.cli generate-api-key
   ```
   The key is printed once — save it immediately to a password manager.

2. **Configure Claude.ai** (Web UI Custom Connector beta):
   - URL: `https://scoutv2.meltradingmcp.uk/mcp`
   - Advanced settings → **OAuth Client ID**: anything (e.g. `claude-ai`)
   - Advanced settings → **OAuth Client Secret**: the `tnx_…` API key from step 1

   Claude.ai performs an OAuth 2.1 `client_credentials` grant against
   `/oauth/token`, receives a short-lived JWT, then sends that JWT as
   `Authorization: Bearer …` for every `/mcp` request. The MCP server
   accepts both the raw API key (for `curl` testing) and the OAuth-issued
   JWT.

3. **Verify** end-to-end: from a Claude.ai chat, call
   `quick_check SPY` and confirm it returns Schwab-backed data.

### Key management

```bash
# List status (no secret leakage)
docker exec -it tradnex_mcp python -m services.mcp.cli show-status

# Rotate (generates a new key, invalidates the old one)
docker exec -it tradnex_mcp python -m services.mcp.cli rotate-api-key

# Revoke (deletes the credential — server returns 401 to all callers)
docker exec -it tradnex_mcp python -m services.mcp.cli revoke-api-key

# Smoke-test the running container
docker exec -it tradnex_mcp python -m services.mcp.cli test-connection
```

### Deployment

The `mcp` service is in the repo's `docker-compose.yml` and runs on
port `8090` internally. To expose it to Claude.ai through Cloudflare
Tunnel:

1. In the Dockge stack at
   `/mnt/.ix-apps/app_mounts/dockge/stacks/tradnex-v2/compose.yaml`,
   add the `mcp` service block + attach to the
   `cloudflared-infra_default` external network (same pattern as the
   `caddy` service).
2. In the Cloudflare zero-trust dashboard, update the
   `scoutv2.meltradingmcp.uk` public hostname on the `truenas-infra`
   tunnel to point to `http://tradnex_mcp:8090`.
3. Pull + restart the stack on Dockge.

## Phase status

- **Phase 0 — foundation + CI**: complete
- **Phase 1a — data interfaces, mock, Schwab client**: complete (Schwab dormant until API approval)
- **Phase 1b — Tier 2 analytics**: complete
- **Phase 1c — Tier 3 options analytics**: complete
- **Phase 1d — Tier 4 (regime, gap, halt, correlation, portfolio Greeks)**: complete
- **Phase 2 — watchlist + DB infrastructure**: complete
- **Phase 3 — scanner + 6-rule long options momentum strategy**: complete
- **Phase 3.5 — exit engine + monitor + position lifecycle**: complete
- **Phase 4 — orchestrator + hard vetoes + calendar service**: complete
- **Phase 5 — Claude evaluator (with Exa news + prompt versioning)**: complete
- **Phase 6 — FastAPI service (auth + REST + SSE)**: complete
- **Phase 7 — Next.js dashboard + Caddy reverse proxy**: complete
- **Phase 8a — encryption + credentials store**: complete
- **Phase 8a.5 — Schwab OAuth activation**: complete
- **Phase 8.7 — TradNex MCP server (replaces Scout)**: complete
- Phase 8b — broker abstraction + Alpaca paper execution: not started
- Phase 8c — V_LIVE vetoes + live trading mode: not started
