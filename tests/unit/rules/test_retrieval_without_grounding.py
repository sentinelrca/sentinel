from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors.retrieval_without_grounding import RetrievalWithoutGroundingDetector

detector = RetrievalWithoutGroundingDetector()

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _retrieval(span_id, offset_ms=0, content=None):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    attrs = {}
    if content is not None:
        attrs["gen_ai.input"] = content
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.RETRIEVAL, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=300),
        workspace_id="ws1", attributes=attrs,
    )


def _llm(span_id, offset_ms=0, input_tokens=None, output_content=None):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    attrs = {}
    if output_content is not None:
        attrs["gen_ai.output"] = output_content
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=1000),
        workspace_id="ws1", input_tokens=input_tokens, output_tokens=50,
        attributes=attrs,
    )


def _tool(span_id, offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=200),
        workspace_id="ws1",
    )


def _tool_retrieve(span_id, name="similarity_search", offset_ms=0, content=None):
    """TOOL_INVOKE with a retrieval-like name — simulates OTel/ADK stacks."""
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    attrs = {}
    if content is not None:
        attrs["gen_ai.input"] = content
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=name, kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=300),
        workspace_id="ws1", attributes=attrs,
    )


# --- structural: no LLM after retrieval ---

def test_fires_when_no_llm_after_retrieval():
    """Retrieval span with no subsequent LLM call — definitive miss."""
    spans = [_retrieval("ret"), _tool("other_tool", offset_ms=400)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].detector_id == "retrieval_without_grounding"
    assert insights[0].evidence["detection_mode"] == "structural_no_llm_after_retrieval"
    assert "ret" in insights[0].affected_span_ids


def test_fires_when_llm_precedes_retrieval():
    """LLM call before retrieval, none after — retrieval result never consumed."""
    spans = [
        _llm("llm_early", offset_ms=0, input_tokens=1000),
        _retrieval("ret", offset_ms=1100),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].evidence["detection_mode"] == "structural_no_llm_after_retrieval"


# --- structural: no token growth ---

def test_fires_on_no_token_growth_after_retrieval():
    """LLM calls before and after retrieval with same token count — content not injected."""
    spans = [
        _llm("llm_before", offset_ms=0,    input_tokens=1000),
        _retrieval("ret",   offset_ms=1100),
        _llm("llm_after",  offset_ms=1500, input_tokens=1010),  # only 1% growth
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].evidence["detection_mode"] == "structural_no_token_growth"
    ev = insights[0].evidence
    assert ev["avg_tokens_before_retrieval"] == 1000
    assert ev["growth_ratio"] < 0.10


# --- structural: no fire ---

def test_no_fire_on_healthy_rag_token_growth():
    """LLM input tokens grow ≥10% after retrieval — content was injected."""
    spans = [
        _llm("llm_before", offset_ms=0,    input_tokens=1000),
        _retrieval("ret",   offset_ms=1100),
        _llm("llm_after",  offset_ms=1500, input_tokens=1200),  # 20% growth
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_no_fire_when_no_retrieval_spans():
    """Trace with no retrieval — skip entirely."""
    spans = [_llm("llm1", offset_ms=0, input_tokens=1000), _tool("t1", offset_ms=1100)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert detector.evaluate(graph, signals) is None


def test_no_fire_when_only_llm_after_retrieval_no_baseline():
    """Only LLM calls after retrieval (no baseline before) — can't assess growth."""
    spans = [
        _retrieval("ret",  offset_ms=0),
        _llm("llm_after", offset_ms=400, input_tokens=1000),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


# --- content mode ---

def test_fires_on_low_content_overlap():
    """Retrieved content shares <5% tokens with LLM response — grounding failure."""
    spans = [
        _retrieval("ret", offset_ms=0,
                   content="The refund policy allows returns within 30 days with receipt"),
        _llm("llm", offset_ms=400,
             output_content="I am unable to provide information about that topic"),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].severity.value == "high"
    assert insights[0].evidence["detection_mode"] == "content"
    assert insights[0].evidence["overlap_ratio"] < 0.05
    assert "ret" in insights[0].affected_span_ids
    assert "llm" in insights[0].affected_span_ids


def test_no_fire_on_high_content_overlap():
    """LLM response uses terms from retrieved content — properly grounded."""
    doc = "The refund policy allows returns within 30 days of purchase with a valid receipt"
    response = "According to the refund policy, returns are allowed within 30 days with a receipt"
    spans = [
        _retrieval("ret", offset_ms=0, content=doc),
        _llm("llm", offset_ms=400, output_content=response),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_content_mode_fires_high_severity():
    """Content mode always fires HIGH severity (definitive evidence)."""
    spans = [
        _retrieval("ret", offset_ms=0, content="quantum entanglement physics experiment"),
        _llm("llm", offset_ms=400, output_content="the weather today is sunny and warm"),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].severity.value == "high"


def test_structural_mode_fires_warning_severity():
    """Structural mode fires WARNING severity (heuristic evidence)."""
    spans = [_retrieval("ret"), _tool("t1", offset_ms=400)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].severity.value == "warning"


# --- OTel / name-pattern fallback ---

def test_fires_on_tool_invoke_with_retrieval_name():
    """TOOL_INVOKE named 'similarity_search' triggers the OTel fallback path."""
    spans = [
        _tool_retrieve("ret", name="similarity_search", offset_ms=0),
        _tool("other", offset_ms=400),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].evidence["detection_mode"] == "structural_no_llm_after_retrieval"


def test_fires_on_tool_invoke_named_retrieve():
    """TOOL_INVOKE named 'retrieve' also triggers the fallback."""
    spans = [_tool_retrieve("r1", name="retrieve", offset_ms=0)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert detector.evaluate(graph, signals)


def test_no_fire_on_unrelated_tool_invoke():
    """TOOL_INVOKE with non-retrieval name should not be treated as retrieval."""
    spans = [
        _tool("send_email", offset_ms=0),
        _llm("llm", offset_ms=400, input_tokens=1000),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)
