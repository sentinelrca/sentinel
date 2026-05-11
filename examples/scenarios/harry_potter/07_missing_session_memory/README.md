# Scenario 07 — `missing_session_memory`: Neville's Notes

## What goes wrong

The DA runs a 3-turn strategy session. Neville coordinates.
The Pensieve sits unused on the shelf the entire time.

Harry explains the full horcrux situation at the start of every turn
because Neville has no memory of the previous one.

```
Turn 1: Harry explains all 7 horcruxes (500 tokens). Neville asks a question.
Turn 2: Harry explains all 7 horcruxes again (+500 tokens). Neville asks again.
Turn 3: Harry explains all 7 horcruxes again (+500 tokens). Neville asks again.
```

*"It's like Neville got hit with an Obliviate between every meeting."*

Token cost: ~1,500. Without missing memory: ~600.
Time wasted: Harry re-briefing instead of planning.

## SentinelAI insight

**Rule:** `missing_session_memory`
**Severity:** MEDIUM
**Detection:** 3 LLM_CALL turns in the same trace. Input tokens grew >50% from
turn 1 to turn 3. No `pensieve_store` or `pensieve_recall` calls anywhere in the trace.

## How to run

```bash
cd examples
python scenarios/harry_potter/07_missing_session_memory/nevilles_notes.py
```

## The fix

At the end of turn 1, store what was decided:
```python
pensieve_store.invoke({"key": "horcrux_status", "memory": summary_of_turn_1})
```

At the start of turns 2 and 3, recall it:
```python
context = pensieve_recall.invoke({"key": "horcrux_status"})
```

Harry can then say "continuing from last session" instead of re-explaining
7 horcruxes from scratch. The Pensieve exists for a reason.

In real systems: use a session memory store (Redis, Zep, LangMem) and write
a summary after each turn. Never make the user re-explain what they already told you.
