"""Unit tests for the shared connector registry (sentinel_pipeline.connectors).

The registry is the single source of truth for which connectors exist and is
used by the API, the live sync task, and the offline project-import task.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_registry():
    """Return get_connector / available_kinds with a clean instance cache."""
    import importlib
    import sentinel_pipeline.connectors as mod
    # Clear cached instances so tests are independent
    mod._INSTANCES.clear()
    return mod.get_connector, mod.available_kinds


# ---------------------------------------------------------------------------
# available_kinds
# ---------------------------------------------------------------------------

def test_available_kinds_contains_all_registered():
    _, available_kinds = _fresh_registry()
    kinds = available_kinds()
    assert "langfuse"      in kinds
    assert "langsmith"     in kinds
    assert "arize_phoenix" in kinds


def test_available_kinds_does_not_contain_unknown():
    _, available_kinds = _fresh_registry()
    assert "langwatch" not in available_kinds()
    assert "openai"    not in available_kinds()


# ---------------------------------------------------------------------------
# get_connector — resolution
# ---------------------------------------------------------------------------

def test_get_connector_langfuse_returns_correct_type():
    get_connector, _ = _fresh_registry()
    from sentinel_connectors.langfuse import LangfuseConnector
    c = get_connector("langfuse")
    assert isinstance(c, LangfuseConnector)


def test_get_connector_langsmith_returns_correct_type():
    get_connector, _ = _fresh_registry()
    from sentinel_connectors.langsmith import LangSmithConnector
    c = get_connector("langsmith")
    assert isinstance(c, LangSmithConnector)


def test_get_connector_arize_returns_correct_type():
    get_connector, _ = _fresh_registry()
    from sentinel_connectors.arize import ArizePhoenixConnector
    c = get_connector("arize_phoenix")
    assert isinstance(c, ArizePhoenixConnector)


def test_get_connector_unknown_kind_returns_none():
    get_connector, _ = _fresh_registry()
    assert get_connector("bogus")    is None
    assert get_connector("")         is None
    assert get_connector("langwatch") is None


# ---------------------------------------------------------------------------
# get_connector — caching
# ---------------------------------------------------------------------------

def test_get_connector_returns_same_instance_on_repeated_calls():
    get_connector, _ = _fresh_registry()
    a = get_connector("langfuse")
    b = get_connector("langfuse")
    assert a is b, "Registry must return the same cached instance"


def test_get_connector_different_kinds_return_different_instances():
    get_connector, _ = _fresh_registry()
    langfuse   = get_connector("langfuse")
    langsmith  = get_connector("langsmith")
    arize      = get_connector("arize_phoenix")
    assert langfuse  is not langsmith
    assert langfuse  is not arize
    assert langsmith is not arize


# ---------------------------------------------------------------------------
# Connector contract — all registered connectors implement the ABC
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["langfuse", "langsmith", "arize_phoenix"])
def test_all_connectors_implement_required_methods(kind):
    get_connector, _ = _fresh_registry()
    c = get_connector(kind)
    assert c is not None
    assert callable(getattr(c, "validate_config",  None)), f"{kind} missing validate_config"
    assert callable(getattr(c, "pull",             None)), f"{kind} missing pull"
    assert callable(getattr(c, "pull_by_window",   None)), f"{kind} missing pull_by_window"
    assert callable(getattr(c, "pull_by_ids",      None)), f"{kind} missing pull_by_ids"


@pytest.mark.parametrize("kind", ["langfuse", "langsmith", "arize_phoenix"])
def test_all_connectors_declare_source_kind(kind):
    get_connector, _ = _fresh_registry()
    c = get_connector(kind)
    assert hasattr(c, "source_kind"), f"{kind} missing source_kind attribute"
    assert isinstance(c.source_kind, str) and c.source_kind, f"{kind}.source_kind must be non-empty"
