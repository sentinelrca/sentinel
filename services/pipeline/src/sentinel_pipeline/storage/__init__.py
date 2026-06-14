"""Storage backend factory.

Select backend via SENTINEL_STORAGE_BACKEND env var:
  clickhouse  (default) — self-hosted Docker / on-prem
  tinybird              — hosted SaaS (Tinybird free tier)

Usage:
    from sentinel_pipeline.storage import get_span_store
    store = get_span_store()
    store.insert_spans(spans)
"""
from __future__ import annotations

import os

from sentinel_pipeline.storage.base import SpanStore

_instance: SpanStore | None = None
# Note: the singleton is not protected by a threading.Lock. This is safe under
# Celery's default prefork pool (each worker process has its own memory space).
# Under threaded pools (gevent/eventlet), two tasks could both see _instance is
# None and each construct a backend object. The worst outcome is two identical,
# stateless instances being created briefly — not a correctness failure. If a
# threaded pool is ever used in production, add a Lock here.


def get_span_store() -> SpanStore:
    """Return a cached SpanStore instance for the configured backend."""
    global _instance
    if _instance is None:
        backend = os.environ.get("SENTINEL_STORAGE_BACKEND", "clickhouse").lower()
        if backend == "tinybird":
            from sentinel_pipeline.storage.tinybird import TinybirdSpanStore
            _instance = TinybirdSpanStore()
        elif backend == "clickhouse":
            from sentinel_pipeline.storage.clickhouse import ClickHouseSpanStore
            _instance = ClickHouseSpanStore()
        else:
            raise ValueError(
                f"Unknown SENTINEL_STORAGE_BACKEND='{backend}'. "
                "Valid values: clickhouse, tinybird"
            )
    return _instance


def reset_span_store() -> None:
    """Clear the cached instance — for use in tests only."""
    global _instance
    _instance = None


__all__ = ["SpanStore", "get_span_store", "reset_span_store"]
