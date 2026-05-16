"""
Auto-discovers all clean-trace fixtures in this package.

To add a new fixture: create a new .py file (not starting with _) that defines
either a module-level FIXTURE: CleanTraceFixture or FIXTURES: list[CleanTraceFixture].
No other changes required — it will be picked up automatically.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from tests.fixtures.clean_traces._base import CleanTraceFixture

ALL: list[CleanTraceFixture] = []

for _mod_info in pkgutil.iter_modules([str(Path(__file__).parent)]):
    if _mod_info.name.startswith("_"):
        continue
    _mod = importlib.import_module(f"tests.fixtures.clean_traces.{_mod_info.name}")
    if hasattr(_mod, "FIXTURES"):
        ALL.extend(_mod.FIXTURES)
    elif hasattr(_mod, "FIXTURE"):
        ALL.append(_mod.FIXTURE)

__all__ = ["CleanTraceFixture", "ALL"]
