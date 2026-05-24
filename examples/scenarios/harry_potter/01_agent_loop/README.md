# Scenario 01 — `agent_loop`: The DA War Council

## What goes wrong

Hermione won't write the mission plan without a threat assessment.
Harry won't do the threat assessment without a mission plan.

They hand off to each other six times. The raid never happens.

```
HermioneAgent: "I cannot finalise the plan without a threat assessment. Harry, assess the threat."
HarryAgent:    "I cannot assess the threat without a mission plan. Hermione, write the plan."
HermioneAgent: "I cannot finalise the plan without a threat assessment. Harry, assess the threat."
...
```

## SentinelAI insight

**Detector:** `agent_loop`
**Severity:** HIGH
**Detection:** `hermione_planner` and `harry_tactical` appear alternately in the flow graph,
forming a cycle with no terminal node reached within the trace.

## How to run

```bash
cd examples
python scenarios/harry_potter/01_agent_loop/da_war_council.py
```

## The fix

Break the circular dependency at design time. One agent must own the first step
unconditionally. In practice: Hermione drafts a *preliminary* plan with assumptions
clearly marked; Harry then produces the threat assessment; Hermione finalises.
No agent should refuse to start without input that only another agent can provide.
