<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg"/>
    <img src="assets/logo.svg" alt="SentinelRCA" height="52"/>
  </picture>
</p>

<p align="center"><strong>Root cause analysis for AI agents.</strong></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"/></a>
  <img src="https://img.shields.io/badge/tests-373%20passing-brightgreen.svg" alt="Tests"/>
  <a href="https://github.com/sentinelrca/sentinel/discussions"><img src="https://img.shields.io/badge/discussions-GitHub-blue?logo=github" alt="Discussions"/></a>
</p>

SentinelRCA connects to your existing observability tools (LangSmith, Langfuse, Arize Phoenix, OpenTelemetry) and tells you *why* your AI agents fail, *what's slowing them down*, and *what to fix* — not just what happened.

```
$ sentinel analyze --source langsmith --api-key lsv2_pt_...

  Detector                  Severity  Trace           Evidence
  ──────────────────────────────────────────────────────────────────────────
  agent_loop                HIGH      trace-abc123    PlannerAgent invoked 4×
  sequential_tools          WARNING   trace-def456    search_web + query_db could save 2.1s
  context_cache_opportunity WARNING   trace-ghi789    Input tokens grew 3200→9800 over 6 calls
  token_cost_runaway        HIGH      trace-jkl012    62k tokens in one trace — 24% above threshold
```

---

## Why SentinelRCA

Langfuse and LangSmith show you a tree of spans. They tell you *what* your agent called and *when*. They don't tell you:

- Why your agent is looping between the same two sub-agents
- Which tool calls could run in parallel and save 40% of latency
- Why your costs are growing unbounded across a multi-turn session
- That a single retrieval timeout silently cascaded into a full trace failure

SentinelRCA reconstructs the **call graph** from your traces and runs deterministic detectors against it to surface specific, actionable fixes.

---

## Quickstart

Connect your observability source in 5 minutes:

| Source | Guide |
|---|---|
| Langfuse | [Connect Langfuse →](docs/quickstart-langfuse.md) |
| LangSmith | [Connect LangSmith →](docs/quickstart-langsmith.md) |
| Arize Phoenix | [Connect Arize Phoenix →](docs/quickstart-arize.md) |

**Or use the CLI (no server needed):**
```bash
cd tools/cli && uv sync
uv run sentinel analyze --source langsmith --api-key lsv2_pt_YOUR_KEY
uv run sentinel analyze --source langfuse  --public-key pk-lf-... --secret-key sk-lf-...
```

---

## Detectors — 8 open source, all free

| Detector | What it catches | Severity |
|---|---|---|
| `agent_loop` | Same agent invoked 3+ times — infinite handoff | HIGH |
| `retry_storm` | Same span retried 3+ times without backoff | HIGH |
| `retrieval_without_grounding` | Empty retrieval followed by LLM call — hallucination risk | HIGH |
| `missing_termination_condition` | Unbounded agent workflow with no iteration guard | HIGH |
| `token_cost_runaway` | Single trace consuming anomalously high tokens | HIGH |
| `latency_spike` | One span consuming >50% of total trace time | WARNING |
| `sequential_tools` | Tool calls that could run in parallel | WARNING |
| `context_cache_opportunity` | Input tokens growing unbounded across LLM calls | WARNING |

All detectors run on trace structure only — **no prompt or response content is ever stored by default**.

---

## Projects — offline batch analysis

Beyond live trace monitoring, SentinelRCA lets you create **Projects**: import a snapshot of traces from a date range, run all detectors across the batch, and explore results trace-by-trace in the UI.

Use this to:
- **Debug a regression** — import traces from before and after a deploy, compare insight counts
- **Audit a model swap** — snapshot 500 traces from the old model, 500 from the new, see which detectors fire more
- **Investigate an incident** — pull the exact traces from a 2-hour window and do offline RCA

Projects are available in the web UI and via the REST API (`POST /v1/projects`).

---

## Architecture

```
Source (LangSmith / Langfuse / Arize / OTLP)
        ↓  connector.pull()
  list[NormalizedSpan]
        ↓  build_graph()
      FlowGraph (NetworkX DiGraph)
        ↓  extract_signals()
         Signals
        ↓  run_detectors()
      list[Insight]  ←  specific recommendation + evidence
```

- **Connectors** — thin pull adapters per source, always MIT licensed
- **Graph builder** — reconstructs parent-child tree, cycle detection, clock skew correction
- **Signal extractor** — critical path, sequential tool pairs, token growth, retry inference
- **Detector engine** — deterministic pattern matching, no LLMs involved in detection

---

## Self-hosting

```bash
# 1. Start infrastructure
task up   # Postgres + ClickHouse + Redis
cd infra/migrations/postgres && uv run alembic upgrade head

# 2. Start services
cd services/api    && uv run uvicorn sentinel_api.main:app --port 8000
cd services/worker && uv run celery -A sentinel_worker.main worker

# 3. Start UI → http://localhost:3001
cp services/ui/.env.local.example services/ui/.env.local
cd services/ui && npm install && npm run dev
```

Or run the full stack with Docker Compose:
```bash
docker compose up
```

**Requirements:** Docker, [go-task](https://taskfile.dev), Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+

---

## Data privacy

- Prompt and response content is **never stored by default** (`store_content=False`)
- Only structural metadata: span IDs, timestamps, token counts, agent names, latency
- Fully self-hostable — traces never leave your network
- `store_content=True` is an explicit opt-in per source

---

## Roadmap

- [x] M1 — Langfuse connector, flow graph, 2 detectors, CLI
- [x] M2 — LangSmith connector, 7 detectors, web UI, PII-safe by default
- [x] M3 — Arize Phoenix connector, 8 detectors, workspace API, self-host ready
- [ ] M4 — More detectors, Slack/PagerDuty alerting, insight lifecycle
- [ ] M5 — Cross-trace detectors, workflow discovery, Pro tier
- [ ] M6 — SSO, on-prem Helm, custom detector builder, enterprise tier

---

## Community

- **[GitHub Discussions](https://github.com/sentinelrca/sentinel/discussions)** — questions, ideas, show & tell
- **[Issues](https://github.com/sentinelrca/sentinel/issues)** — bug reports and feature requests
- Building a connector for a source we don't support? Open a discussion first so we can align on the interface.

---

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the connector and detector authoring guides.

```bash
cd tests && uv sync --no-install-project
uv run --no-project pytest unit/   # 373 tests, no Docker needed
```

---

## License

MIT — connectors and core pipeline.

The commercial detector engine (`sentinel-engine`) is a separate private package. Free users get all 8 core detectors. See [sentinelrca.com](https://sentinelrca.com) for the hosted version.
