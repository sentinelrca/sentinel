# Scenario 03 — `retry_storm`: Dobby's Persistence

## What goes wrong

The Ministry records room is sealed with Dark Magic. Alohomora doesn't work on
Dark Magic seals — it's the wrong tool for the job. But Dobby keeps trying.

```
Attempt 1: "The door holds firm. The Dark Magic seal resists Alohomora."
Attempt 2: "Dobby is trying harder. The seal resists."
Attempt 3: "Dobby will not give up. The seal resists."
Attempt 4: "The door swings open."  ← only succeeded because the seal weakened
```

No backoff. No escalation. Just Dobby and the same spell, over and over.

## SentinelAI insight

**Detector:** `retry_storm`
**Severity:** HIGH
**Detection:** `alohomora` called 4 times within a single trace on the same target.
`retry_count >= 3` on a single span group.

## How to run

```bash
cd examples
python scenarios/harry_potter/03_retry_storm/dobbys_persistence.py
```

## The fix

After 2 failures with the same tool on the same target, the agent should:
1. **Escalate** — call Hermione, use a different spell, ask a human
2. **Backoff** — wait between attempts if retrying is appropriate
3. **Circuit break** — stop after N attempts and surface an error

In real systems: implement exponential backoff with jitter, set a max retry
limit, and surface a clear error when the limit is reached. Don't let the
agent keep hammering a permanently broken door.
