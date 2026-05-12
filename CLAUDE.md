# CLAUDE.md — TradNex 2 working notes

This file is loaded into context at the start of every Claude Code
session on this repo. Keep it short, current, and specific. When
something here is wrong, fix it. When something here is missing that
should be captured, add it.

The complete user-facing reference is in [README.md](README.md). This
file is for the *working developer / agent* — gotchas, conventions, and
the operating manual.

---

## Goal

**Build a single-user, autonomous paper-options-trading research
system** that runs end-to-end on a home server, with a phone-friendly
web UI for the daily workflow (morning watchlist, midday approvals,
EOD journal). The system scans, evaluates with Claude, asks the human
for a yes/no on each trade, and (eventually, Phase 8b) places the order
with a broker.

**Not the goal**:
- Multi-tenant SaaS — single user only
- Microsecond latency — minute-scale loop is fine
- Beating the market on alpha — disciplined execution + clear rationale
  is what we're testing
- Live trading until paper has worked for weeks (Phase 8c gates live
  behind explicit confirmation + V_LIVE vetoes + red banner UI)

---

## Architecture at a glance

```
                         ┌─ Caddy :80 ─┐
                         │ /api/* → api│
                         │  else → ui  │
                         └──────────────┘
              ┌────────────────┴────────────────┐
              ▼                                 ▼
       tradnex_api (FastAPI)            tradnex_frontend (Next.js 15)

         ▲                          ▲
         │ SQLite (WAL)             │ SSE → TanStack Query invalidation
         │                          │
   ┌─────┴──────────────────────────┴────────────────┐
   │  data · scanner · orchestrator · evaluator       │
   │  · monitor  (all share the same SQLite DB)       │
   └──────────────────────────────────────────────────┘
```

- **SQLite + WAL**, one file (`/data/tradnex.db`) shared by every
  service. `check_same_thread=False` because FastAPI sync deps run in
  the threadpool.
- **The DB is the queue**. Status columns (`candidates.status`,
  `positions.status`) are the source of truth. In-memory deques are
  losable; bootstraps rehydrate from the DB.
- **Atomic claim pattern** for race-prone transitions:
  `UPDATE … WHERE status = 'pending_X'` + check `rowcount == 1`.
  Used by orchestrator, evaluator, and (soon) execution.
- **Events table** is append-only, polled by `/api/events/stream` and
  emitted via `shared.events.emit(service, level, event_type, payload)`.

---

## Phase history (chronological)

| Phase | Title | Commit | What it added |
|------:|-------|--------|---------------|
| 0  | Foundation + CI | `209d19b` | Repo skeleton, Dockerfile.python, GHCR publish |
| 1a/b | Data + Tier 2 analytics | `4f15241` | MarketDataClient ABC, Mock + Schwab, daily/regime metrics |
| 1c | Tier 3 options analytics | `6a91525` | Black-Scholes Greeks, IV surface, options chain shaping |
| 1d | Tier 4 analytics | `9207b33` | Gap detection, halt feed, correlation matrix, portfolio Greeks |
| 2  | Watchlist + DB infra | `c5d0db8` | strategy_configs, watchlists, universe |
| 3  | Scanner + strategy | `5a20450` | 6-rule long_options_momentum strategy, candidates table |
| 3.5 | Exit engine | `13d4391` | Exit signals, monitor cycle, position_lifecycle_events |
| 4  | Orchestrator + vetoes | `fe24e87` | V1–V10 hard vetoes, CalendarService, Finnhub client |
| 5  | Claude evaluator | `2d806bf` | ClaudeCliClient subprocess, Exa pre-fetch, prompt versioning |
| 6  | FastAPI service | `606102b` | 11 routers, session auth, SSE, runtime toggles |
| 7  | Next.js frontend | `35ab641` + `5c9184e` | App Router UI, Caddy proxy, mobile-first, vitest |
| 8a | Encryption + credentials | `e7bda5a` | Fernet store, env→DB migration, /settings/credentials UI |
| 8a.5 | Schwab OAuth activation | `108e14e` | In-app OAuth (auth-start/callback/refresh/disconnect), 25-min auto-refresh task, schwab_client/schwab_oauth credential split, tokens_provider in SchwabDataClient, `/api/system/data-status`, `import-schwab-token` + `smoke-test` CLIs, interactive 4-state Schwab card |
| 8.7 | TradNex MCP server | *pending* | Replaces Scout at `scout.meltradingmcp.uk`. New `services/mcp/` Streamable-HTTP MCP server wrapping `shared/analytics/`; 7 tools (`quick_check`, `scout`, `market_overview`, `regime_check`, `correlation_check`, `position_check`, `calendar_check`); Bearer-token auth via new `mcp_api_key` credential; `services.mcp.cli` for key generate/rotate/revoke/test |
| 8b | *not started* | — | Broker abstraction, Alpaca paper, execution service, fill poller |
| 8c | *not started* | — | V_LIVE vetoes, live mode UI (Schwab OAuth already shipped in 8a.5) |

Current totals after 8.7: **~705 backend tests, 36 frontend tests**.

---

## Workflow conventions

### Planning a new phase

We work phase-by-phase. The pattern that works:

1. **Spec arrives** — usually a long markdown block from the user with
   architecture decisions, file layouts, and test targets.
2. **Ask clarifying questions** via `AskUserQuestion` for the 2–4
   highest-impact ambiguities. Don't ask about things the spec
   already pins down. Don't ask about plan approval.
3. **Briefly explore** the relevant existing code (3 reads max, or one
   `Explore` agent) to validate spec assumptions against reality.
4. **Propose a scoped plan in chat** — *what's in, what's out, what's
   risky*. The user either approves or trims.
5. **Build, test, ship** in one focused arc.

Plan mode (`ExitPlanMode`) is reserved for genuinely large work
where the user wants to review the whole shape before code starts.
Phase 7 used it; Phase 8a didn't and was fine.

### Splitting large phases

If a phase touches >5 service directories or adds >50 tests, propose
sub-phases (e.g. 8a / 8b / 8c). Smaller PRs = smaller blast radius.
Confirmed via Phase 8 split — encryption shipped on its own without
broker code, broker code can ship without live-trading UI.

### Commit / push protocol

- **One commit per phase** (or per sub-phase). Multi-paragraph commit
  body explaining: what was added, what was deferred, what tests cover
  it, and one line confirming end-to-end verification.
- Push to `main`. CI runs `build-and-publish.yml`:
  - `test` job: ruff + mypy + pytest
  - `build` job: backend image → GHCR
  - `build-frontend` job: lint + typecheck + vitest + next build → GHCR
- Tags: `:latest` and `:sha-<short>` on each successful main push.

### Verification before commit

Run **all four** before considering a phase ready:

```bash
# Backend
.venv/bin/python -m pytest tests/ -q          # all tests pass
.venv/bin/ruff check .                        # no lint
.venv/bin/mypy shared/ services/api/ services/evaluator/ \
              services/scanner/ services/orchestrator/ \
              services/monitor/                # strict on these

# Frontend
cd frontend
npm run lint && npm run typecheck && npm run test && npm run build
```

Plus an **end-to-end smoke**: boot uvicorn locally, exercise the new
endpoints with `curl` + verify DB state. Skip nothing on this step —
the credentials encryption test (Phase 8a) and the SSE redirect bug
(Phase 7 middleware) both showed up only at runtime.

---

## Testing standards

### Backend (`pytest tests/`)

- **Async by default**. `asyncio_mode = "auto"` in `pyproject.toml`.
  Plain `async def test_*(...)` works, no decorator needed.
- **DB-isolated per test**. Use `tests/_api_helpers.py`'s
  `reset_modules_for_test_db(tmp_path, monkeypatch)` which:
  1. Sets `DATABASE_PATH` to a tmp file
  2. Reloads `shared.config` and `shared.db` to pick up the patch
  3. Runs migrations
  4. Returns a fresh connection
- **API tests** use the shared `client_setup` fixture pattern (see
  `test_api_candidates.py`). Always seed a user + login before
  exercising auth-required endpoints.
- **Credentials tests** must `monkeypatch.setenv("ENCRYPTION_KEY", ...)`
  *before* `reset_modules_for_test_db` so the config reload picks it
  up. Helper: `tests/_credential_helpers.py`.
- **Skip flaky timing assertions**. The earlier
  `test_market_status_returns_consistent_values` was tautological;
  rewrite to check actual ordering, not `a <= b OR b >= a`.

### Frontend (`vitest`)

- **No snapshot tests** — they age badly. Test behavior, not DOM
  structure.
- **Coverage target**: ~30–40% on critical paths (API client, SSE map,
  format helpers, reused components like CopyButton).
- **Mock `@/components/ui/sonner`** in tests that wrap mutations:
  ```ts
  vi.mock('@/components/ui/sonner', () => ({
    toast: { success: vi.fn(), error: vi.fn() },
    Toaster: () => null,
  }))
  ```
- **Don't use fake timers with userEvent** — they conflict and tests
  hang. Test the immediate state change instead of the delayed reset.

### CI gotchas

- `ENCRYPTION_KEY` must be set in CI workflow env, otherwise the new
  encryption-aware tests fail. Use the test key:
  `vJEKnyT7ulyHCYGFY7nBh-XqMhXpwnBJ7-kIPxKj-Rs=` (literal, NOT a secret).
- The `api-types-in-sync` job in `pr-checks.yml` boots the API to
  regenerate types — also needs `ENCRYPTION_KEY` and `DATABASE_PATH`.

---

## Deployment

### Local dev

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
# → http://localhost (Caddy fronts api + frontend)
```

Frontend bind-mounts `src/`; HMR via `WATCHPACK_POLLING=true`. Named
volumes for `node_modules` and `.next` avoid Linux ownership tangles.

Alternative inner loop (faster HMR, no Docker for the frontend):

```bash
docker compose -f docker-compose.yml \
               -f docker-compose.dev.yml \
               -f docker-compose.dev-host.yml \
               up -d data scanner orchestrator monitor evaluator api
cd frontend
NEXT_PUBLIC_API_BASE=http://localhost:8080 npm run dev
```

### First-run setup

```bash
# Generate the master encryption key (one time)
python -m services.api.cli generate-encryption-key
# → ENCRYPTION_KEY=<base64>
# Paste into .env

# Seed a user
python -m services.api.cli create-user --email me@example.com
# → prompts for password

# Add provider keys via the UI:
#   /settings/credentials → Finnhub, Exa, Alpaca paper (when 8b lands)
```

### Production (Dockge / docker compose)

```bash
docker compose up -d                # pulls :latest from GHCR
```

Images:
- `ghcr.io/melcore1/tradnex-v2:sha-<short>` (backend)
- `ghcr.io/melcore1/tradnex-v2-frontend:sha-<short>` (frontend)

Both are public. CI builds `linux/amd64`. Pin to a SHA tag for
deploys you care about, use `:latest` for "always recent."

---

## Standard procedures

### Adding a new API endpoint

1. Pydantic schemas in `services/api/schemas/__init__.py`
2. Router file in `services/api/routers/<resource>.py`
3. Register in `services/api/main.py`
4. Tests in `tests/test_api_<resource>.py` using `client_setup`
5. Regenerate frontend types: with API running locally,
   `cd frontend && npm run generate:api`
6. Per-resource client in `frontend/src/lib/api/<resource>.ts`
7. Hook in `frontend/src/hooks/use<Resource>.ts`
8. Page or component that consumes the hook

### Adding a new credential type

1. Edit the CHECK constraint in `migrations/0010_credentials.sql`
2. Update `VALID_CREDENTIAL_TYPES` in `shared/services/credentials.py`
3. Update `CredentialType` literal in same file
4. Update `CredentialTypeLiteral` in `services/api/schemas/__init__.py`
5. Add a `CredentialEditor` card in
   `frontend/src/app/settings/credentials/page.tsx`
6. Test in `tests/test_credentials_service.py`

### Adding a new migration

- File name: `00NN_<topic>.sql`. Migrations run in lexical order via
  `shared.db.run_migrations()`. They're idempotent (`IF NOT EXISTS`).
- When changing a table's CHECK constraint, SQLite requires recreating
  the table. Pattern in `0008_evaluator.sql` is:
  ```sql
  PRAGMA foreign_keys = OFF;
  CREATE TABLE candidates_new (...);
  INSERT INTO candidates_new SELECT *, NULL FROM candidates;
  DROP TABLE candidates;
  ALTER TABLE candidates_new RENAME TO candidates;
  -- recreate indexes
  PRAGMA foreign_keys = ON;
  ```

### Adding a runtime toggle

Use `strategy_configs.settings_json`. Pattern:
- `shared/services/runtime_toggles.py:DEFAULTS` — add the key + default
- `/api/system/toggle` accepts the new `name`
- Service that reads it: `get_toggle(conn, "new_key", default=False)`

Verified to flow through V1 veto, evaluator, and monitor cycle in
Phase 6.

---

## What NOT to do — gotchas we've already hit

These all happened during development. Don't repeat them.

### Backend

- **Don't reuse `<<: *python-base` for services not in the base
  compose**. `docker-compose.dev.yml` references a `tripwire` service
  that doesn't exist in `docker-compose.yml`; the merge creates an
  empty service with no command. Pre-existing; leave alone but don't
  add new dangling refs.
- **Don't forget `check_same_thread=False` on the SQLite connection**.
  FastAPI sync deps run in the threadpool; without this flag,
  `TestClient` raises *"SQLite objects created in a thread can only be
  used in that same thread"*. Fixed in `shared/db.py`.
- **Don't cache `from shared.config import settings` at module level
  in API dep functions**. Test fixtures reload `shared.config` but the
  module-level binding stays stale → 503 errors only when other tests
  run first. Use `from shared import config as _config` *inside* the
  dep function (see `get_encryption` in `services/api/deps.py`).
- **Don't store NULLs in a UNIQUE column you want to dedupe on**.
  SQLite treats every NULL as distinct. Use `''` and convert to None
  on read (see Phase 4's watchlist ticker handling).
- **Don't use Pydantic field names that shadow v1 methods**.
  `schema_json` shadowed the deprecated v1 method and caused warnings;
  renamed to `response_schema` in Phase 5.
- **Don't `git commit --amend` after a pre-commit hook failure**. The
  commit didn't happen — `--amend` modifies the *previous* commit.
  Re-stage and create a new commit.
- **Don't put credentials in `.env`** (except `ENCRYPTION_KEY`).
  Phase 8a's rule. New credential types go into the encrypted DB store.

### Frontend

- **`middleware.ts` MUST live in `src/middleware.ts`** when using the
  `src/` layout. At repo root it silently doesn't run — Next.js builds
  a `middleware-manifest.json` with `"middleware": {}` and you get
  prerendered HTML for routes that should redirect. Phase 7 fixup.
- **`frontend/public/` must exist** even if empty, otherwise
  `Dockerfile.frontend`'s `COPY --from=builder /app/public` fails in
  CI. We ship `public/robots.txt` as a placeholder. Phase 7 fixup.
- **`apiFetch` query type can't use named interfaces directly** —
  TypeScript strict rejects them without index signatures. Either
  cast at call sites (`params as Record<string, unknown>`) or make the
  query param type loose. See `lib/api/client.ts`.
- **Don't pair `userEvent` with `vi.useFakeTimers()`** — they
  deadlock. The CopyButton test that tried `vi.advanceTimersByTime`
  after a click hung for 5s. Test the immediate state, not the timer
  reset.
- **Don't import shadcn components that aren't used** — Next's lint is
  strict (`@typescript-eslint/no-unused-vars`) and the production
  build fails. Trim imports before pushing.
- **Don't rely on `withCredentials` for cross-origin SSE locally**.
  EventSource sends cookies same-origin only. Use the Caddy proxy
  (port 80) or the dev-host override.

### Infra

- **`flush_interval -1` belongs INSIDE `reverse_proxy { }`** in
  Caddyfile, not at the top level. Plus `read_timeout 0` +
  `response_header_timeout 0` for SSE.
- **`output: 'standalone'` in `next.config.ts` is required** for the
  multi-stage Docker runtime to work. Without it the `server.js`
  doesn't exist.
- **Don't expose the API port in production compose**. Caddy is the
  single entry point on `:80`. Keep `8080` internal. The
  `docker-compose.dev-host.yml` override re-exposes it only for the
  host-side `npm run dev` flow.
- **CI workflows need `ENCRYPTION_KEY` after Phase 8a**, even though
  the encryption tests technically gate behind `Encryption` dep.
  Without it, several test fixtures fail. Add it to both
  `build-and-publish.yml` and `pr-checks.yml`.

### Schwab OAuth (Phase 8a.5)

- **Redirect URI must be HTTPS**. Schwab rejects plain-HTTP callbacks
  except for explicit loopback grants. For local dev, terminate TLS via
  Caddy + a local cert; the in-app OAuth flow won't work behind plain
  HTTP on port 80.
- **Refresh tokens roll on a 7-day window**. Every successful refresh
  extends it. If the system is offline >7 days, the refresh window
  lapses and the user must click "Connect Schwab" again from scratch.
  The UI surfaces a warning banner under 24h remaining.
- **OAuth state is a Fernet token, not a session cookie**. There's no
  `request.session` in this app. State carries `{user_id, nonce, exp}`
  encrypted with the master key, and `/callback` verifies user_id matches
  the active session before exchanging the auth code.
- **SchwabDataClient takes `tokens_provider`, not a token file path**.
  The factory builds a closure that reads `schwab_oauth` fresh from DB
  on every API call. The 25-min auto-refresh task in `services/data`
  is the single source of truth for refreshes; schwab-py's reactive
  refresh is wired to a no-op writer.
- **`schwab_client` vs `schwab_oauth`**. Two separate credential rows:
  `schwab_client` holds Client ID/Secret (stable, user-managed via UI),
  `schwab_oauth` holds access+refresh tokens (rotated by the auto-refresh
  task). Disconnect removes `schwab_oauth` only — Client ID/Secret
  persist so reconnecting just needs one more OAuth handshake.

### MCP Server (Phase 8.7)

- **`FastMCP.streamable_http_app()` returns a complete Starlette app**
  with the session manager lifespan and custom `/health` route already
  attached. Don't try to wrap it in another Starlette — the inner
  lifespan won't fire and Claude.ai will see "session not initialized"
  responses. Just use it as the ASGI app directly under uvicorn.
- **`session_manager.run()` is idempotent-disallowed**. Tests that build
  the app twice (e.g. multiple `TestClient(app)` contexts) must reload
  `services.mcp.main` between them, otherwise the second `lifespan` raises
  `RuntimeError: .run() can only be called once per instance.`
- **Endpoint is `/mcp`, not `/sse`**. Spec 2025-03-26 deprecated HTTP+SSE
  in favor of Streamable HTTP. Claude.ai connectors default to `/mcp`. If
  Claude.ai exhibits the current CallToolRequest regression, add an SSE
  fallback as a separate sub-app — but cleanly, not by nesting
  streamable_http_app inside another Starlette.
- **Tools take `client`/`db` as positional injection**, not from FastMCP
  context. The SDK's tool decorator passes only the JSON-RPC params as
  args; we resolve the data client + DB connection inside the wrapper
  using `build_data_client()` + `db_session()`. Keeps the tool functions
  testable without mocking the SDK.
- **Single API key, single user**. The `mcp_api_key` credential is one
  row in `credentials`. Rotation replaces it; revocation deletes it.
  The verifier uses `hmac.compare_digest` for constant-time comparison
  to dodge timing attacks.
- **OAuth 2.1 client_credentials for Claude.ai Web UI**. The Web
  Custom Connector beta only exposes OAuth Client ID/Secret fields —
  no Bearer-token field. So the MCP server runs a minimal auth-server
  at `/oauth/token` accepting `grant_type=client_credentials`, where
  any `client_id` is accepted and `client_secret` must equal the
  stored `mcp_api_key`. On success it mints a JWT (HS256, signed with
  the same `mcp_api_key`) which the verifier validates alongside raw
  API keys. Discovery via `/.well-known/oauth-authorization-server`.
  This is *not* full OAuth — no /authorize, no refresh tokens, no
  user consent — just enough for the Web UI's client_credentials path.
- **No process-wide state across tools**. Every tool opens a fresh
  sqlite3 connection (SQLite WAL handles concurrent readers). Tests use
  `reset_modules_for_test_db` to get a tmp DB per case; production uses
  the same shared `/data/tradnex.db` as every other TradNex service.

### Process

- **Don't enter plan mode for small phases**. Phase 8a was decided in
  chat after 4 clarifying questions and shipped fine. Plan mode pays
  off for sprawling phases (Phase 7) where the user wants to see the
  full file layout before approving.
- **Don't ship without end-to-end smoke**. Twice now we shipped
  something that passed unit tests but failed at runtime (middleware
  location, Dockerfile public/). The smoke takes 2 minutes; do it.
- **Don't auto-migrate / auto-anything without an emit event**.
  Silent migrations are debugging nightmares. Every state change
  emits to the events table; users can see what happened via
  `/api/events/stream` or the dashboard.

---

## Project structure

```
shared/                          shared library code (mypy strict)
  clients/                       broker, market data, calendar, exa, claude CLI
  services/                      auth, credentials, encryption, prompts, watchlist
  strategy/                      rules, vetoes, exit signals, settings
  analytics/                     all tier 1-4 metrics
services/
  data/                          background data ingestion + IV snapshots
  scanner/                       per-watchlist-cycle entry candidate generation
  orchestrator/                  veto application + LLM evaluator triggering
  evaluator/                     Claude prompt rendering + subprocess + persistence
  monitor/                       open-position evaluation + exit signals
  api/                           FastAPI (11 routers, lifespan, middleware)
migrations/                      0001 – 0010 (run on startup)
frontend/                        Next.js 15, see frontend/README.md
infra/                           Caddyfile
tests/                           pytest + asyncio-auto
.github/workflows/               build-and-publish.yml + pr-checks.yml
```

---

## Tech stack

| Layer | Choice | Why |
|------|--------|-----|
| Lang | Python 3.12 / Node 20 | LTS, fast enough |
| DB | SQLite + WAL | One file, no server, single-user fit |
| API | FastAPI + uvicorn | Pydantic v2 typed end-to-end |
| Auth | bcrypt + DB-session cookies | HttpOnly, SameSite=Strict, lockout via `login_attempts` |
| Encryption | `cryptography.fernet` | AES-128-CBC + HMAC, JSON-aware wrapper |
| Frontend | Next.js 15 App Router, TS strict | Server components + SSE-driven hydration |
| State | TanStack Query 5 | SSE invalidates keys, components subscribe to keys |
| Forms | react-hook-form + zod | Client validation; server still validates |
| UI | shadcn/ui + Tailwind 3 | Vendored components, dark mode default |
| Tests | pytest (back) / vitest (front) | Async + happy-dom |
| CI | GHA + GHCR | Same-org tags, public images |
| Deploy | docker compose + Caddy | LAN port 80, no TLS yet |

---

## Working with the user

Single user (the developer). They've shown they want:

- **Long, detailed Phase specs** as input — don't ask them to repeat
  themselves.
- **Clarifying questions only when ambiguity matters** — use
  `AskUserQuestion` for 2–4 high-impact decisions, not nitpicks.
- **A brief in-chat plan + confirm**, then build straight through.
- **Verification before "done"** — they read the test counts and the
  curl outputs in the final summary. Lying about test counts is
  uniquely bad.
- **Mistake-aware** — if we hit a CI failure mid-phase, fix it with a
  follow-up commit (Phase 7 fixup `5c9184e`) rather than rewriting
  history.

---

## Next phases (planned)

**Phase 8b**: Broker abstraction + Alpaca paper + execution service.
Add `Broker` ABC, `AlpacaBroker` (alpaca-py), `MockBroker`. New
`services/execution/` with `place_order`, `fill_poller`, and an
orchestrator → execution trigger. Migration `0011_orders_fills.sql`
with `orders` + `fills` tables and `positions.trading_mode` column.
~10–12 new tests for the broker mock, ~12 for execution.

**Phase 8c**: V_LIVE vetoes (size cap, daily loss circuit breaker,
concurrent positions cap, first-N-trades human review) + live trading
mode UI (red `[LIVE]` banner, type-`APPROVE` modal) + Schwab OAuth.
Live mode requires `live_confirmed=true` in `strategy_configs.settings_json`
plus Alpaca live credentials. Service refuses to start in live mode
without confirmation.

After 8c: the system trades.
