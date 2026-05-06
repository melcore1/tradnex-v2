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

## Activating Schwab data (when API approval lands)

Phase 1a ships the Schwab client fully built; flipping it on once approved is a
config change, not a code change.

1. Add credentials to `.env`:

       SCHWAB_CLIENT_ID=<from developer portal>
       SCHWAB_CLIENT_SECRET=<from developer portal>
       SCHWAB_REDIRECT_URI=https://127.0.0.1:8443

2. Run one-time auth (opens browser, log in to your **brokerage** account):

       .venv/bin/python scripts/schwab_auth.py

3. Flip `DATA_CLIENT=schwab` in `.env`.

4. Restart the data service:

       docker compose restart data

5. Verify:

       .venv/bin/python -m services.data.cli quote NVDA

   Should return a real-time NVDA quote.

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

## Phase status

- **Phase 0 — foundation + CI**: complete
- **Phase 1a — data interfaces, mock, Schwab client**: complete (Schwab dormant until API approval)
- **Phase 1b — Tier 2 analytics**: complete
- **Phase 1c — Tier 3 options analytics**: complete
- **Phase 1d — Tier 4 (regime, gap, halt, correlation, portfolio Greeks)**: complete
- **Phase 2 — watchlist + DB infrastructure**: complete
- Phase 3 — scanner + strategy rules: not started
- Phase 4 — hard vetoes: not started
- Phase 5 — Claude evaluator: not started
- Phase 6 — FastAPI: not started
- Phase 7 — Next.js dashboard: not started
- Phase 8 — paper execution: not started
