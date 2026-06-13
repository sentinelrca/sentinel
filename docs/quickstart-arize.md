# Connect Arize Phoenix in 5 minutes

Pull your Arize Phoenix traces into Sentinel and see your first AI agent insights.

Works with both **Phoenix Cloud** (`app.phoenix.arize.com`) and **Phoenix OSS** (self-hosted).

## Prerequisites

- Docker + [go-task](https://taskfile.dev) installed
- An [Arize Phoenix](https://app.phoenix.arize.com) account, or a local Phoenix OSS instance
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

---

## 2. Get your Phoenix credentials

**Phoenix Cloud:**
1. Go to `app.phoenix.arize.com` → Settings → API Keys
2. Create a key — it looks like `eyJhbGciOi...`
3. Your space URL is `https://app.phoenix.arize.com/s/your-space-name`

**Phoenix OSS (local):**
- Host: `http://localhost:6006`
- No API key needed

---

## 3. Create your workspace and get an API key

```bash
curl -X POST http://localhost:8000/v1/workspaces \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: $SENTINEL_ADMIN_KEY" \
  -d '{"name": "my-workspace"}'
```

**Save the `api_key` — it's shown only once.** Use it as `$API_KEY` below.

---

## 4. Connect your Phoenix source

**Phoenix Cloud:**
```bash
curl -X POST http://localhost:8000/v1/sources \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "arize_phoenix",
    "config_json": {
      "host": "https://app.phoenix.arize.com/s/YOUR_SPACE_NAME",
      "api_key": "eyJhbGciOi...",
      "project_name": "your-project"
    }
  }'
```

**Phoenix OSS (local):**
```bash
curl -X POST http://localhost:8000/v1/sources \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "arize_phoenix",
    "config_json": {
      "host": "http://localhost:6006",
      "project_name": "default"
    }
  }'
```

---

## 5. Sync your traces

```bash
SOURCE_ID="src-..."   # from the response above

curl -X POST http://localhost:8000/v1/sources/$SOURCE_ID/sync \
  -H "Authorization: Bearer $API_KEY"
```

---

## 6. View your insights

```bash
curl http://localhost:8000/v1/insights \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool
```

---

## Sending traces to Phoenix from your app

Add OpenInference instrumentation to your LangChain/LangGraph app:

```bash
pip install arize-phoenix-otel openinference-instrumentation-langchain
```

```python
from phoenix.otel import register
from openinference.instrumentation.langchain import LangChainInstrumentor

tracer_provider = register(
    project_name="my-project",
    endpoint="https://app.phoenix.arize.com/s/YOUR_SPACE_NAME/v1/traces",
    api_key="eyJhbGciOi...",
)
LangChainInstrumentor().instrument(tracer_provider=tracer_provider)

# Now run your LangChain/LangGraph app — traces appear in Phoenix automatically
```

For local Phoenix OSS:
```python
tracer_provider = register(
    project_name="my-project",
    endpoint="http://localhost:6006/v1/traces",
)
```

---

## What Sentinel detects

See the [Langfuse quickstart](./quickstart-langfuse.md#what-to-expect) for the full detector list.

> **Note:** Retry detection (`retry_storm`) works best when your framework emits explicit retry counts or error-status intermediate spans. LangGraph traces may not surface retries automatically.
