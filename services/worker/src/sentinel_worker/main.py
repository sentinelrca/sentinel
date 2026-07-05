import os
from celery import Celery
from celery.signals import worker_ready

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "sentinel_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "sentinel_worker.tasks.process_trace",
        "sentinel_worker.tasks.sync_source",
        "sentinel_worker.tasks.analyze_project",
        "sentinel_worker.tasks.import_project_traces",
    ],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@worker_ready.connect
def _on_worker_ready(**_kwargs):
    """Create ClickHouse tables when the worker process is fully started."""
    from sentinel_pipeline.db.clickhouse import ensure_tables

    ensure_tables()
