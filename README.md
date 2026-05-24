# SentinelRCA

**Diagnose failures. Optimize performance. Improve architecture. Scale with confidence. For AI agents.**

SentinelRCA connects to your existing observability tools (LangSmith, Langfuse, OpenTelemetry) and tells you *why* your AI agents fail, *what's slowing them down*, *what to fix before it becomes a production incident*, and *where your system breaks under load* — not just what happened.

```
$ sentinel analyze --source langsmith --api-key lsv2_pt_...

  Detector                  Severity  Trace           Evidence
  ──────────────────────────────────────────────────────────────────────────
  agent_loop                HIGH      trace-abc123    PlannerAgent invoked 4×
  sequential_tools          WARNING   trace-def456    search_web + query_db could save 2.1s
  context_cache_opportunity WARNING   trace-ghi789    Input tokens grew 3200→9800 over 6 calls
  missing_session_memory    WARNING   trace-jkl012    7 turns, tokens +340% — no memory tool detected
```

---

## The problem

Langfuse and LangSmith show you a tree of spans. They tell you what your agent called and when. They don't tell you:

- Why your agent is looping between the same two sub-agents
- Which tool calls could run in parallel and save 40% of latency
- Why your costs are growing unbounded across a multi-turn session
- That your agent has no memory layer and your users are repeating themselves

SentinelRCA reconstructs the **call graph** from your traces and runs deterministic rules against it to surface specific, actionable fixes — across three dimensions:

| Dimension | What it catches |
|---|---|
| **Diagnose** | Agent loops, retry storms, retrieval failures, cascading errors |
| **Optimize** | Sequential tools that could parallelize, latency spikes, context bloat, suboptimal model routing |
| **Improve** | Missing memory layer, no guardrails, unvalidated LLM output, architectural gaps before they cause failures |
| **Scale** | Fan-out rate limits, thundering herd, orchestrator bottlenecks, latency degradation under load |

---

## Quickstart

**CLI (stateless, no setup):**
```bash
cd tools/cli
uv sync
uv run sentinel analyze \
  --source langsmith \
  --api-key lsv2_pt_YOUR_KEY \
  --project-name your-project

# or Langfuse
uv run sentinel analyze \
  --source langfuse \
  --public-key pk-lf-... \
  --secret-key sk-lf-...
```

**Web UI (persistent insight feed + flow graph):**
```bash
task up   # starts Postgres + ClickHouse + Redis
cd infra/migrations/postgres && uv run alembic upgrade head
cd services/api && uv run uvicorn sentinel_api.main:app --port 8000
cp services/ui/.env.local.example services/ui/.env.local
cd services/ui && npm install && npm run dev   # http://localhost:3001
```

---

## Rules (M1/M2 — all open source)

### Diagnose — why it failed

| Rule | Detects | Severity |
|---|---|---|
| `agent_loop` | Same agent invoked 3+ times — infinite handoff | HIGH |
| `retry_storm` | Same span retried 3+ times — rate limit or flaky tool | HIGH |
| `retrieval_without_grounding` | Retrieval returns 0 results but LLM call fires — hallucination risk | HIGH |
| `latency_spike` | Single span consumes >50% of total trace duration | WARNING |

### Optimize — what's inefficient

| Rule | Detects | Severity |
|---|---|---|
| `sequential_tools` | Two tools ran serially that could run in parallel | WARNING |
| `context_cache_opportunity` | Input tokens growing unbounded across LLM calls | WARNING |

### Improve — architectural gaps

| Rule | Detects | Severity |
|---|---|---|
| `missing_session_memory` | Input tokens growing across turns with no memory tool calls — users are repeating themselves | WARNING |

All rules operate on trace structure only — **no prompt or response content is ever stored by default**.

---

## Architecture

```
Source (LangSmith / Langfuse / OTLP)
        ↓  connector.pull()
  list[NormalizedSpan]
        ↓  build_graph()
      FlowGraph (NetworkX DiGraph)
        ↓  extract_signals()
         Signals
        ↓  run_rules()
      list[Insight]  ←  specific recommendation + evidence
```

- **Connectors** — thin pull adapters, one per source, always free and open source
- **Graph builder** — reconstructs parent-child tree, detects agent handoffs, cycle detection, clock skew correction
- **Signal extractor** — critical path, sequential tool pairs, token growth, retry counts, session memory patterns
- **Rule engine** — deterministic pattern matching, no LLMs involved in detection

---

## Self-hosting

```bash
# Start infrastructure (Postgres, ClickHouse, Redis)
task up

# Run migrations
cd infra/migrations/postgres && uv run alembic upgrade head

# Start services
cd services/api    && uv run uvicorn sentinel_api.main:app --reload --port 8000
cd services/worker && uv run celery -A sentinel_worker.main worker --loglevel=info

# Start web UI  →  http://localhost:3001
cp services/ui/.env.local.example services/ui/.env.local
# edit .env.local: set SENTINEL_API_KEY to a valid workspace API key
cd services/ui && npm install && npm run dev
```

Or run the full stack with Docker Compose (includes UI on port 3001):
```bash
SENTINEL_API_KEY=sk-sentinel-dev docker compose up
```

Requires: Docker, [go-task](https://taskfile.dev), Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+

---

## Adding a connector

```
1. Create connectors/<source>/
2. Implement Connector ABC from connectors/_base/src/sentinel_connectors/base.py
3. Add tests in tests/unit/connectors/test_<source>.py
4. Open a PR
```

Connectors are always MIT licensed. See [CLAUDE.md](CLAUDE.md) for the full guide.

---

## Tests

```bash
cd tests
uv sync --no-install-project
uv run --no-project pytest unit/ -v   # 58 tests, no Docker needed
```

---

## Data privacy

- Prompt and response content is **never stored by default** (`store_content=False`)
- Only structural metadata is stored: span IDs, timestamps, token counts, agent names, latency
- Fully self-hostable — traces never leave your network
- `store_content=True` is an explicit opt-in per source

---

## Roadmap

- [x] M1 — Langfuse connector, flow graph, 2 rules, CLI
- [x] M2 — LangSmith connector, 7 rules, web UI, PII-safe by default
- [ ] M3 — Arize + LangWatch connectors, docs, v1.0 GA, Starter billing
- [ ] M4 — Rules 8–17, email/Slack/PagerDuty alerting, insight lifecycle
- [ ] M5 — Cross-trace rules, workflow discovery, Pro tier
- [ ] M6 — SSO, on-prem Helm, custom rule builder, enterprise tier

---

## License

MIT — connectors and core pipeline.

The commercial rule engine (`sentinel-engine`) is a separate private package. Free users get the 7 core rules above. See [pricing](https://sentinelrca.com) for the hosted version.

---

## Contributing

Issues and PRs welcome. If you're building a connector for a source we don't support yet, open an issue first so we can align on the interface.
