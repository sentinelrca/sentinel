# SentinelAI Examples

Runnable multi-agent scenarios that deliberately trigger SentinelAI detectors.
Each scenario is a real LangGraph agent making a real mistake — the kind your
own agents might be making right now without you knowing.

## Structure

```
examples/
├── shared/                    ← theme-independent utilities
│   ├── llm.py                 ← get_llm()  — works with any provider
│   └── observability.py      ← configure() — Langfuse or LangSmith
└── scenarios/
    └── harry_potter/          ← current theme (self-contained, replaceable)
        ├── README.md
        ├── shared/tools.py    ← HP-themed tools (accio, alohomora, brew_potion…)
        ├── 01_agent_loop/
        ├── 02_sequential_tools/
        ├── 03_retry_storm/
        ├── 04_latency_spike/
        ├── 05_retrieval_without_grounding/
        ├── 06_context_cache_opportunity/
        └── 07_missing_session_memory/
```

The `scenarios/harry_potter/` directory is self-contained. To use a different
theme, drop in a replacement directory with the same internal structure.

## Setup

```bash
cd examples
cp .env.example .env
# Fill in SENTINEL_MODEL + one backend (LANGFUSE or LANGSMITH section)
uv sync
```

## Run a scenario

```bash
python scenarios/harry_potter/01_agent_loop/da_war_council.py
python scenarios/harry_potter/05_retrieval_without_grounding/trelawneys_briefing.py
# etc.
```

Each script prints what went wrong and which SentinelAI detector would fire.
Run `sentinel analyze` pointed at your backend to see the actual insight.

## The scenarios

| # | Scenario | Detector | Severity |
|---|---|---|---|
| 01 | The DA War Council | `agent_loop` | HIGH |
| 02 | The Two-Owl Problem | `sequential_tools` | MEDIUM |
| 03 | Dobby's Persistence | `retry_storm` | HIGH |
| 04 | Snape's Potion | `latency_spike` | HIGH |
| 05 | Trelawney's Briefing | `retrieval_without_grounding` | CRITICAL |
| 06 | Hermione's Homework | `context_cache_opportunity` | MEDIUM |
| 07 | Neville's Notes | `missing_session_memory` | MEDIUM |

## Supported models

Set `SENTINEL_MODEL` in `.env` to any of:

```
gpt-4o-mini          # OpenAI (default)
gpt-4o               # OpenAI
claude-haiku-4-5-20251001   # Anthropic
claude-sonnet-4-6    # Anthropic
ollama:qwen2.5:3b    # Local Ollama (free, no key needed)
groq:llama-3.1-8b-instant   # Groq (free tier)
```

## Supported observability backends

Set `SENTINEL_BACKEND=langfuse` or `SENTINEL_BACKEND=langsmith`.
See `.env.example` for credential configuration for each.
