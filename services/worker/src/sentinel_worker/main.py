import os
from celery import Celery
from sentinel_pipeline.db.clickhouse import ensure_tables

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "sentinel_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "sentinel_worker.tasks.process_trace",
        "sentinel_worker.tasks.sync_source",
        "sentinel_worker.tasks.analyze_project",
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

# Ensure ClickHouse tables exist when the worker starts
ensure_tables()
