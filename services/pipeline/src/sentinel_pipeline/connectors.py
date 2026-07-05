"""Shared connector registry.

Maps a source ``kind`` string to its :class:`Connector` instance. Every code
path that needs to resolve a connector — the live sync task, the offline
project-import task, and the API's source-validation endpoint — goes through
``get_connector`` here, so a new connector is registered in exactly one place.

Imports are lazy (performed inside ``get_connector``) so that importing this
module does not pull in every connector package at load time, and so
``sentinel_pipeline`` carries no module-load dependency on the connectors that
depend on it.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel_connectors.base import Connector

# kind → (module path, class name). Add new connectors here only.
_CONNECTOR_SPECS: dict[str, tuple[str, str]] = {
    "langfuse": ("sentinel_connectors.langfuse", "LangfuseConnector"),
    "langsmith": ("sentinel_connectors.langsmith", "LangSmithConnector"),
    "arize_phoenix": ("sentinel_connectors.arize", "ArizePhoenixConnector"),
}

_INSTANCES: dict[str, "Connector"] = {}


def get_connector(kind: str) -> "Connector | None":
    """Return a cached connector instance for ``kind``, or ``None`` if unknown."""
    if kind not in _INSTANCES:
        spec = _CONNECTOR_SPECS.get(kind)
        if spec is None:
            return None
        module_name, class_name = spec
        module = importlib.import_module(module_name)
        _INSTANCES[kind] = getattr(module, class_name)()
    return _INSTANCES.get(kind)


def available_kinds() -> list[str]:
    """List the source kinds that have a registered connector."""
    return list(_CONNECTOR_SPECS)
