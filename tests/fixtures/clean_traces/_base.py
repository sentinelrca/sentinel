"""Base type for clean-trace fixtures."""
from __future__ import annotations

from dataclasses import dataclass, field

from sentinel_pipeline.models.span import NormalizedSpan


@dataclass
class CleanTraceFixture:
    label: str
    description: str
    spans: list[NormalizedSpan]
    # Rule IDs that currently fire on this fixture but are documented as known
    # limitations — not test failures.  Remove entries here as rules improve.
    known_false_positives: list[str] = field(default_factory=list)
