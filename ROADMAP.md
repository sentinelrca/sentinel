# SentinelRCA Roadmap

SentinelRCA is an open-source observability platform that automatically detects anti-patterns in LLM agent traces and surfaces actionable insights.

---

## Released — M1 + M2

**Built-in detections (7, all free/open source)**

| Detection | What it catches | Dimension |
|---|---|---|
| `agent_loop` | Agent cycles between nodes without making progress | Reliability |
| `sequential_tools` | Independent tool calls that could run in parallel | Performance |
| `retry_storm` | Repeated failures on the same operation | Reliability |
| `latency_spike` | A single step dominating total trace duration | Performance |
| `retrieval_without_grounding` | LLM call proceeds after retrieval returns nothing | Reliability |
| `context_cache_opportunity` | Prompt context growing unnecessarily across LLM calls | Cost |
| `missing_session_memory` | Agent re-receiving context it has seen before — no memory in use | Architecture |

**Connectors**
- Langfuse (pull via REST API)
- LangSmith (pull via REST API)

**Web UI**
- Insight feed with severity filter
- Insight detail + flow graph
- Sources management page

**API**
- `GET /v1/insights` — paginated, filterable
- `GET /v1/flows/{trace_id}` — full DAG as JSON
- `GET/POST/DELETE /v1/sources`

**Infrastructure**
- Docker Compose stack (Postgres + ClickHouse + Redis + API + Worker)
- Incremental sync with dedup (idempotent ingestion)
- 96 unit tests

---

## Next — M2.5: Trace-Centric UI

Shifts from insight-centric to trace-centric investigation.

- **Trace health feed** — grouped by trace, worst-severity rollup, detection badges, span stats
- **Interactive DAG** — node click opens span detail drawer; affected nodes annotated inline
- **Timeline/waterfall view** — spans as horizontal bars (width = duration), affected spans highlighted
- **Span detail drawer** — identity, timing, tokens, error, retries, raw attributes, human-readable explanation of what was detected and why
- **New API endpoints** — `GET /v1/traces`, `GET /v1/traces/{trace_id}/insights`

---

## M3 — v1.0 GA

- **Connectors:** Arize Phoenix, LangWatch, generic OTLP
- **Billing:** Free tier enforcement + Starter tier (self-serve upgrade)
- **Docs:** Quickstart per source, detection reference, self-host guide, connector contribution guide

---

## M4+ — Commercial Tiers

- **Projects** — saved filter sets for focused RCA on a date range or set of trace IDs (Free: 1, Starter: 5)
- **Extended detection library** — 10 additional checks (over-orchestration, cascading failure, missing guardrail, and more)
- **Alerting** — email + Slack for HIGH/CRITICAL insights; insight lifecycle (OPEN → RESOLVED)
- **Pro tier** — cross-trace analysis, team seats, incremental trace import from connectors

---

## M6 — Enterprise

- SSO (SAML 2.0, OIDC)
- RBAC + audit logs
- On-prem Kubernetes Helm chart
- Custom detection builder
- Python + TypeScript SDK
- GitHub Action: `sentinel analyze` in CI

---

## Feature Summary by Tier

| Feature | Free | Starter | Pro |
|---|---|---|---|
| Detections | 7 | 7 + 10 | All |
| Sources | 1 | 3 | Unlimited |
| Retention | 7 days | 30 days | 90d+ |
| Projects | 1 | 5 | Unlimited |
| Alerting | — | Email + Slack | Email + Slack + PagerDuty |
| Team seats | 1 | 1 | Up to 5 |
| Cross-trace analysis | — | — | ✅ |
| Custom detections | — | — | M6 |

---

## Contributing

See [CLAUDE.md](CLAUDE.md) for the developer guide — adding connectors, adding detections, running tests.

Pull requests welcome. All detections in this repository are MIT licensed.
