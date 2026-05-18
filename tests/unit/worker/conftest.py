# Ensure worker task modules are importable without a live Celery/ClickHouse connection.
# sentinel_worker.main no longer calls ensure_tables() at import time (it's deferred to
# the worker_ready signal), so these imports are safe in unit tests.
import sentinel_worker.tasks.import_project_traces  # noqa: F401
import sentinel_worker.tasks.analyze_project  # noqa: F401
import sentinel_worker.tasks.sync_source  # noqa: F401
