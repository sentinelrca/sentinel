"""Rate-limit handling for Tinybird integration tests.

Tinybird free tier: 1,000 requests/day. Running 19 tests × ~5 calls
= ~95 calls per suite run. A 2-second pause between tests prevents
burst rate-limiting on the free tier.

Note: delete tests use _wait_for_deletion() (35s) instead of
_wait_for_ingestion() because Tinybird Cloud delete Jobs take ~30s.
"""
import time
import pytest


@pytest.fixture(autouse=True)
def _inter_test_pause(request):
    """2-second pause before each Tinybird integration test to avoid rate limits."""
    if "tinybird" in request.node.fspath.basename:
        time.sleep(2)
    yield
