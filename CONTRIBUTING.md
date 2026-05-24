# Contributing to SentinelRCA

Thanks for your interest in contributing. SentinelRCA is an open-source AI agent reliability tool — contributions to connectors, detectors, bug fixes, and docs are all welcome.

---

## Quick start

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/sentinel.git
cd sentinel

# 2. Start infrastructure
task up   # requires Docker + go-task (brew install go-task)

# 3. Install test dependencies
cd tests && uv sync --no-install-project

# 4. Run unit tests (no Docker required)
uv run --no-project pytest unit/ -v

# 5. Create a branch and make your changes
git checkout -b feature/your-change

# 6. Push and open a PR against sentinelrca/sentinel main
```

---

## What to contribute

### Connectors (highest impact)

New connectors make Sentinel useful to more teams. A connector pulls traces from an observability source and normalizes them to `NormalizedSpan`.

Supported today: Langfuse, LangSmith.
Wanted: Arize Phoenix, LangWatch, Weave, OpenTelemetry/OTLP.

See [`connectors/langfuse/`](connectors/langfuse/) as the reference implementation and [`connectors/_base/`](connectors/_base/) for the `Connector` ABC.

Steps:
1. Create `connectors/<source>/` with its own `pyproject.toml`
2. Implement `Connector` ABC — `validate_config()` and `pull()`
3. Add a fixture trace at `tests/fixtures/<source>_sample.json`
4. Add unit tests at `tests/unit/connectors/test_<source>.py`

### Detectors

A detector is a deterministic pattern matched against a trace's flow graph. All detectors must work **without reading prompt content** — structure, timing, token counts, and span metadata only.

See [`services/pipeline/src/sentinel_pipeline/detectors/`](services/pipeline/src/sentinel_pipeline/detectors/) for existing detectors and the `Detector` ABC in `base.py`.

Steps:
1. Create `services/pipeline/src/sentinel_pipeline/detectors/<name>.py`
2. Implement `Detector` ABC — `id`, `name`, `severity`, `tier`, `evaluate()`
3. Register in `detectors/__init__.py` `DETECTOR_REGISTRY`
4. Add tests: at least one fixture that triggers the detector, one that must not

Before opening a PR for a new detector, open an issue using the **New Detector** template first. We want to agree on the failure pattern, thresholds, and FP risk before implementation.

### Bug fixes

Check [open issues](https://github.com/sentinelrca/sentinel/issues) labelled `bug`. Any bug fix is welcome — no prior discussion needed for clear bugs.

### Documentation

Fixes to `README.md`, `CLAUDE.md`, or code comments are always welcome.

---

## Guidelines

**Detectors must be deterministic.** The same trace must always produce the same result. No LLM inference, no randomness, no external API calls in detection logic.

**No content reading by default.** Detectors operate on span structure, timestamps, token counts, span kinds, and agent names — not on prompt text or LLM outputs. Content-based detectors require `store_content=True` and are explicitly marked as Pro tier.

**One detector per PR.** Keeps review focused and makes it easier to revert if a detector has a high false positive rate.

**Tests are required.** PRs without tests will not be merged. At minimum: one positive case (detector fires) and one negative case (detector does not fire on a clean trace).

**Thresholds need rationale.** If your detector fires on a threshold (e.g., ≥3 retries, >50% of trace duration), explain why in the PR description — cite a source, a practitioner report, or measured data.

---

## PR checklist

- [ ] Branch name: `feature/`, `fix/`, or `connector/` prefix
- [ ] Tests pass: `cd tests && uv run --no-project pytest unit/ -v`
- [ ] New detector registered in `DETECTOR_REGISTRY`
- [ ] New connector has a fixture trace and unit tests
- [ ] No prompt content read in detector logic
- [ ] PR description explains the failure pattern and threshold rationale

---

## Local development tips

```bash
task test          # run all unit tests
task lint          # ruff linter
task fmt           # auto-format
task up            # start Postgres + ClickHouse + Redis
task migrate       # run Postgres migrations
task logs:worker   # tail Celery worker logs
```

Each service has its own virtualenv managed by `uv`. No root-level venv.

```bash
cd services/pipeline && uv sync   # install pipeline deps
cd services/api     && uv sync   # install API deps
cd tests            && uv sync --no-install-project  # install test deps
```

---

## Questions?

Open a [GitHub Discussion](https://github.com/sentinelrca/sentinel/discussions) or file an issue. We respond to all genuine questions.
