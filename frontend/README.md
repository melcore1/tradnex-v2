# TradNex 2 — Frontend (Phase 7)

Next.js 15 (App Router) + TypeScript + shadcn/ui + Tailwind. Dark mode, mobile-first.

## Stack

- **Next.js 15** — App Router, server components by default, `output: 'standalone'` for the Docker image
- **TanStack Query 5** — all server state. SSE invalidates query keys; components subscribe to keys, not raw events
- **shadcn/ui + Tailwind 3** — components vendored under `src/components/ui/`, theme in `src/app/globals.css`
- **react-hook-form + zod** — login form, settings, prompt editor
- **vitest + @testing-library/react** — ~30 critical-path tests (`npm run test`)
- **openapi-typescript** — API types regenerated from the live OpenAPI schema

## Routes

| Route | Page |
|-------|------|
| `/` | Dashboard |
| `/login` | Login (only public route) |
| `/approvals` | Pending human approvals — copy full context, approve, reject |
| `/trades` | Active trades + lifecycle timelines |
| `/watchlist` | Today's watchlist + 7-day calendar |
| `/journal` | EOD review by date |
| `/settings/system` | Toggles + queue stats + trading mode |
| `/settings/strategy` | JSON editor for `strategy_configs.settings_json` |
| `/settings/prompts` | Prompt versioning (entry / exit) — create, activate, rollback |
| `/settings/universe` | Add / remove universe tickers |

`middleware.ts` redirects unauthenticated requests to `/login` (SSR `/api/auth/me` round-trip).

## Dev flows

Both flows are supported. Pick whichever feels right.

### A) Containerized (full stack via docker-compose)

```bash
# from repo root
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
# → http://localhost  (Caddy fronts api + frontend)
```

The frontend container bind-mounts `frontend/src` and runs `npm run dev` inside. HMR works. `node_modules` and `.next` live in named volumes to avoid Linux fs ownership tangles.

### B) Host-side `npm run dev` against a containerized API

```bash
# Terminal 1 — backend stack only (Caddy not needed)
docker compose -f docker-compose.yml \
               -f docker-compose.dev.yml \
               -f docker-compose.dev-host.yml \
               up -d data scanner orchestrator monitor evaluator api

# Terminal 2 — frontend on host
cd frontend
NEXT_PUBLIC_API_BASE=http://localhost:8080 npm run dev
# → http://localhost:3000
```

The `dev-host` override re-exposes the API port so the host-side frontend can reach it directly.

## Scripts

```bash
npm run dev         # Next dev server
npm run build       # Production build (output: standalone)
npm run start       # Run the standalone build locally
npm run lint        # next lint
npm run typecheck   # tsc --noEmit
npm run test        # vitest --run
npm run test:watch
npm run generate:api  # regenerates src/types/api.generated.ts from a running API
```

## Type generation

Backend type changes propagate to the frontend via `openapi-typescript`:

```bash
# In another terminal: start the API
cd ..
.venv/bin/uvicorn services.api.main:app --port 8080

# Then regenerate
cd frontend
npm run generate:api
git diff src/types/api.generated.ts   # commit the regenerated types
```

CI fails on drift (PR check `api-types-in-sync`).

## SSE → query invalidation

`src/lib/sse/SseProvider.tsx` opens an `EventSource` to `/api/events/stream` and translates each event into a TanStack Query cache invalidation according to `src/lib/sse/event-map.ts`.

To add a new event: emit it from a backend service, then map it to the relevant query keys in `event-map.ts`. No component-level changes needed.

## Project layout

```
src/
├── app/             # App Router pages
├── components/
│   ├── ui/          # shadcn primitives (vendored)
│   ├── shared/      # CopyButton, RawJsonToggle, badges, etc.
│   ├── candidate/   # ApprovalCard, RuleTraceDisplay, etc.
│   ├── position/    # PositionCard, LifecycleTimeline
│   ├── system/      # SystemStatusPanel
│   └── layout/      # Header, Sidebar, MobileNav
├── lib/
│   ├── api/         # fetch wrapper + per-resource modules
│   ├── sse/         # EventSource provider + invalidation map
│   ├── format/      # decimal/datetime/status helpers
│   └── utils.ts     # cn()
├── hooks/           # TanStack Query wrappers
├── types/
│   └── api.generated.ts  # generated, do not edit
└── __tests__/       # vitest suites
```

## Testing philosophy

We do not target 100% coverage. The aim is to test the things that would make the trading workflow embarrassing if they broke:

- **API client** — credentials, error handling, JSON parsing
- **SSE → invalidation map** — known events resolve to known keys
- **Format helpers** — money/percent formatting (financial UIs are unforgiving)
- **System display logic** — paused → enabled negation, override propagation
- **CopyButton + RawJsonToggle** — the two components used on every detail panel

Component snapshot tests are intentionally avoided; they age badly.

## Mobile-first

Every screen is tested at 375px width. Bottom-nav (mobile) + sidebar (desktop). Touch targets ≥ 44px (`tap-target` utility class).
