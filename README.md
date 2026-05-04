# TradNex 2

Personal autonomous paper-options-trading research system.
A scanner generates candidates, an LLM evaluator filters them with calendar + news context, and a human approves before any paper order is placed.

## Run locally

Two paths — Docker (with the dev override) or a Python venv. The venv path is what Phase 0 verification used and works without any container runtime.

### Docker (with the dev override)

    cp .env.example .env
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

The override builds the image as `tradnex:dev`, bind-mounts your source tree (so edits reflect without rebuild), and runs the container as your host uid (default 1000) to avoid bind-mount permission issues. If your host uid differs, set `TRADNEX_UID` / `TRADNEX_GID` in `.env`.

Without the override, `docker compose up` pulls `ghcr.io/melcore1/tradnex2:latest` from GHCR — the same path Dockge uses in production.

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

- Image: `ghcr.io/melcore1/tradnex2`
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

## Phase status

- **Phase 0 — foundation + CI**: complete
- Phase 1 — Schwab data layer: not started
- Phase 2 — analytics: not started
- Phase 3 — scanner + strategy rules: not started
- Phase 4 — hard vetoes: not started
- Phase 5 — Claude evaluator: not started
- Phase 6 — FastAPI: not started
- Phase 7 — Next.js dashboard: not started
- Phase 8 — paper execution: not started
