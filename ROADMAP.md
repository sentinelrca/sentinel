# SentinelRCA Roadmap

SentinelRCA is an open-source observability platform that automatically detects anti-patterns in LLM agent traces and surfaces actionable insights.

---

## Released — M1 + M2

**Rules (7, all free/open source)**

| Rule | Detects | Dimension |
|---|---|---|
| `agent_loop` | Cycle detected — agent bounces between nodes without resolving | Reliability |
| `sequential_tools` | Independent tools called sequentially under same parent | Performance |
| `retry_storm` | Same span retried 3+ times with error status | Reliability |
| `latency_spike` | Single span >50% of total trace duration | Performance |
| `retrieval_without_grounding` | RETRIEVAL returns 0 results but LLM_CALL fires | Reliability |
| `context_cache_opportunity` | Input tokens growing >300 per successive LLM call | Cost |
| `missing_session_memory` | Token growth >1.5× across turns, no memory tool detected | Architecture |

**Connectors**
- Langfuse (pull via REST API)
- LangSmith (pull via REST API)

**Web UI**
- Insight feed with severity filter
- Insight detail + read-only flow graph
- Sources management page

**API**
- `GET /v1/insights` — paginated, filterable
- `GET /v1/flows/{trace_id}` — full DAG as JSON
- `GET/POST/DELETE /v1/sources`

**Infrastructure**
- Docker Compose stack (Postgres + ClickHouse + Redis + API + Worker)
- Incremental sync with overlap window + dedup (idempotent ingestion)
- 96 unit tests

---

## Next — M2.5: Trace-Centric UI

Shifts from insight-centric to trace-centric investigation.

- **Trace health feed** — grouped by trace, worst-severity rollup, rule badge pills, span stats
- **Interactive DAG** — node click opens span detail drawer; rule annotations on affected nodes
- **Timeline/waterfall view** — spans as horizontal bars (width = duration), affected spans highlighted; same drawer on click
- **Span detail drawer** — structured sections: identity, timing, tokens, error, retries, raw attributes, "Flagged by" with human-readable evidence
- **New API endpoints** — `GET /v1/traces`, `GET /v1/traces/{trace_id}/insights`

---

## M3 — v1.0 GA

- **Connectors:** Arize Phoenix, LangWatch, generic OTLP
- **Billing:** Free tier enforcement + Starter tier (self-serve upgrade)
- **Docs:** Quickstart per source, rule reference, self-host guide, connector contribution guide

---

## M4+ — Commercial Tiers

- **Projects** — saved filter sets for focused RCA on a date range or set of trace IDs (Free: 1, Starter: 5)
- **Additional rules** — 10 new structural rules (over-orchestration, cascading failure, missing guardrail, etc.)
- **Alerting** — email + Slack for HIGH/CRITICAL insights; insight lifecycle (OPEN → RESOLVED)
- **Pro tier** — cross-trace rules, team seats, incremental trace import from connectors

---

## M6 — Enterprise

- SSO (SAML 2.0, OIDC)
- RBAC + audit logs
- On-prem Kubernetes Helm chart
- Custom rule builder (YAML DSL)
- Python + TypeScript SDK
- GitHub Action: `sentinel analyze` in CI

---

## Feature Summary by Tier

| Feature | Free | Starter | Pro |
|---|---|---|---|
| Rules | 7 | 7 + 10 | All |
| Sources | 1 | 3 | Unlimited |
| Retention | 7 days | 30 days | 90d+ |
| Projects | 1 | 5 | Unlimited |
| Alerting | — | Email + Slack | Email + Slack + PagerDuty |
| Team seats | 1 | 1 | Up to 5 |
| Cross-trace rules | — | — | ✅ |
| Custom rules | — | — | M6 |

---

## Contributing

See [CLAUDE.md](CLAUDE.md) for the developer guide — adding connectors, adding rules, running tests.

Pull requests welcome. All rules in this repository are MIT licensed.
