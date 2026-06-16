FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

# Install shared pipeline
COPY services/pipeline/pyproject.toml /deps/pipeline/pyproject.toml
COPY services/pipeline/src /deps/pipeline/src
RUN uv pip install --system -e /deps/pipeline

# Install connectors
COPY connectors/_base/pyproject.toml /deps/connectors-base/pyproject.toml
COPY connectors/_base/src /deps/connectors-base/src
RUN uv pip install --system -e /deps/connectors-base

COPY connectors/langfuse/pyproject.toml /deps/connectors-langfuse/pyproject.toml
COPY connectors/langfuse/src /deps/connectors-langfuse/src
RUN uv pip install --system -e /deps/connectors-langfuse

COPY connectors/langsmith/pyproject.toml /deps/connectors-langsmith/pyproject.toml
COPY connectors/langsmith/src /deps/connectors-langsmith/src
RUN uv pip install --system -e /deps/connectors-langsmith

COPY connectors/arize/pyproject.toml /deps/connectors-arize/pyproject.toml
COPY connectors/arize/src /deps/connectors-arize/src
RUN uv pip install --system -e /deps/connectors-arize

# Install API
COPY services/api/pyproject.toml .
COPY services/api/src src/
RUN uv pip install --system -e .

EXPOSE 8000
CMD ["uvicorn", "sentinel_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
