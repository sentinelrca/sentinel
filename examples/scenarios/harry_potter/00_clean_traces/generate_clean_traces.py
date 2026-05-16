"""
Scenario 00 — Clean Traces: "A Quiet Day at Hogwarts"

Generates 50 clean Harry Potter traces in Langfuse — no rules should fire.
Used to validate the "No issues detected" state in the Sentinel UI.

Usage:
    # Full run: wipe Sentinel data, generate clean traces
    python generate_clean_traces.py --all

    # Just wipe Sentinel data (ClickHouse spans + Postgres insights + reset cursor)
    python generate_clean_traces.py --cleanup

    # Just generate traces in Langfuse (no cleanup)
    python generate_clean_traces.py --generate

After running, trigger a sync:
    cd services/worker && uv run celery -A sentinel_worker.main call \\
        sentinel_worker.tasks.sync_source.sync_all_sources

Why each trace is clean (no rules fire with current REGISTRY):
    agent_loop:       No chain/agent node name appears 3+ times with LLM children.
    sequential_tools: No sibling TOOL_INVOKE spans — all container spans are 'chain' type.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[3]))
load_dotenv(Path(__file__).parents[3] / ".env")


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
# Trace patterns
# ---------------------------------------------------------------------------

def _pattern_hermione_research(lf, i: int) -> str:
    """
    Hermione searches the library and synthesises an answer.
    root chain → accio_library chain → hermione_synthesise generation
    """
    from langfuse.types import TraceContext
    trace_id = uuid.uuid4().hex
    topics = [
        "Animagus transformation requirements",
        "Counter-jinx for Petrificus Totalus",
        "History of the Philosopher's Stone",
        "Precautions for Polyjuice Potion",
        "Defensive charms against Dementors",
        "Properties of Felix Felicis",
        "Origins of Parseltongue",
        "Rules of the Triwizard Tournament",
        "Classification of magical creatures",
        "Ministry of Magic organisational structure",
    ]
    topic = topics[i % len(topics)]
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="hermione_research", as_type="chain",
        input={"query": topic},
        metadata={"scenario": "clean", "pattern": "hermione_research"},
    )
    search = root.start_observation(
        name="accio_library", as_type="chain",
        input={"query": topic},
    )
    search.update(output={"documents": [
        f"Ref-1: {topic} — primary source",
        f"Ref-2: {topic} — historical context",
    ]})
    search.end()

    gen = root.start_observation(
        name="hermione_synthesise", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": f"Summarise: {topic}"}],
        usage_details={"input": 280, "output": 120},
    )
    gen.update(output=f"Based on the library records, {topic} involves the following key points...")
    gen.end()

    root.end()
    return trace_id


def _pattern_harry_direct(lf, i: int) -> str:
    """
    Harry answers a tactical question directly.
    root chain → harry_responds generation
    """
    from langfuse.types import TraceContext
    trace_id = uuid.uuid4().hex
    questions = [
        "Where is the Room of Requirement?",
        "What's the quickest route to the Quidditch pitch?",
        "How many points is Gryffindor ahead by?",
        "When does Dumbledore's Army meet next?",
        "Who's on broom patrol tonight?",
        "Is the Marauder's Map showing anyone in the corridor?",
        "Which spell would stop a Blast-Ended Skrewt?",
        "Has Ron checked the common room?",
        "What time does the Hogwarts Express leave?",
        "Did Dobby deliver the message?",
    ]
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="harry_tactical_query", as_type="chain",
        input={"question": questions[i % len(questions)]},
        metadata={"scenario": "clean", "pattern": "harry_direct"},
    )
    gen = root.start_observation(
        name="harry_responds", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": questions[i % len(questions)]}],
        usage_details={"input": 90, "output": 60},
    )
    gen.update(output="Right, here's what I know...")
    gen.end()
    root.end()
    return trace_id


def _pattern_dumbledore_delegates(lf, i: int) -> str:
    """
    Dumbledore assesses, delegates once to McGonagall who responds.
    Two agents each appearing exactly once — well below agent_loop threshold.
    """
    from langfuse.types import TraceContext
    trace_id = uuid.uuid4().hex
    tasks = [
        "Arrange the Sorting Ceremony",
        "Review Hogsmeade permission slips",
        "Inspect the Astronomy Tower",
        "Update the house point totals",
        "Schedule the Quidditch fixture list",
        "Check on the third-floor corridor",
        "Review Defence Against the Dark Arts curriculum",
        "Confirm the arrival of the Beauxbatons delegation",
        "Update the wards around the castle",
        "Prepare the Great Hall for the end-of-year feast",
    ]
    task = tasks[i % len(tasks)]
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="dumbledore_oversight", as_type="chain",
        input={"directive": task},
        metadata={"scenario": "clean", "pattern": "dumbledore_delegates",
                  "agent_name": "Dumbledore"},
    )
    d_gen = root.start_observation(
        name="dumbledore_assess", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": f"Assess priority: {task}"}],
        usage_details={"input": 120, "output": 80},
        metadata={"agent_name": "Dumbledore"},
    )
    d_gen.update(output="This is a priority-two matter. I'll delegate to McGonagall.")
    d_gen.end()

    mc = root.start_observation(
        name="mcgonagall_execute", as_type="chain",
        input={"task": task},
        metadata={"agent_name": "McGonagall"},
    )
    mc_gen = mc.start_observation(
        name="mcgonagall_respond", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": f"Execute: {task}"}],
        usage_details={"input": 150, "output": 100},
        metadata={"agent_name": "McGonagall"},
    )
    mc_gen.update(output=f"Understood, Headmaster. I will handle: {task}.")
    mc_gen.end()
    mc.end()
    root.end()
    return trace_id


def _pattern_dobby_task(lf, i: int) -> str:
    """
    Dobby performs a single household task and confirms.
    root chain → dobby_do_task chain → dobby_confirm generation
    """
    from langfuse.types import TraceContext
    trace_id = uuid.uuid4().hex
    chores = [
        "Polish the Gryffindor common room fireplace",
        "Deliver breakfast to the Hospital Wing",
        "Mend Harry's Quidditch robes",
        "Stock the Room of Requirement with supplies",
        "Clean the Prefects' bathroom",
        "Fold the House elves' tea towels",
        "Carry Professor Sprout's seedling trays",
        "Deliver a sock to the laundry room",
        "Set the table in the Great Hall",
        "Refill the cauldrons in Potions",
    ]
    chore = chores[i % len(chores)]
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="dobby_chore", as_type="chain",
        input={"task": chore},
        metadata={"scenario": "clean", "pattern": "dobby_task"},
    )
    step = root.start_observation(name="dobby_do_task", as_type="chain", input={"chore": chore})
    step.update(output={"result": f"{chore} — done!"})
    step.end()

    gen = root.start_observation(
        name="dobby_confirm", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": f"Confirm: {chore}"}],
        usage_details={"input": 80, "output": 40},
    )
    gen.update(output="Dobby has completed the task, sir! Dobby is pleased.")
    gen.end()
    root.end()
    return trace_id


def _pattern_ron_owl(lf, i: int) -> str:
    """
    Ron composes an owl post message — single LLM call.
    root chain → ron_compose generation
    """
    from langfuse.types import TraceContext
    trace_id = uuid.uuid4().hex
    recipients = [
        ("Mum", "Requesting more Chocolate Frogs"),
        ("Fred", "Quidditch tactics for Saturday"),
        ("George", "Missing Extendable Ears — please send"),
        ("Percy", "Can you lend me your Transfiguration notes?"),
        ("Ginny", "Don't forget Quidditch practice is moved"),
        ("Hermione", "What time is the Hogwarts Express?"),
        ("Harry", "The password changed to Caput Draconis"),
        ("Neville", "Found your Remembrall near the greenhouses"),
        ("Luna", "You left your Quibbler in the common room"),
        ("Seamus", "Chess match tomorrow after dinner?"),
    ]
    recipient, subject = recipients[i % len(recipients)]
    ctx = TraceContext(trace_id=trace_id)

    root = lf.start_observation(
        trace_context=ctx, name="ron_owl_post", as_type="chain",
        input={"to": recipient, "subject": subject},
        metadata={"scenario": "clean", "pattern": "ron_owl"},
    )
    gen = root.start_observation(
        name="ron_compose", as_type="generation",
        model="gpt-4o-mini",
        input=[{"role": "user", "content": f"Write a short owl post to {recipient} about: {subject}"}],
        usage_details={"input": 110, "output": 90},
    )
    gen.update(output=f"Dear {recipient}, {subject}. Cheers, Ron")
    gen.end()
    root.end()
    return trace_id


# ---------------------------------------------------------------------------
# Generation loop
# ---------------------------------------------------------------------------

PATTERNS = [
    _pattern_hermione_research,
    _pattern_harry_direct,
    _pattern_dumbledore_delegates,
    _pattern_dobby_task,
    _pattern_ron_owl,
]
TRACES_PER_PATTERN = 10


def generate_traces() -> None:
    from langfuse import Langfuse

    host = (
        os.getenv("LANGFUSE_HOST")
        or os.getenv("LANGFUSE_BASE_URL")
        or "http://localhost:3000"
    )
    lf = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=host,
    )

    total = len(PATTERNS) * TRACES_PER_PATTERN
    print(f"Generating {total} clean traces ({len(PATTERNS)} patterns × {TRACES_PER_PATTERN})…\n")

    generated = 0
    for pattern_fn in PATTERNS:
        name = pattern_fn.__name__.replace("_pattern_", "")
        for i in range(TRACES_PER_PATTERN):
            trace_id = pattern_fn(lf, i)
            generated += 1
            print(f"  [{generated:2d}/{total}] {name}[{i}]  trace_id={trace_id}")

    lf.flush()
    print(f"\n✓ {generated} traces flushed to Langfuse at {host}")
    print("\nNext: trigger a Sentinel sync to pull them in.")
    print("  cd services/worker && uv run celery -A sentinel_worker.main call \\")
    print("    sentinel_worker.tasks.sync_source.sync_all_sources")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate clean Harry Potter traces")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cleanup",  action="store_true",
                       help="Wipe Sentinel data only (ClickHouse + Postgres)")
    group.add_argument("--generate", action="store_true",
                       help="Generate 50 clean traces in Langfuse only")
    group.add_argument("--all",      action="store_true",
                       help="Cleanup first, then generate")
    args = parser.parse_args()

    if args.cleanup or args.all:
        print("=== Cleaning up Sentinel data ===")
        cleanup_sentinel_data()
        print()

    if args.generate or args.all:
        print("=== Generating clean traces ===")
        generate_traces()


if __name__ == "__main__":
    main()
