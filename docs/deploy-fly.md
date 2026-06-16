# Deploy to Fly.io (free tier)

Deploys SentinelRCA as a live hosted service at zero cost using:
- **Fly.io** — API + worker (3 free shared VMs)
- **Neon** — Postgres (free, 0.5 GB)
- **Upstash** — Redis (free, 10k cmds/day)
- **Tinybird** — OLAP spans storage (free, 10 GB) ← already configured
- **Vercel** — Next.js UI (free)

---

## Prerequisites

```bash
# Install Fly CLI
brew install flyctl

# Log in
fly auth login
```

---

## Step 1 — External services

### Neon (Postgres)

1. Sign up at [neon.tech](https://neon.tech) (free tier)
2. Create a project → copy the connection string
3. **Important:** prefix must be `postgresql+asyncpg://` for SQLAlchemy async.
   Neon gives you `postgresql://...` — change the prefix:
   ```
   postgresql+asyncpg://user:pass@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

### Upstash (Redis)

1. Sign up at [upstash.com](https://upstash.com) (free tier)
2. Create a Redis database → use the **Redis URL** (not the REST URL):
   ```
   rediss://default:xxx@xxx.upstash.io:6380
   ```

---

## Step 2 — Generate secrets

```bash
# Fernet key for encrypting source credentials at rest
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Admin key for workspace provisioning
openssl rand -hex 32
```

---

## Step 3 — Run Postgres migrations (before deploy)

Run migrations from your local machine pointing at Neon — the Docker image
does not include the `alembic` config or migration scripts.

```bash
cd infra/migrations/postgres
DATABASE_URL="postgresql+asyncpg://..." uv run --no-project alembic upgrade head
```

---

## Step 4 — Deploy the API

```bash
# Create the app (first time only)
fly launch --no-deploy --config fly.toml

# Set all secrets
fly secrets set \
  DATABASE_URL="postgresql+asyncpg://..." \
  REDIS_URL="rediss://..." \
  SENTINEL_SECRET_KEY="your-fernet-key" \
  SENTINEL_ADMIN_KEY="your-admin-key" \
  TINYBIRD_API_KEY="p.eyJ1IjogI..." \
  TINYBIRD_HOST="https://api.us-east.aws.tinybird.co" \
  CORS_ORIGINS="https://your-app.vercel.app" \
  --config fly.toml

# Deploy
fly deploy --config fly.toml
```

> **CORS_ORIGINS** must match your Vercel URL exactly (set it now even if you
> don't know the URL yet — update it after Vercel deployment in Step 6).

---

## Step 5 — Deploy the worker

```bash
# Create the worker app (first time only)
fly launch --no-deploy --config fly.worker.toml

# Same secrets as the API
fly secrets set \
  DATABASE_URL="postgresql+asyncpg://..." \
  REDIS_URL="rediss://..." \
  SENTINEL_SECRET_KEY="your-fernet-key" \
  TINYBIRD_API_KEY="p.eyJ1IjogI..." \
  TINYBIRD_HOST="https://api.us-east.aws.tinybird.co" \
  --config fly.worker.toml

# Deploy
fly deploy --config fly.worker.toml
```

---

## Step 6 — Create your first workspace

```bash
API_URL="https://sentinel-api.fly.dev"

curl -X POST $API_URL/v1/workspaces \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: $SENTINEL_ADMIN_KEY" \
  -d '{"name": "my-workspace", "tier": 1}'
```

Copy the `api_key` from the response — **shown once only**.

---

## Step 7 — Deploy the UI to Vercel

1. Go to [vercel.com](https://vercel.com) → New Project → Import `sentinelrca/sentinel`
2. Set root directory to `services/ui`
3. Add environment variables:
   ```
   SENTINEL_API_URL=https://sentinel-api.fly.dev
   SENTINEL_API_KEY=sk-sentinel-<workspace-api-key-from-step-6>
   ```
4. Deploy → note the URL (e.g. `https://sentinel-ui.vercel.app`)
5. Update `CORS_ORIGINS` on the API to match:
   ```bash
   fly secrets set CORS_ORIGINS="https://sentinel-ui.vercel.app" --config fly.toml
   fly deploy --config fly.toml
   ```

---

## Verify

```bash
# API health
curl https://sentinel-api.fly.dev/health
# → {"status":"ok"}

# List sources (authenticated)
curl https://sentinel-api.fly.dev/v1/sources \
  -H "Authorization: Bearer sk-sentinel-..."
# → {"items":[]}
```

---

## Retention cleanup (optional)

To run nightly span cleanup, add a Fly.io scheduled machine:

```bash
fly machine run \
  --schedule daily \
  --app sentinel-worker \
  --config fly.worker.toml \
  -- celery -A sentinel_worker.main call enforce_retention
```

---

## Costs

All free tiers. Estimated first paid tier upgrade triggers:
- **Neon**: at 0.5 GB Postgres (workspace/insight metadata — months away)
- **Upstash**: at 10k Redis commands/day (heavy Celery use — unlikely on free tier)
- **Tinybird**: at 10 GB spans (millions of spans — months away)
- **Fly.io**: at 4th VM or sustained CPU usage

For the soft-launch, everything stays at $0.
