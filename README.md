# SentinelRCA

**Root cause analysis for AI agents.**

SentinelRCA connects to your existing observability tools (LangSmith, Langfuse, OpenTelemetry) and tells you *why* your AI agents fail — not just *what* happened.

```
$ sentinel analyze --source langsmith --api-key lsv2_pt_...

  Rule                  Severity  Trace           Evidence
  ─────────────────────────────────────────────────────────────────────
  agent_loop            HIGH      trace-abc123    PlannerAgent invoked 4×
  sequential_tools      WARNING   trace-def456    search_web + query_db could save 2.1s
  context_cache         WARNING   trace-ghi789    Input tokens grew 3200→9800 over 6 calls
```

---

## The problem

Langfuse and LangSmith show you a tree of spans. They tell you what your agent called and when. They don't tell you:

- Why your agent is looping between the same two sub-agents
- Which tool calls could run in parallel and save 40% of latency
- Why your costs are growing unbounded across a multi-turn session

SentinelRCA reconstructs the **call graph** from your traces and runs deterministic rules against it to surface specific, actionable fixes.

---

## Quickstart

```bash
# Install
pip install sentinel-cli   # coming soon — use uv for now

# Analyze a LangSmith project
cd tools/cli
uv sync
uv run sentinel analyze \
  --source langsmith \
  --api-key lsv2_pt_YOUR_KEY \
  --project-name your-project

# Analyze a Langfuse project
uv run sentinel analyze \
  --source langfuse \
  --public-key pk-lf-... \
  --secret-key sk-lf-...
```

---

## Rules (M1/M2 — all open source)

| Rule | Detects | Dimension |
|---|---|---|
| `agent_loop` | Same agent invoked 3+ times — infinite handoff | Reliability |
| `sequential_tools` | Two tools ran serially that could run in parallel | Performance |
| `retry_storm` | Same span retried 3+ times — rate limit or flaky tool | Reliability |
| `latency_spike` | Single span consumes >50% of total trace duration | Performance |
| `context_cache_opportunity` | Input tokens growing unbounded across LLM calls | Cost |

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
- **Signal extractor** — critical path, sequential tool pairs, token growth, retry counts
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
```

Requires: Docker, [go-task](https://taskfile.dev), Python 3.12+, [uv](https://docs.astral.sh/uv/)

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
uv run --no-project pytest unit/ -v   # 56 tests, no Docker needed
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
- [x] M2 — LangSmith connector, 5 rules, PII-safe by default
- [ ] M3 — Caching rules, workflow discovery (cluster traces into workflows)
- [ ] M4 — Workflow health dashboard, cross-trace analysis
- [ ] M5 — REST API, web UI

---

## License

MIT — connectors and core pipeline.

The commercial rule engine (`sentinel-engine`) is a separate private package. Free users get the 5 core rules above. See [pricing](https://sentinelrca.com) for the hosted version.

---

## Contributing

Issues and PRs welcome. If you're building a connector for a source we don't support yet, open an issue first so we can align on the interface.
