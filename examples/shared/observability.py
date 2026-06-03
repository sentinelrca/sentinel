import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ObservabilityConfig:
    backend: str
    callbacks: list[Any] = field(default_factory=list)


def configure() -> ObservabilityConfig:
    backend = os.getenv("SENTINEL_BACKEND", "langfuse").lower()
    if backend == "langfuse":
        return _configure_langfuse()
    if backend == "langsmith":
        return _configure_langsmith()
    if backend == "arize_phoenix":
        return _configure_arize_phoenix()
    raise ValueError(f"Unknown SENTINEL_BACKEND='{backend}'. Use: langfuse, langsmith, arize_phoenix")


def _configure_langfuse() -> ObservabilityConfig:
    _require("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    # Langfuse v4: CallbackHandler reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY,
    # and LANGFUSE_BASE_URL (or LANGFUSE_HOST) directly from the environment.
    from langfuse.langchain import CallbackHandler
    return ObservabilityConfig(
        backend="langfuse",
        callbacks=[CallbackHandler()],
    )


def _configure_langsmith() -> ObservabilityConfig:
    _require("LANGCHAIN_API_KEY")
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ.setdefault("LANGCHAIN_PROJECT", "sentinel-examples")
    return ObservabilityConfig(backend="langsmith", callbacks=[])


def _configure_arize_phoenix() -> ObservabilityConfig:
    _require("PHOENIX_HOST")
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from openinference.instrumentation.langchain import LangChainInstrumentor

    host    = os.environ["PHOENIX_HOST"].rstrip("/")
    api_key = os.getenv("PHOENIX_API_KEY", "")
    project = os.getenv("PHOENIX_PROJECT_NAME", "default")

    headers: dict = {"project-name": project}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Phoenix Cloud OTLP endpoint lives under the same space path as the REST API
    exporter = OTLPSpanExporter(
        endpoint=f"{host}/v1/traces",
        headers=headers,
    )
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    LangChainInstrumentor().instrument(tracer_provider=provider)

    # Ensure spans are exported before the process exits (short-lived scripts)
    import atexit
    atexit.register(provider.force_flush)
    atexit.register(provider.shutdown)

    return ObservabilityConfig(backend="arize_phoenix", callbacks=[])


def _require(*keys: str) -> None:
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Missing env vars: {', '.join(missing)}. See .env.example"
        )
