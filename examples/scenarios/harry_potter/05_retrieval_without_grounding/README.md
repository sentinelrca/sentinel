# Scenario 05 — `retrieval_without_grounding`: Trelawney's Briefing

## What goes wrong

The DA casts Accio to retrieve Ministry surveillance records on the Death Eater hideout.
The records are sealed under the Fidelius Charm.

```
Accio result: []
```

Professor Trelawney is invoked anyway. She has zero retrieved documents.
She delivers a full, confident intelligence briefing — entry points, occupant count,
Voldemort's schedule — entirely from her "Inner Eye."

This is hallucination in production. The LLM produced specific, actionable,
completely fabricated intelligence. The DA could get killed acting on it.

## SentinelAI insight

**Detector:** `retrieval_without_grounding`
**Severity:** CRITICAL
**Detection:** `accio` (RETRIEVAL span) returned `[]`. The LLM_CALL span that follows
still produced a non-empty response with no retrieved context to draw from.

## How to run

```bash
cd examples
python scenarios/harry_potter/05_retrieval_without_grounding/trelawneys_briefing.py
```

## The fix

Gate the LLM call on retrieval success:

```python
if not retrieved or retrieved == "[]":
    return "Insufficient intelligence. Cannot brief without verified records."

# Only reach here if retrieval returned something
briefing = chain.invoke({"records": retrieved})
```

Or constrain the system prompt explicitly:
> "If the retrieved records are empty, respond only with: 'No records found.
> Do not speculate or use prior knowledge.'"

Trelawney should never have been consulted without evidence in hand.
That's not mysticism — it's a missing guard clause.
