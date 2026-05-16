"""
False-positive regression suite.

Runs every rule in REGISTRY against every fixture in fixtures/clean_traces/.
A test passes only when no *unexpected* rule fires.

Adding a new clean scenario: drop a new .py file in tests/fixtures/clean_traces/
with a module-level FIXTURE or FIXTURES variable — no changes needed here.

Documenting a known false positive: add the rule_id to the fixture's
known_false_positives list.  Remove the entry once the rule is improved.
"""
from __future__ import annotations

import warnings

import pytest

from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.rules import REGISTRY
from sentinel_pipeline.signals.extractor import extract_signals
from tests.fixtures.clean_traces import ALL, CleanTraceFixture


def _ids(fixtures: list[CleanTraceFixture]) -> list[str]:
    return [f.label for f in fixtures]


@pytest.mark.parametrize("fixture", ALL, ids=_ids(ALL))
def test_no_unexpected_rule_fires(fixture: CleanTraceFixture) -> None:
    graph = build_graph(fixture.spans)
    signals = extract_signals(graph)

    fired = list(dict.fromkeys(
        rule.id
        for rule in REGISTRY
        if rule.evaluate(graph, signals)
    ))

    unexpected = [r for r in fired if r not in fixture.known_false_positives]
    assert unexpected == [], (
        f"Clean trace '{fixture.label}' triggered unexpected rules: {unexpected}\n"
        f"  Description: {fixture.description}\n"
        f"  If intentional, add to known_false_positives in the fixture file."
    )

    # Surface stale known_false_positives so they get cleaned up — rule improved.
    resolved = [r for r in fixture.known_false_positives if r not in fired]
    if resolved:
        warnings.warn(
            f"[{fixture.label}] known_false_positives no longer fire: {resolved} "
            f"— remove them from the fixture.",
            stacklevel=1,
        )
