# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## This is a polyglot monorepo

Services are organized by function under `services/` and `connectors/`. Each directory owns its own language toolchain. Do not assume Python — check the service directory for its `pyproject.toml` (Python), `go.mod` (Go), `package.json` (TypeScript), or `Cargo.toml` (Rust).

**Current languages in use:** Python 3.12 (all M1 services).

## Task runner (cross-language)

All common operations use `task` (Taskfile.yml at repo root). Install: `brew install go-task`.

```
task up        # start all infrastructure (Postgres, ClickHouse, Redis)
task down      # stop infrastructure
task test      # run all tests across all services
task lint      # run linters across all services
task build     # build all Docker images
```

## Python services (M1)

Services using Python: `services/ingestor`, `services/pipeline`, `services/api`, `services/worker`, `connectors/langfuse`, `tools/cli`. Each has its own `pyproject.toml`. Use `uv` for dependency management.

```
cd services/pipeline && uv sync          # install deps for one service
uv run pytest ../../tests/unit/pipeline/ # run pipeline unit tests
```

There is no root-level Python virtualenv — each service is isolated.

## Running locally

```
task up
cd services/ingestor && uv run uvicorn sentinel_ingestor.main:app --reload --port 8001
cd services/api     && uv run uvicorn sentinel_api.main:app     --reload --port 8000
cd services/worker  && uv run celery -A sentinel_worker.main worker --loglevel=info
```

## CLI

```
cd tools/cli
uv run sentinel analyze --source langfuse --public-key X --secret-key Y [--project-id Z]
uv run sentinel watch   --source langfuse --public-key X --secret-key Y

  --format json     machine-readable output
  exit 0            no insights found
  exit 1            insights found (CI-safe)
```

## Database

```
# Postgres migrations
cd infra/migrations/postgres && uv run alembic upgrade head
cd infra/migrations/postgres && uv run alembic revision --autogenerate -m "description"

# ClickHouse DDL (applied automatically at worker startup in dev)
# Manual: infra/migrations/clickhouse/001_spans.sql
```

## Tests

```
task test                                                         # all tests
cd tests && uv sync --no-install-project                          # install test deps
cd tests && uv run --no-project pytest unit/                      # unit only (no Docker)
cd tests && uv run --no-project pytest integration/               # requires: task up
cd tests && uv run --no-project pytest -k "test_agent_loop"       # single test by name
cd tests && uv run --no-project pytest unit/rules/ -v             # all rule tests
```

## Adding a service in a new language

1. Create `services/<name>/` with the language's project file (`go.mod`, `package.json`, `Cargo.toml`)
2. Add a `Dockerfile`
3. Add the service to `docker-compose.yml`
4. Add `task build:<name>` and `task test:<name>` to `Taskfile.yml`
5. If the service exchanges `NormalizedSpan` or `Insight`, generate types from `proto/sentinel/v1/`

## Adding a connector

1. Create `connectors/<source>/` with its own `pyproject.toml` (or language tooling of choice)
2. Implement `Connector` ABC from `connectors/_base/src/sentinel_connectors/base.py`
3. Add a fixture trace at `tests/fixtures/<source>_sample.json`
4. Add unit tests at `tests/unit/connectors/test_<source>.py`

## Adding a detector

1. Create `services/pipeline/src/sentinel_pipeline/detectors/<detector_name>.py`
2. Implement the `Detector` ABC (`detectors/base.py`)
3. Register in `detectors/__init__.py` `DETECTOR_REGISTRY` list
4. Write tests: one fixture that triggers the detector, one that must NOT trigger it

## Key shared contracts

```
proto/sentinel/v1/span.proto      NormalizedSpan wire format
proto/sentinel/v1/insight.proto   Insight, Severity, Tier enums
proto/openapi/api.yaml            REST API contract
```

## Environment variables (.env)

```
DATABASE_URL      postgres://sentinel:sentinel@localhost:5432/sentinel
CLICKHOUSE_URL    clickhouse://localhost:9000/sentinel
REDIS_URL         redis://localhost:6379/0
SENTINEL_ENV      development | production
```
