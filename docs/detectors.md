# Detector Reference

SentinelRCA ships 8 open-source detectors and additional Pro/Enterprise detectors via `sentinel-engine`. All run on trace structure — no prompt or response content is ever read unless you explicitly opt in with `store_content=True`.

Each detector entry covers:
- **What it detects** — the exact condition
- **Thresholds** — the values that trigger it (all tunable via [detector configs API](#tuning-thresholds))
- **Evidence keys** — what the `evidence` object contains in each insight
- **Why it matters** — the production failure mode
- **How to fix it** — concrete remediation

---

## agent_loop

**Severity:** HIGH · **Tier:** Free

### What it detects

Two patterns, either of which fires the detector:

1. **Structural cycle** — a directed cycle exists in the trace graph (Agent A calls Agent B which calls Agent A).
2. **Repeated agent** — the same agent node appears ≥ 3 times in the trace without resolving.

### Thresholds

| Parameter | Default | Meaning |
|---|---|---|
| `_MIN_LOOP_COUNT` | `3` | Minimum invocations of the same agent to flag as a loop |

### Evidence keys

```json
{
  "node_name":   "PlannerAgent",
  "invocations": 4,
  "span_ids":    ["sp-1", "sp-2", "sp-3", "sp-4"],
  "agent_names": ["PlannerAgent", "ExecutorAgent"]
}
```

| Key | Meaning |
|---|---|
| `node_name` | The agent node that repeated |
| `invocations` | How many times it appeared |
| `span_ids` | The affected span IDs |
| `agent_names` | Distinct agent names involved in the cycle |

### Why it matters

An agent loop burns tokens on every cycle and typically never resolves — it either exceeds a token budget or hits a context window limit and crashes. In production, this means a stuck request and a large API bill.

### How to fix it

- **Add a step counter** — pass `step: int` through agent state, check `if step > MAX_STEPS: return fallback`.
- **Break circular dependencies** — one agent must act unconditionally to start the chain. Never let Agent A require output from Agent B while Agent B requires output from Agent A.
- **LangGraph:** set `recursion_limit` on the graph (`graph.compile(recursion_limit=10)`).
- **CrewAI:** set `max_iter` on the crew.

---

## retry_storm

**Severity:** HIGH · **Tier:** Free

### What it detects

Excessive retries on the same span, indicating a flaky tool, rate-limited API, or broken fallback logic.

### Thresholds

| Parameter | Default | Meaning |
|---|---|---|
| `_MIN_RETRIES_PER_SPAN` | `3` | Single span retried this many times → flag |
| `_MIN_TOTAL_RETRIES` | `5` | Total retries across all spans → flag even if no single span hits the per-span threshold |

### Evidence keys

```json
{
  "total_retries":      7,
  "spans_with_retries": 2,
  "max_retries":        5,
  "worst_span_name":    "call_external_api",
  "worst_span_id":      "sp-abc"
}
```

### Why it matters

A retry storm amplifies failure. One rate-limited API call becomes 5 calls in rapid succession, which makes the rate limit worse — and if multiple agents are orchestrating in parallel, one retry storm becomes dozens.

### How to fix it

- **Add exponential backoff** — wait `2^n * base_delay` between retries, not a fixed interval.
- **Set a retry cap** — max 2–3 retries per call, then surface the error.
- **Escalate, don't retry** — after 2 failures, try a different approach or alert a human rather than re-attempting the same call.
- **Use a circuit breaker** — if a tool fails 3+ times in a window, stop sending traffic until it recovers.

> **Note:** Retry detection works best when your framework emits explicit `retry_count` on spans, or when failed intermediate attempts appear as separate `ERROR`-status sibling spans. LangGraph traces may not surface retries automatically.

---

## retrieval_without_grounding

**Severity:** HIGH · **Tier:** Free

### What it detects

A retrieval span (RAG lookup) returns empty results but an LLM call fires immediately after — the model produces output with no factual basis.

Two detection modes:

1. **Empty retrieval** — the retrieval span returns 0 documents (`detection_mode: "empty_retrieval"`).
2. **Token overlap** — the retrieval span returns content but the LLM's input shows < 5% Jaccard overlap with it (`detection_mode: "low_overlap"`), suggesting the retrieved content was ignored.

### Thresholds

| Parameter | Default | Meaning |
|---|---|---|
| `_MIN_TOKEN_GROWTH_RATIO` | `0.10` | Expect ≥10% input token growth after retrieval |
| `_MIN_OVERLAP_RATIO` | `0.05` | Jaccard threshold for content-based grounding check |
| `_MIN_INPUT_TOKENS_TO_CHECK` | `500` | Skip token growth check for very small prompts |

### Evidence keys

```json
{
  "retrieval_span":    "sp-rag-001",
  "detection_mode":   "empty_retrieval",
  "llm_span":         "sp-llm-002"
}
```

### Why it matters

An LLM answering without retrieved context produces hallucinations — confident-sounding answers with no factual basis. In a production agent this means wrong data returned to users, and the error is silent (no exception, just wrong output).

### How to fix it

- **Gate the LLM call** — if retrieval returns 0 results, return `"Insufficient information to answer"` rather than calling the LLM.
- **Log and alert** — empty retrieval on a question that should have answers signals a broken index or query.
- **Check your embedding model** — a mismatch between the embedding model used at index time and query time causes near-zero overlap even with relevant documents.

---

## latency_spike

**Severity:** WARNING · **Tier:** Free

### What it detects

A single span consumes more than 60% of the total trace duration, making it the dominant bottleneck.

Also detects context window pressure: when a span's input tokens exceed 75% of the model's known context window, flagging truncation risk.

### Thresholds

| Parameter | Default | Meaning |
|---|---|---|
| `_CRITICAL_PATH_THRESHOLD` | `0.60` | Flag when a single span > 60% of total trace time |
| `_CONTEXT_UTILIZATION_THRESHOLD` | `0.75` | Flag when input tokens > 75% of model context window |
| `_MIN_PEERS_FOR_THROUGHPUT` | `2` | Minimum peer spans needed for throughput comparison |

### Evidence keys

```json
{
  "span_duration_ms": 4200,
  "total_duration_ms": 4800,
  "ratio": 0.875,
  "model": "gpt-4o"
}
```

### Why it matters

A latency spike usually means the slow span is on the critical path — everything waits for it. 4 seconds in a 4.8-second trace means the parallel work is nearly meaningless.

### How to fix it

- **Move it off the critical path** — if the slow span doesn't depend on other work, start it first in parallel.
- **Cache the result** — if the same slow call happens across multiple traces with the same input, cache it.
- **Use a smaller model for this step** — if the slow span is a long-running LLM call that doesn't require the largest model, route it to a faster one.
- **Prompt caching** — for slow calls with large, repetitive system prompts, enable provider-side prompt caching.

---

## missing_termination_condition

**Severity:** HIGH · **Tier:** Free

### What it detects

An agent workflow with a high number of LLM calls and agent coordination steps, but no structural evidence of a bounded iteration guard (max steps, token budget, or explicit termination condition).

### Thresholds

| Parameter | Default | Meaning |
|---|---|---|
| `_MIN_LLM_CALLS` | `10` | Minimum LLM calls in the trace to flag |
| `_MIN_AGENT_STEPS` | `4` | Minimum agent/chain steps to confirm multi-agent coordination |

### Evidence keys

```json
{
  "llm_call_count":   14,
  "agent_step_count":  6,
  "total_span_count": 23
}
```

### Why it matters

Unbounded agent workflows are the leading cause of runaway costs and infinite loops in production. Without a hard stop, a single user request can trigger hundreds of LLM calls — exhausting budgets and blocking other requests.

### How to fix it

- **Set `recursion_limit`** (LangGraph): `graph.compile(recursion_limit=10)`
- **Set `max_iter`** (CrewAI): `Crew(max_iter=5)`
- **Add a step counter** in agent state and check it explicitly at each node.
- **Token budget guard** — track cumulative tokens and halt if a per-trace budget is exceeded.

---

## sequential_tools

**Severity:** WARNING · **Tier:** Free

### What it detects

Two tool calls that share the same parent span (same orchestrator step) ran back-to-back sequentially, but neither depends on the other's output — they could have run in parallel, saving ≥ 500ms.

### Thresholds

| Parameter | Default | Meaning |
|---|---|---|
| `_MIN_SAVED_MS` | `500.0` | Minimum time savings to flag (ms) — filters out trivially fast tool pairs |

### Evidence keys

```json
{
  "tool_a":   "search_web",
  "tool_b":   "query_database",
  "saved_ms": 2100.0,
  "span_id_a": "sp-001",
  "span_id_b": "sp-002"
}
```

### Why it matters

Sequential execution of independent tools adds avoidable latency. Two 1-second tool calls running sequentially take 2 seconds; in parallel they take 1 second. Across a multi-step agent this compounds quickly.

### How to fix it

- **LangGraph:** use a fan-out node that dispatches both tools in parallel branches, then merge results.
- **LangChain:** use `RunnableParallel` for independent tool calls.
- **Direct async:** `await asyncio.gather(tool_a(), tool_b())` if calling tools directly.

---

## context_cache_opportunity

**Severity:** WARNING · **Tier:** Free

### What it detects

Multiple LLM calls in the same trace share a large static prefix in their input tokens (system prompt, document context, or instructions) that never changes — a strong signal for provider-side prompt caching.

### Thresholds

| Parameter | Default | Meaning |
|---|---|---|
| `_MIN_REPEATED_CALLS` | `2` | Minimum LLM calls with similar input to flag |
| `_MIN_CACHE_TOKENS_DEFAULT` | `1024` | Minimum shared prefix tokens to flag (below this, caching is not worth the overhead) |

### Evidence keys

```json
{
  "repeated_prefix_tokens": 3200,
  "affected_call_count":    4,
  "estimated_savings_pct":  68
}
```

### Why it matters

Re-sending the same 3,000-token system prompt on every LLM call in a trace wastes ~70% of your input tokens. With Anthropic prompt caching, re-used prefixes cost ~90% less. The more calls per trace, the bigger the saving.

### How to fix it

- **Anthropic:** set `cache_control: {"type": "ephemeral"}` on the system prompt block.
- **OpenAI:** prompt caching is automatic on gpt-4o-mini and gpt-4o for inputs > 1024 tokens.
- **Architecture:** extract the static prefix (system prompt, document) as a shared context, send it once at the start of the conversation rather than on every call.

---

## missing_session_memory

**Severity:** WARNING · **Tier:** Free

### What it detects

Input tokens grow significantly across turns in a multi-turn session, with no evidence of memory tool calls (no `memory_read`, `pensieve_recall`, or similar) — the agent is re-sending the entire conversation history instead of using a memory layer.

### Evidence keys

```json
{
  "turn_count":         6,
  "token_growth_ratio": 3.4,
  "first_turn_tokens":  820,
  "last_turn_tokens":   2790
}
```

### Why it matters

Without a memory layer, token counts grow O(n) with conversation length — doubling every few turns. Users repeat themselves because the agent forgets context. Costs grow unbounded.

### How to fix it

- **Add a memory tool** — `memory_store` / `memory_retrieve` calls that summarize and recall context.
- **Sliding window** — keep only the last N turns in the context window, truncate the rest.
- **Summarization** — when context exceeds a threshold, summarize earlier turns into a single compact entry.

---

## token_cost_runaway

**Severity:** HIGH · **Tier:** Free

### What it detects

A single trace consumes anomalously high tokens across all its LLM calls — exceeding safe thresholds for input, output, or total token usage.

### Thresholds

| Parameter | Default | Meaning |
|---|---|---|
| `_MAX_INPUT_TOKENS` | `50,000` | Total input tokens across all LLM calls in the trace |
| `_MAX_OUTPUT_TOKENS` | `10,000` | Total output tokens across all LLM calls |
| `_MAX_TOTAL_TOKENS` | `100,000` | Combined input + output ceiling |

### Evidence keys

```json
{
  "total_input_tokens":  62000,
  "total_output_tokens":  3100,
  "total_tokens":        65100,
  "top_consumers": [
    {"span_id": "sp-001", "name": "summarize_docs", "input_tokens": 48000, "model": "gpt-4o"}
  ],
  "thresholds": {
    "max_input_tokens": 50000,
    "max_output_tokens": 10000,
    "max_total_tokens": 100000
  }
}
```

### Why it matters

A single runaway trace can cost $5–50+ at typical API pricing. Without guardrails, a user or automated workflow can trigger traces that exhaust a monthly budget in hours.

### How to fix it

- **Set a per-trace token budget** — track cumulative tokens in agent state and halt when exceeded.
- **Use smaller models for intermediate steps** — reserve large models for final synthesis.
- **Enable prompt caching** — cuts input token costs by 60–90% for repeated system prompts.
- **Chunk large inputs** — split large documents into smaller chunks and process incrementally.

---

---

## Pro / Enterprise Detectors

The following detectors are available in `sentinel-engine` (Pro and Enterprise tiers).
They install alongside the OSS core and register automatically.

| Detector | Severity | What it catches |
|---|---|---|
| `cascading_failure_propagation` | CRITICAL / HIGH | Single failure propagating through call tree; isolates root cause from cascade victims |

Full reference: [sentinel-engine/docs/detectors-pro.md](https://github.com/sentinelrca/sentinel-engine/blob/main/docs/detectors-pro.md)

---

## Tuning thresholds

All thresholds are overridable per workspace via the detector configs API:

```bash
# Disable a detector for your workspace
curl -X PUT http://localhost:8000/v1/detector-configs/latency_spike \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action": "DISABLED"}'

# Override severity
curl -X PUT http://localhost:8000/v1/detector-configs/sequential_tools \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action": "OVERRIDE_SEVERITY", "severity": "info"}'
```

Threshold values (e.g. `_MIN_LOOP_COUNT`) are constants in the detector source files — edit them directly if you're self-hosting and want different defaults.
