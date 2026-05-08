FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY services/pipeline/pyproject.toml /deps/pipeline/pyproject.toml
COPY services/pipeline/src /deps/pipeline/src
RUN uv pip install --system -e /deps/pipeline

COPY connectors/_base/pyproject.toml /deps/connectors-base/pyproject.toml
COPY connectors/_base/src /deps/connectors-base/src
RUN uv pip install --system -e /deps/connectors-base

COPY connectors/langfuse/pyproject.toml /deps/connectors-langfuse/pyproject.toml
COPY connectors/langfuse/src /deps/connectors-langfuse/src
RUN uv pip install --system -e /deps/connectors-langfuse

COPY services/worker/pyproject.toml .
COPY services/worker/src src/
RUN uv pip install --system -e .

CMD ["celery", "-A", "sentinel_worker.main", "worker", "--loglevel=info", "--concurrency=4"]
