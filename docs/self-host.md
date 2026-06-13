# Self-Hosting SentinelRCA

Run the full Sentinel stack on your own infrastructure. All data stays in your network — traces are never sent to any external service.

## Requirements

| Tool | Version | Install |
|---|---|---|
| Docker + Docker Compose | 24+ | [docs.docker.com](https://docs.docker.com/get-docker/) |
| go-task | any | `brew install go-task` |
| Python | 3.12+ | [python.org](https://www.python.org) |
| uv | any | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | 20+ | [nodejs.org](https://nodejs.org) |

---

## Quick start (development)

The fastest path — starts everything locally with hot-reload.

### 1. Clone and configure

```bash
git clone https://github.com/sentinelrca/sentinel
cd sentinel/code
cp .env.example .env   # if it doesn't exist, copy the block below
```

Minimum `.env` for a working local stack:

```env
DATABASE_URL=postgres://sentinel:sentinel@localhost:5432/sentinel
CLICKHOUSE_URL=clickhouse://localhost:9000/sentinel
REDIS_URL=redis://localhost:6379/0
SENTINEL_ENV=development

# Generate with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SENTINEL_SECRET_KEY=<your-fernet-key>

# Generate with: openssl rand -hex 32
SENTINEL_ADMIN_KEY=<your-admin-key>

# Your workspace API key — create one after startup (step 3)
SENTINEL_API_KEY=<leave-blank-for-now>
```

### 2. Start infrastructure

```bash
task up   # starts Postgres, ClickHouse, Redis in Docker
```

Wait until all three are healthy (takes ~10 seconds):

```bash
docker compose ps
# postgres    Up (healthy)
# clickhouse  Up (healthy)
# redis       Up (healthy)
```

### 3. Run database migrations

```bash
cd infra/migrations/postgres
DATABASE_URL=postgres://sentinel:sentinel@localhost:5432/sentinel \
uv run --no-project alembic upgrade head
cd ../../
```

### 4. Start the API

```bash
cd services/api
uv sync
uv run uvicorn sentinel_api.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify: `curl http://localhost:8000/health` → `{"status":"ok"}`

### 5. Start the worker

In a new terminal:

```bash
cd services/worker
uv sync
uv run celery -A sentinel_worker.main worker --loglevel=info
```

### 6. Create your first workspace

```bash
curl -X POST http://localhost:8000/v1/workspaces \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: $SENTINEL_ADMIN_KEY" \
  -d '{"name": "my-workspace", "tier": 1}'
```

Copy the `api_key` from the response — it's shown only once. Add it to your `.env`:

```env
SENTINEL_API_KEY=sk-sentinel-...
```

### 7. Start the UI

```bash
cd services/ui
cp .env.local.example .env.local
# edit .env.local: set SENTINEL_API_KEY=sk-sentinel-...
npm install
npm run dev   # → http://localhost:3001
```

---

## Production deployment (Docker Compose)

For a persistent production deployment, run the full stack via Docker Compose.

### 1. Set environment variables

Create a `.env` file alongside `docker-compose.yml`:

```env
DATABASE_URL=postgres://sentinel:sentinel@postgres:5432/sentinel
CLICKHOUSE_URL=clickhouse://clickhouse:9000/sentinel
REDIS_URL=redis://redis:6379/0
SENTINEL_ENV=production

SENTINEL_SECRET_KEY=<generate: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
SENTINEL_ADMIN_KEY=<generate: openssl rand -hex 32>
SENTINEL_API_KEY=<create after first startup>
```

### 2. Build and start

```bash
docker compose build
docker compose up -d
```

Services and ports:

| Service | Port | What |
|---|---|---|
| API | 8000 | REST API |
| UI | 3001 | Web dashboard |
| Postgres | 5432 | Workspace/insight metadata |
| ClickHouse | 9000/8123 | Span/trace data |
| Redis | 6379 | Celery broker |

### 3. Run migrations (first time only)

Alembic lives in `infra/migrations/postgres`, not inside the API container:

```bash
cd infra/migrations/postgres
DATABASE_URL=postgres://sentinel:sentinel@localhost:5432/sentinel \
uv run --no-project alembic upgrade head
cd ../../
```

### 4. Create your workspace

```bash
curl -X POST http://localhost:8000/v1/workspaces \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: YOUR_SENTINEL_ADMIN_KEY" \
  -d '{"name": "production", "tier": 1}'
```

Add the returned `api_key` to `.env` as `SENTINEL_API_KEY`, then restart the UI service:

```bash
docker compose restart ui
```

### 5. Connect a source

Follow the quickstart guide for your observability source:
- [Langfuse](quickstart-langfuse.md)
- [LangSmith](quickstart-langsmith.md)
- [Arize Phoenix](quickstart-arize.md)

---

## Scheduled retention cleanup

Sentinel ships a `enforce_retention` Celery task that deletes spans older than each workspace's retention window (7 days for free tier, 30 days for paid).

Add the beat schedule to `services/worker/src/sentinel_worker/main.py`:

```python
app.conf.beat_schedule = {
    "enforce-retention-nightly": {
        "task": "enforce_retention",
        "schedule": crontab(hour=2, minute=0),   # 2am UTC every night
    },
}
```

Import `crontab` at the top:
```python
from celery.schedules import crontab
```

Start the beat scheduler alongside the worker (separate process):

```bash
# Development
cd services/worker
uv run celery -A sentinel_worker.main beat --loglevel=info

# Production (Docker) — run in a separate container or add to docker-compose.yml
docker compose exec worker celery -A sentinel_worker.main beat --loglevel=info
```

---

## Configuration reference

| Env var | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Postgres connection string |
| `CLICKHOUSE_URL` | Yes | ClickHouse connection string |
| `REDIS_URL` | Yes | Redis URL (Celery broker + backend) |
| `SENTINEL_SECRET_KEY` | Yes | Fernet key for encrypting source credentials at rest |
| `SENTINEL_ADMIN_KEY` | Yes | Secret for workspace provisioning endpoint |
| `SENTINEL_API_KEY` | API key | Used by the UI to authenticate with the API |
| `SENTINEL_ENV` | No | `development` or `production` (default: `development`) |
| `CORS_ORIGINS` | No | Comma-separated allowed origins (default: `http://localhost:3001`) |

---

## Upgrading

```bash
git pull origin main
docker compose build
docker compose up -d

# Run any new migrations
docker compose exec api alembic upgrade head
```

Check the [releases page](https://github.com/sentinelrca/sentinel/releases) before upgrading in production.

---

## Troubleshooting

**API returns 500 on startup**
Check `SENTINEL_SECRET_KEY` is set. Generate one with:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Worker not processing tasks**
Verify Redis is reachable and `REDIS_URL` matches in both API and worker environments.

**ClickHouse tables missing**
The worker creates ClickHouse tables automatically on startup. If they're missing, restart the worker — or run the DDL manually:
```bash
curl -s http://localhost:8123/ -d "$(cat infra/migrations/clickhouse/001_spans.sql)"
curl -s http://localhost:8123/ -d "$(cat infra/migrations/clickhouse/003_project_spans.sql)"
```

**UI shows "synced never"**
The UI reads `last_synced_at` from the source row. Trigger a manual sync:
```bash
curl -X POST http://localhost:8000/v1/sources/$SOURCE_ID/sync \
  -H "Authorization: Bearer $API_KEY"
```
