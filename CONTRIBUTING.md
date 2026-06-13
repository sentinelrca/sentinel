# Contributing to SentinelRCA

Thanks for your interest. The two most common contributions are **connectors** (new observability sources) and **detectors** (new patterns to detect). Both are straightforward to add.

## Getting started

```bash
git clone https://github.com/sentinelrca/sentinel
cd sentinel/code/tests
uv sync --no-install-project
uv run --no-project pytest unit/ -v   # should be all green
```

---

## Adding a connector

A connector is a thin pull adapter that fetches spans from one observability source and maps them to `NormalizedSpan`.

### 1. Create the package

```
connectors/<source>/
├── pyproject.toml
└── src/sentinel_connectors/<source>.py
```

Copy `connectors/langsmith/` as a starting point — it's the simplest connector.

### 2. Implement the ABC

```python
from sentinel_connectors.base import Connector
from sentinel_pipeline.models.span import NormalizedSpan

class MyConnector(Connector):
    source_kind = "my_source"

    def validate_config(self, config: dict) -> bool:
        # hit a cheap endpoint to verify credentials
        ...

    def pull(self, config, since, workspace_id) -> Iterator[list[NormalizedSpan]]:
        # cursor-paginate spans newer than `since`
        ...

    def pull_by_window(self, config, since, until, workspace_id, limit=500):
        # bounded import: spans in [since, until]
        ...

    def pull_by_ids(self, config, trace_ids, workspace_id):
        # fetch specific traces by ID
        ...
```

### 3. Register it

Add to `services/pipeline/src/sentinel_pipeline/connectors.py`:

```python
_CONNECTOR_SPECS: dict[str, tuple[str, str]] = {
    ...
    "my_source": ("sentinel_connectors.my_source", "MyConnector"),
}
```

### 4. Add tests

```
tests/unit/connectors/test_<source>.py
```

Use `respx` to mock HTTP calls. See `tests/unit/connectors/test_arize.py` for a full example with 25 tests covering all three pull methods, pagination, error handling, and evidence quality.

### 5. Open a PR

Open an issue first to align on the interface — especially if the source has an unusual auth model or pagination scheme.

---

## Adding a detector

A detector takes a `FlowGraph` + `Signals` and returns a list of `Insight` objects (or `None`).

### 1. Create the file

```
services/pipeline/src/sentinel_pipeline/detectors/<detector_name>.py
```

### 2. Implement the ABC

```python
from sentinel_pipeline.detectors.base import Detector
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.signals.extractor import Signals

_MY_THRESHOLD = 3

class MyDetector(Detector):
    id       = "my_detector"
    name     = "My Detector"
    severity = Severity.WARNING
    tier     = Tier.FREE           # or Tier.STARTER / Tier.PRO

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not <condition>:
            return None

        return [Insight(
            workspace_id=graph.workspace_id,
            trace_id=graph.trace_id,
            detector_id=self.id,
            severity=self.severity,
            title="Short title shown in the UI",
            detail="Longer explanation of what was found and why it matters.",
            recommendation="Specific, actionable fix the developer can apply.",
            affected_span_ids=["sp-1", "sp-2"],
            evidence={"key": "value"},
        )]
```

### 3. Register it

Add to `DETECTOR_REGISTRY` in `services/pipeline/src/sentinel_pipeline/detectors/__init__.py`:

```python
from sentinel_pipeline.detectors.my_detector import MyDetector

DETECTOR_REGISTRY: list[Detector] = [
    ...
    MyDetector(),
]
```

### 4. Add tests

```
tests/unit/rules/test_<detector_name>.py
```

Write at least:
- One test that **triggers** the detector
- One test that **does not trigger** it (clean trace)
- Evidence key assertions

See `tests/unit/rules/test_retry_storm.py` for a thorough example.

---

## Code style

```bash
uv run ruff check services/ connectors/ tools/ tests/
uv run ruff format services/ connectors/ tools/ tests/
```

---

## Questions?

Open a [GitHub Discussion](https://github.com/sentinelrca/sentinel/discussions) before starting large changes.
