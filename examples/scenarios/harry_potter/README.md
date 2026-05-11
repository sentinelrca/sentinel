# Dumbledore's Army — SentinelAI Example Scenarios

Seven missions. Seven things that went wrong. Seven rules that caught them.

Dumbledore's Army (the DA) is SentinelAI's fictional multi-agent team — a group of
well-intentioned agents coordinating covert operations against Voldemort. Each scenario
is a mission that fails in a specific, diagnosable way. SentinelAI detects the failure
and tells you exactly what went wrong and why.

> **Disclaimer:** Harry Potter characters and the Wizarding World are the intellectual
> property of J.K. Rowling and Warner Bros. Entertainment Inc. These scenarios are
> fan-inspired educational illustrations created for a non-commercial open-source
> project. SentinelAI is not affiliated with or endorsed by the Harry Potter franchise.

---

## The Cast

| Agent | Role | Rule it demonstrates |
|---|---|---|
| **Hermione Granger** | Strategic planner / researcher | `agent_loop`, `sequential_tools` |
| **Harry Potter** | Mission executor / orchestrator | `agent_loop`, `retry_storm` |
| **Ron Weasley** | Field coordinator | `sequential_tools` |
| **Professor Trelawney** | Intelligence oracle (unreliable) | `retrieval_without_grounding` |
| **Dobby** | Eager but persistent helper | `retry_storm` |
| **Professor Snape** | Potions — slow, precise | `latency_spike` |
| **Neville Longbottom** | Session coordinator (forgetful) | `missing_session_memory` |
| **Fred & George** | Parallel executors (the right way) | contrast for `sequential_tools` |

## The Spells (tools)

| Spell | What it does | Maps to |
|---|---|---|
| `accio(query)` | Summon Ministry records | Retrieval / RAG |
| `alohomora(target)` | Unlock a door or seal | Authentication / API access |
| `owl_post(recipient, msg)` | Send a message | Async API call / webhook |
| `marauders_map(area)` | Check for figures in an area | Monitoring / lookup |
| `brew_potion(potion)` | Brew a potion (slow for complex ones) | Long-running computation |
| `wingardium_leviosa(target)` | Levitate supplies | Fast utility operation |
| `pensieve_store(key, memory)` | Store a memory for later | Session memory write |
| `pensieve_recall(key)` | Retrieve a stored memory | Session memory read |
| `expecto_patronum(threat)` | Defensive guardrail cast | Safety / content filter |

---

## The Missions

| # | File | Mission | Rule triggered |
|---|---|---|---|
| 01 | `01_agent_loop/da_war_council.py` | The DA War Council | `agent_loop` |
| 02 | `02_sequential_tools/two_owl_problem.py` | The Two-Owl Problem | `sequential_tools` |
| 03 | `03_retry_storm/dobbys_persistence.py` | Dobby's Persistence | `retry_storm` |
| 04 | `04_latency_spike/snapes_potion.py` | Snape's Potion | `latency_spike` |
| 05 | `05_retrieval_without_grounding/trelawneys_briefing.py` | Trelawney's Briefing | `retrieval_without_grounding` |
| 06 | `06_context_cache_opportunity/hermiones_homework.py` | Hermione's Homework | `context_cache_opportunity` |
| 07 | `07_missing_session_memory/nevilles_notes.py` | Neville's Notes | `missing_session_memory` |

---

## Quickstart

```bash
cd examples
cp .env.example .env          # fill in your model key + one backend
uv sync

# Run a single scenario
python scenarios/harry_potter/01_agent_loop/da_war_council.py

# Then verify the insight fired
sentinel analyze --source langfuse ...
```

See the top-level `examples/.env.example` for model and backend configuration.
