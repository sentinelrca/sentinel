FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY services/pipeline/pyproject.toml /deps/pipeline/pyproject.toml
COPY services/pipeline/src /deps/pipeline/src
RUN uv pip install --system -e /deps/pipeline

COPY services/api/pyproject.toml .
COPY services/api/src src/
RUN uv pip install --system -e .

EXPOSE 8000
CMD ["uvicorn", "sentinel_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
