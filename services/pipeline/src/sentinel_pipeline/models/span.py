from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SpanKind(str, Enum):
    LLM_CALL     = "llm_call"
    TOOL_INVOKE  = "tool_invoke"
    AGENT_INVOKE = "agent_invoke"
    RETRIEVAL    = "retrieval"
    CHAIN        = "chain"
    HANDOFF      = "handoff"
    GENERIC      = "generic"


class SpanStatus(str, Enum):
    OK      = "ok"
    ERROR   = "error"
    TIMEOUT = "timeout"


class EdgeKind(str, Enum):
    PARENT_CHILD   = "parent_child"
    AGENT_HANDOFF  = "agent_handoff"
    RETRY          = "retry"


class NormalizedSpan(BaseModel):
    span_id:        str
    trace_id:       str
    parent_span_id: str | None = None
    name:           str
    kind:           SpanKind   = SpanKind.GENERIC
    status:         SpanStatus = SpanStatus.OK
    start_time:     datetime
    end_time:       datetime
    workspace_id:   str

    # Extracted gen_ai.* fields — None when absent in source
    model:         str | None  = None
    agent_name:    str | None  = None
    input_tokens:  int | None  = None
    output_tokens: int | None  = None
    retry_count:   int         = 0
    error_message: str | None  = None

    # All source attributes preserved verbatim — never drop unknown keys
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def end_after_start(self) -> NormalizedSpan:
        if self.end_time < self.start_time:
            # Swap — malformed span, but don't raise; log at caller
            self.end_time, self.start_time = self.start_time, self.end_time
        return self

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time).total_seconds() * 1000

    def is_root(self) -> bool:
        return self.parent_span_id is None


class FlowEdge(BaseModel):
    source_span_id: str
    target_span_id: str
    kind:           EdgeKind = EdgeKind.PARENT_CHILD
