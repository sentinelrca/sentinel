FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

# Install shared pipeline dependency first (better layer caching)
COPY services/pipeline/pyproject.toml /deps/pipeline/pyproject.toml
COPY services/pipeline/src /deps/pipeline/src
RUN uv pip install --system -e /deps/pipeline

COPY services/ingestor/pyproject.toml .
COPY services/ingestor/src src/
RUN uv pip install --system -e .

EXPOSE 8001
CMD ["uvicorn", "sentinel_ingestor.main:app", "--host", "0.0.0.0", "--port", "8001"]
