## What does this PR do?

<!-- One paragraph summary. Link to the issue if there is one. -->

Closes #

## Type of change

- [ ] Bug fix
- [ ] New connector
- [ ] New detector
- [ ] Enhancement to existing feature
- [ ] Documentation

## Checklist

- [ ] Tests pass locally: `cd tests && uv run --no-project pytest unit/ -v`
- [ ] New detector is registered in `DETECTOR_REGISTRY`
- [ ] New connector has a fixture trace and unit tests
- [ ] Detector does not read prompt content or LLM output (structure only)
- [ ] Threshold rationale documented in PR description or linked issue

## For new detectors — failure pattern & threshold rationale

<!-- What failure does this detect? Why these thresholds? What are the FP risks? -->
