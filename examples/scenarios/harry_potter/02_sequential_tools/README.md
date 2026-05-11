# Scenario 02 — `sequential_tools`: The Two-Owl Problem

## What goes wrong

Ron needs to do two completely independent things:
1. Check the Marauder's Map
2. Send an owl to Dumbledore

He does them one at a time. Map first, owl second. The owl sits waiting while
Ron stares at the map, even though it could have been flying already.

Fred and George, watching from across the room: *"He sent them one at a time, George."*
*"Tragic, Fred."*

## SentinelAI insight

**Rule:** `sequential_tools`
**Severity:** MEDIUM
**Detection:** `marauders_map` and `owl_post` both appear under the same parent span
(`ron_coordinator`) with non-overlapping timestamps and no data flowing from one to the other.

## How to run

```bash
cd examples
python scenarios/harry_potter/02_sequential_tools/two_owl_problem.py
```

## The fix

Independent tools should run in parallel. In LangGraph, use a fan-out pattern:

```python
# Fan out to both tools simultaneously
graph.add_edge("coordinator", "check_map")
graph.add_edge("coordinator", "send_owl")
# Fan back in
graph.add_edge("check_map", "collector")
graph.add_edge("send_owl", "collector")
```

Or use an async agent that can call tools concurrently. Fred and George always
send their owls together. That's the pattern to follow.
