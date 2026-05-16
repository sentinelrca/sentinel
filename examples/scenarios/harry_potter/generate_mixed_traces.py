"""
Mixed trace generator — clean + rule-triggering traces.

Generates 22 Harry Potter traces in Langfuse:
  10 clean  (no rules fire)
   6 agent_loop  (same CHAIN node 3+ times with LLM children)
   6 sequential_tools  (sibling TOOL_INVOKE spans, >500ms saving)

All spans include realistic start/end timing via time.sleep() so the
timeline waterfall in Sentinel UI shows meaningful durations.

Usage:
    python generate_mixed_traces.py --all      # cleanup + generate
    python generate_mixed_traces.py --cleanup  # wipe Sentinel data only
    python generate_mixed_traces.py --generate # push traces only

After running, trigger a sync:
    cd services/worker && uv run python -c "
    import asyncio, sys; sys.path.insert(0,'src')
    from sentinel_worker.tasks.sync_source import _sync_source
    print(asyncio.run(_sync_source('<source_id>')))
    "
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[2]))
load_dotenv(Path(__file__).parents[2] / ".env")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_sentinel_data() -> None:
    import clickhouse_driver
    import psycopg2
    from urllib.parse import urlparse

    clickhouse_url = os.getenv("CLICKHOUSE_URL", "clickhouse://localhost:9000/sentinel")
    database_url   = os.getenv("DATABASE_URL", "postgresql://sentinel:sentinel@localhost:5432/sentinel")

    parsed = urlparse(clickhouse_url)
    ch = clickhouse_driver.Client(
        host=parsed.hostname or "localhost",
        port=parsed.port or 9000,
        database=parsed.path.lstrip("/") or "sentinel",
    )
    ch.execute("TRUNCATE TABLE IF EXISTS spans")
    print("✓ ClickHouse: spans table truncated")

    pg_dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(pg_dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM insights")
    cur.execute("UPDATE sources SET last_synced_at = NULL")
    cur.execute("SELECT COUNT(*) FROM sources")
    source_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    print(f"✓ Postgres: insights deleted, {source_count} source cursor(s) reset")


# ---------------------------------------------------------------------------
# Langfuse client
# ---------------------------------------------------------------------------

def _make_client():
    from langfuse import Langfuse
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "http://localhost:3000"
    return Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=host,
    ), host


# ---------------------------------------------------------------------------
# Clean trace patterns
# Sleeps give each span a realistic duration so the timeline is meaningful.
# ---------------------------------------------------------------------------

def _clean_hermione(lf, i: int) -> str:
    from langfuse.types import TraceContext
    topics = [
        "Animagus transformation requirements",
        "Counter-jinx for Petrificus Totalus",
        "History of the Philosopher's Stone",
        "Properties of Felix Felicis",
        "Origins of Parseltongue",
    ]
    topic = topics[i % len(topics)]
    trace_id = uuid.uuid4().hex
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="hermione_research", as_type="chain",
        input={"query": topic},
        metadata={"scenario": "clean"},
    )

    search = root.start_observation(name="accio_library", as_type="chain", input={"query": topic})
    time.sleep(0.28)
    search.update(output={"documents": [f"Ref-1: {topic}", f"Ref-2: {topic} — context"]})
    search.end()

    gen = root.start_observation(
        name="hermione_synthesise", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": f"Summarise: {topic}"}],
        usage_details={"input": 280, "output": 120},
    )
    time.sleep(0.32)
    gen.update(output=f"Based on the library records, {topic} involves...")
    gen.end()

    root.end()
    return trace_id


def _clean_harry(lf, i: int) -> str:
    from langfuse.types import TraceContext
    questions = [
        "Where is the Room of Requirement?",
        "What's the quickest route to the Quidditch pitch?",
        "Has Ron checked the common room?",
        "What time does the Hogwarts Express leave?",
        "Did Dobby deliver the message?",
    ]
    trace_id = uuid.uuid4().hex
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="harry_tactical_query", as_type="chain",
        input={"question": questions[i % len(questions)]},
        metadata={"scenario": "clean"},
    )
    gen = root.start_observation(
        name="harry_responds", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": questions[i % len(questions)]}],
        usage_details={"input": 90, "output": 60},
    )
    time.sleep(0.25)
    gen.update(output="Right, here's what I know...")
    gen.end()
    root.end()
    return trace_id


# ---------------------------------------------------------------------------
# Agent loop patterns
# Same CHAIN node name fires 3+ times, each with an LLM child.
# Sleeps give each iteration distinct timestamps.
# ---------------------------------------------------------------------------

def _loop_da_planning(lf, i: int) -> str:
    from langfuse.types import TraceContext
    missions = [
        "Plan the raid on the Department of Mysteries",
        "Coordinate the defence of Hogwarts",
        "Organise the search for Horcruxes",
        "Design the escape from Gringotts",
        "Prepare the ambush at the Astronomy Tower",
    ]
    mission = missions[i % len(missions)]
    trace_id = uuid.uuid4().hex
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="da_war_council", as_type="chain",
        input={"mission": mission},
        metadata={"scenario": "agent_loop"},
    )

    for turn in range(4):
        node = root.start_observation(
            name="hermione", as_type="chain",
            input={"turn": turn, "mission": mission},
        )
        gen = node.start_observation(
            name="hermione_thinks", as_type="generation",
            model="gpt-4o-mini",
            input=[{"role": "user", "content": f"Turn {turn}: assess {mission}"}],
            usage_details={"input": 200 + turn * 50, "output": 80},
        )
        time.sleep(0.18)
        gen.update(output=f"Turn {turn}: I need more information before proceeding.")
        gen.end()
        node.end()

    root.end()
    return trace_id


def _loop_quidditch_strategy(lf, i: int) -> str:
    from langfuse.types import TraceContext
    opponents = ["Slytherin", "Ravenclaw", "Hufflepuff", "Durmstrang", "Beauxbatons"]
    opponent = opponents[i % len(opponents)]
    trace_id = uuid.uuid4().hex
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="quidditch_prep", as_type="chain",
        input={"opponent": opponent},
        metadata={"scenario": "agent_loop"},
    )

    for turn in range(3):
        node = root.start_observation(
            name="harry", as_type="chain",
            input={"turn": turn, "opponent": opponent},
        )
        gen = node.start_observation(
            name="harry_strategises", as_type="generation",
            model="gpt-4o-mini",
            input=[{"role": "user", "content": f"Devise play vs {opponent}, turn {turn}"}],
            usage_details={"input": 150 + turn * 30, "output": 70},
        )
        time.sleep(0.20)
        gen.update(output=f"Turn {turn}: wait for better conditions.")
        gen.end()
        node.end()

    root.end()
    return trace_id


def _loop_order_meeting(lf, i: int) -> str:
    from langfuse.types import TraceContext
    threats = [
        "Voldemort's return to power",
        "Death Eater infiltration of the Ministry",
        "The prophecy leaking to the enemy",
        "Snape's double-agent status",
        "The Horcrux destruction timeline",
    ]
    threat = threats[i % len(threats)]
    trace_id = uuid.uuid4().hex
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="order_of_the_phoenix_meeting", as_type="chain",
        input={"threat": threat},
        metadata={"scenario": "agent_loop"},
    )

    for turn in range(3):
        node = root.start_observation(
            name="dumbledore", as_type="chain",
            input={"deliberation": turn},
        )
        gen = node.start_observation(
            name="dumbledore_weighs", as_type="generation",
            model="gpt-4o-mini",
            input=[{"role": "user", "content": f"Deliberate on {threat}, round {turn}"}],
            usage_details={"input": 300 + turn * 80, "output": 120},
        )
        time.sleep(0.22)
        gen.update(output=f"Round {turn}: the situation requires further analysis.")
        gen.end()
        node.end()

    root.end()
    return trace_id


# ---------------------------------------------------------------------------
# Sequential tools patterns
# Two sibling TOOL_INVOKE spans run back-to-back (no overlap, B > 500ms).
# ---------------------------------------------------------------------------

def _seq_library_research(lf, i: int) -> str:
    from langfuse.types import TraceContext
    topics = [
        "Dark Arts countermeasures",
        "Animagus registry records",
        "Goblin rebellion history",
        "Parseltongue translations",
        "Ancient rune interpretations",
    ]
    topic = topics[i % len(topics)]
    trace_id = uuid.uuid4().hex
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="library_research", as_type="chain",
        input={"topic": topic},
        metadata={"scenario": "sequential_tools"},
    )

    tool_a = root.start_observation(name="search_books", as_type="tool", input={"query": topic})
    time.sleep(0.62)
    tool_a.update(output={"results": [f"Book on {topic}", f"Reference for {topic}"]})
    tool_a.end()

    tool_b = root.start_observation(name="check_references", as_type="tool", input={"topic": topic})
    time.sleep(0.65)
    tool_b.update(output={"citations": [f"Citation 1 for {topic}", f"Citation 2 for {topic}"]})
    tool_b.end()

    gen = root.start_observation(
        name="synthesise", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": f"Summarise findings on {topic}"}],
        usage_details={"input": 300, "output": 150},
    )
    time.sleep(0.28)
    gen.update(output=f"Here is what I found about {topic}...")
    gen.end()

    root.end()
    return trace_id


def _seq_potion_prep(lf, i: int) -> str:
    from langfuse.types import TraceContext
    potions = [
        "Polyjuice Potion",
        "Veritaserum",
        "Amortentia",
        "Felix Felicis",
        "Wolfsbane Potion",
    ]
    potion = potions[i % len(potions)]
    trace_id = uuid.uuid4().hex
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="potion_preparation", as_type="chain",
        input={"potion": potion},
        metadata={"scenario": "sequential_tools"},
    )

    tool_a = root.start_observation(name="fetch_ingredients", as_type="tool", input={"potion": potion})
    time.sleep(0.61)
    tool_a.update(output={"ingredients": [f"Ingredient 1 for {potion}", f"Ingredient 2 for {potion}"]})
    tool_a.end()

    tool_b = root.start_observation(name="consult_recipe", as_type="tool", input={"potion": potion})
    time.sleep(0.68)
    tool_b.update(output={"steps": [f"Step 1 of {potion}", f"Step 2 of {potion}"]})
    tool_b.end()

    gen = root.start_observation(
        name="snape_instructs", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": f"How to brew {potion}?"}],
        usage_details={"input": 250, "output": 130},
    )
    time.sleep(0.26)
    gen.update(output=f"To brew {potion}, begin with...")
    gen.end()

    root.end()
    return trace_id


def _seq_quidditch_scouting(lf, i: int) -> str:
    from langfuse.types import TraceContext
    matches = ["vs Slytherin", "vs Ravenclaw", "vs Hufflepuff", "vs Durmstrang", "vs Beauxbatons"]
    match = matches[i % len(matches)]
    trace_id = uuid.uuid4().hex
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="quidditch_scouting", as_type="chain",
        input={"match": match},
        metadata={"scenario": "sequential_tools"},
    )

    tool_a = root.start_observation(name="check_weather", as_type="tool", input={"date": "match day"})
    time.sleep(0.60)
    tool_a.update(output={"conditions": "Partly cloudy, 12mph wind from the north"})
    tool_a.end()

    tool_b = root.start_observation(name="scout_opponent", as_type="tool", input={"opponent": match})
    time.sleep(0.67)
    tool_b.update(output={"strengths": "Fast Seeker", "weaknesses": "Slow Beaters"})
    tool_b.end()

    gen = root.start_observation(
        name="oliver_briefs", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": f"Prepare game plan {match}"}],
        usage_details={"input": 220, "output": 110},
    )
    time.sleep(0.24)
    gen.update(output=f"Game plan for {match}: exploit their weak Beaters...")
    gen.end()

    root.end()
    return trace_id


# ---------------------------------------------------------------------------
# Generation loop
# ---------------------------------------------------------------------------

CLEAN_PATTERNS = [_clean_hermione, _clean_harry]
LOOP_PATTERNS  = [_loop_da_planning, _loop_quidditch_strategy, _loop_order_meeting]
SEQ_PATTERNS   = [_seq_library_research, _seq_potion_prep, _seq_quidditch_scouting]


def generate_traces() -> None:
    client, host = _make_client()

    plan = [
        ("clean",            CLEAN_PATTERNS,  5),   # 5 reps × 2 patterns = 10 clean
        ("agent_loop",       LOOP_PATTERNS,   2),   # 2 reps × 3 patterns = 6 loop
        ("sequential_tools", SEQ_PATTERNS,    2),   # 2 reps × 3 patterns = 6 seq
    ]

    total = sum(reps * len(patterns) for _, patterns, reps in plan)
    print(f"Generating {total} mixed traces…\n")

    generated = 0
    for label, patterns, reps in plan:
        for fn in patterns:
            for i in range(reps):
                trace_id = fn(client, i)
                generated += 1
                print(f"  [{generated:2d}/{total}] {label}/{fn.__name__}[{i}]  trace_id={trace_id}")

    client.flush()
    print(f"\n✓ {generated} traces flushed to Langfuse at {host}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mixed Harry Potter traces")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cleanup",  action="store_true", help="Wipe Sentinel data only")
    group.add_argument("--generate", action="store_true", help="Generate traces only")
    group.add_argument("--all",      action="store_true", help="Cleanup then generate")
    args = parser.parse_args()

    if args.cleanup or args.all:
        print("=== Cleaning up Sentinel data ===")
        cleanup_sentinel_data()
        print()

    if args.generate or args.all:
        print("=== Generating mixed traces ===")
        generate_traces()


if __name__ == "__main__":
    main()
