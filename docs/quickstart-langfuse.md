# Connect Langfuse in 5 minutes

Pull your Langfuse traces into Sentinel and see your first AI agent insights.

## Prerequisites

- Docker + [go-task](https://taskfile.dev) installed
- A [Langfuse](https://cloud.langfuse.com) account (cloud or self-hosted)
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) installed

---

## 1. Start the Sentinel stack

```bash
git clone https://github.com/sentinelrca/sentinel
cd sentinel/code

task up                                                          # Postgres + ClickHouse + Redis
cd infra/migrations/postgres && uv run alembic upgrade head     # run DB migrations
cd ../../
```

Start the API and worker in two terminals:

```bash
# Terminal 1 — API
cd services/api
uv sync
SENTINEL_SECRET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
SENTINEL_ADMIN_KEY=$(openssl rand -hex 32) \
uv run uvicorn sentinel_api.main:app --port 8000
```

```bash
# Terminal 2 — Worker
cd services/worker
uv sync
SENTINEL_SECRET_KEY=<same key as above> \
uv run celery -A sentinel_worker.main worker --loglevel=info
```

> **Tip:** Save both keys to a `.env` file in `code/` — every service reads it automatically.

---

## 2. Create your workspace and get an API key

```bash
curl -X POST http://localhost:8000/v1/workspaces \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: $SENTINEL_ADMIN_KEY" \
  -d '{"name": "my-workspace"}'
```

Response:
```json
{
  "id": "ws-...",
  "api_key": "sk-sentinel-abc123...",
  "name": "my-workspace",
  "tier": 0
}
```

**Save the `api_key` — it's shown only once.** Use it as `$API_KEY` for all subsequent requests.

---

## 3. Connect your Langfuse source

```bash
curl -X POST http://localhost:8000/v1/sources \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "langfuse",
    "config_json": {
      "public_key": "pk-lf-YOUR_PUBLIC_KEY",
      "secret_key": "sk-lf-YOUR_SECRET_KEY",
      "host": "https://cloud.langfuse.com"
    }
  }'
```

For self-hosted Langfuse, set `"host": "http://your-langfuse-host:3000"`.

---

## 4. Sync your traces

```bash
SOURCE_ID="src-..."   # from the response above

curl -X POST http://localhost:8000/v1/sources/$SOURCE_ID/sync \
  -H "Authorization: Bearer $API_KEY"
```

The worker will pull traces and run all 8 detectors. For large projects this takes 10–60 seconds.

---

## 5. View your insights

```bash
curl http://localhost:8000/v1/insights \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool
```

Or open the web UI:

```bash
cd services/ui
cp .env.local.example .env.local
# edit .env.local: set SENTINEL_API_KEY=sk-sentinel-abc123...
npm install && npm run dev   # → http://localhost:3001
```

---

## What to expect

Sentinel runs 8 detectors against your traces:

| Detector | What it catches |
|---|---|
| `agent_loop` | Agent cycling without progress |
| `retry_storm` | Same tool retried 3+ times |
| `latency_spike` | One span consuming >50% of trace time |
| `retrieval_without_grounding` | Empty retrieval followed by LLM call |
| `sequential_tools` | Tools that could run in parallel |
| `context_cache_opportunity` | Input tokens growing across calls |
| `missing_termination_condition` | Unbounded agent workflow |
| `token_cost_runaway` | Single trace exceeding token budget |

Each insight includes a specific recommendation and the affected span IDs.

---

## Troubleshooting

**"Connection test failed"** — Check your Langfuse keys and host URL. Verify the project exists.

**No insights after sync** — Check the worker logs. Your traces may be clean (no issues detected) — that's a good thing.

**Free tier limits** — Free workspaces sync up to 3 times per week, 500 traces per sync, 7-day retention. Upgrade to remove limits.
