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
    raise ValueError(f"Unknown SENTINEL_BACKEND='{backend}'. Use: langfuse, langsmith")


def _configure_langfuse() -> ObservabilityConfig:
    _require("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    from langfuse.callback import CallbackHandler
    return ObservabilityConfig(
        backend="langfuse",
        callbacks=[CallbackHandler(
            host=os.environ["LANGFUSE_HOST"],
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        )],
    )


def _configure_langsmith() -> ObservabilityConfig:
    _require("LANGCHAIN_API_KEY")
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ.setdefault("LANGCHAIN_PROJECT", "sentinel-examples")
    return ObservabilityConfig(backend="langsmith", callbacks=[])


def _require(*keys: str) -> None:
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Missing env vars: {', '.join(missing)}. See .env.example"
        )
