# Scenario 06 — `context_cache_opportunity`: Hermione's Homework

## What goes wrong

The DA runs a 3-turn planning session. Every turn, the agent prepends the full
static context to the LLM request — even when the question is "7pm or 8pm?"

| Turn | Static context | Question | Total |
|---|---|---|---|
| 1 | ~1,200 tokens | ~15 tokens | ~1,215 tokens |
| 2 | ~1,200 tokens (same) | ~12 tokens | ~1,212 tokens |
| 3 | ~1,200 tokens (same) | ~18 tokens | ~1,218 tokens |

3,636 tokens billed. 3,600 of them were identical bytes sent three times.

*"Harry, why are you re-reading Hogwarts: A History before asking what time dinner is?"*

## SentinelAI insight

**Detector:** `context_cache_opportunity`
**Severity:** MEDIUM
**Detection:** Consecutive LLM_CALL spans in the same trace with growing input_tokens
where the token delta per turn is smaller than the static prefix size — indicating
the static portion is being re-sent rather than a genuinely growing conversation.

## How to run

```bash
cd examples
python scenarios/harry_potter/06_context_cache_opportunity/hermiones_homework.py
```

## The fix

**Option A — Provider prompt caching** (Anthropic / OpenAI):
Mark the static system message with `cache_control: {"type": "ephemeral"}`.
The provider caches the KV state; subsequent calls pay only for new tokens.

**Option B — Restructure the prompt**:
Send the static context once in the initial system message, then pass
only the evolving conversation in follow-up turns.

**Option C — Summarise and compress**:
If the static context changes slowly, maintain a compressed summary
rather than the full verbatim text.

Hermione would never re-read the same chapter before answering each question.
Your agent shouldn't either.
