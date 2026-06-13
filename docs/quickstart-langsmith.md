# Connect LangSmith in 5 minutes

Pull your LangSmith traces into Sentinel and see your first AI agent insights.

## Prerequisites

- Docker + [go-task](https://taskfile.dev) installed
- A [LangSmith](https://smith.langchain.com) account
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

## 2. Get your LangSmith API key

In LangSmith: **Settings → API Keys → Create API Key**.

Your key looks like `lsv2_pt_...`.

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

## 4. Connect your LangSmith source

```bash
curl -X POST http://localhost:8000/v1/sources \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "langsmith",
    "config_json": {
      "api_key": "lsv2_pt_YOUR_KEY",
      "project_name": "default"
    }
  }'
```

`project_name` is the LangSmith project you want to analyze. Defaults to `"default"` if omitted.

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

Or open the web UI at http://localhost:3001 (see step 1 of the Langfuse quickstart for UI setup).

---

## LangChain tracing tip

To get traces into LangSmith automatically, add this to your app:

```python
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "lsv2_pt_..."
os.environ["LANGCHAIN_PROJECT"] = "my-project"
```

Then run your LangChain/LangGraph app normally — traces appear in LangSmith and Sentinel can pull them.

---

## What Sentinel detects

See the [Langfuse quickstart](./quickstart-langfuse.md#what-to-expect) for the full detector list.
