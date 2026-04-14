"""Core data types shared across all minyoung-mah protocols.

This module holds the **passive data structures** that flow between the
Orchestrator, roles, tool adapters, memory, and HITL channels. Protocols
themselves live in :mod:`minyoung_mah.core.protocols`.

Everything here is either a ``dataclass`` or a plain ``Enum`` so that it is
cheap to construct, easy to serialize, and safe to pass across async
boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Literal

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Invocation context — what a role receives when it is invoked
# ---------------------------------------------------------------------------


@dataclass
class InvocationContext:
    """Everything a role needs to run one invocation.

    The Orchestrator constructs this per ``invoke_role`` call. Roles treat it
    as read-only; any mutation belongs in the resulting ``RoleInvocationResult``.
    """

    task_summary: str
    user_request: str
    parent_outputs: dict[str, Any] = field(default_factory=dict)
    shared_state: dict[str, Any] = field(default_factory=dict)
    memory_snippets: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool invocation results
# ---------------------------------------------------------------------------


class ErrorCategory(Enum):
    """Library-level error taxonomy for tool-level retry decisions.

    Only the transient categories (``TIMEOUT``, ``RATE_LIMIT``, ``NETWORK``)
    are retried by the tool-level retry layer. ``AUTH`` is surfaced
    immediately because retrying usually cannot fix a credential problem.
    ``TOOL_ERROR`` and ``PARSE_ERROR`` are semantic failures — the library
    passes them through to the LLM so the role can decide what to do.
    """

    TIMEOUT = auto()
    RATE_LIMIT = auto()
    NETWORK = auto()
    AUTH = auto()
    TOOL_ERROR = auto()
    PARSE_ERROR = auto()
    UNKNOWN = auto()


TRANSIENT_ERRORS: frozenset[ErrorCategory] = frozenset(
    {ErrorCategory.TIMEOUT, ErrorCategory.RATE_LIMIT, ErrorCategory.NETWORK}
)


@dataclass
class ToolResult:
    """Structured outcome of a single tool call.

    ``value`` is constrained to ``str | BaseModel | dict`` per decision C1 so
    the Orchestrator knows exactly how to serialize the payload for the LLM.
    """

    ok: bool
    value: str | BaseModel | dict[str, Any] | None
    error: str | None = None
    error_category: ErrorCategory | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRequest:
    """One tool call requested by an LLM turn."""

    call_id: str
    tool_name: str
    args: dict[str, Any]


# ---------------------------------------------------------------------------
# Role invocation results
# ---------------------------------------------------------------------------


class RoleStatus(Enum):
    COMPLETED = auto()
    INCOMPLETE = auto()
    FAILED = auto()
    ABORTED = auto()


@dataclass
class RoleInvocationResult:
    """What a role invocation returns to the Orchestrator."""

    role_name: str
    status: RoleStatus
    output: str | BaseModel | dict[str, Any] | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    iterations: int = 0
    duration_ms: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Static pipeline definition
# ---------------------------------------------------------------------------


PipelineState = dict[str, "PipelineStepResult"]


@dataclass
class PipelineStepResult:
    """Aggregated result of a single pipeline step.

    For ``fan_out`` steps the ``outputs`` list holds all parallel invocations.
    For regular steps ``outputs`` has exactly one entry and ``output`` is
    a shortcut to it.
    """

    step_name: str
    role_name: str
    outputs: list[RoleInvocationResult]
    skipped: bool = False

    @property
    def output(self) -> RoleInvocationResult | None:
        return self.outputs[0] if self.outputs else None


@dataclass
class PipelineStep:
    """One node in a StaticPipeline.

    ``input_mapping`` builds the ``InvocationContext`` from the accumulated
    pipeline state. ``condition`` lets a step be skipped based on upstream
    outputs. ``fan_out`` turns the step into N parallel invocations of the
    same role — each with its own context.
    """

    name: str
    role: str
    input_mapping: Callable[[PipelineState], InvocationContext]
    condition: Callable[[PipelineState], bool] | None = None
    fan_out: Callable[[PipelineState], list[InvocationContext]] | None = None


@dataclass
class StaticPipeline:
    steps: list[PipelineStep]
    on_step_failure: Literal["abort", "continue", "escalate_hitl"] = "abort"


@dataclass
class PipelineResult:
    state: PipelineState
    completed: bool
    aborted_at: str | None = None
    error: str | None = None
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Dynamic loop (run_loop) — declared here so tests can import even though the
# actual implementation is deferred to Phase 4.
# ---------------------------------------------------------------------------


@dataclass
class LoopState:
    driver_role: str
    iterations: int
    last_result: RoleInvocationResult | None
    driver_returned_final: bool
    shared_state: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopResult:
    final_output: str | BaseModel | dict[str, Any] | None
    iterations: int
    completed: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


@dataclass
class MemoryEntry:
    """A single memory record. Scoped by ``tier`` + optional ``scope``."""

    tier: str
    key: str
    value: str
    scope: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# HITL
# ---------------------------------------------------------------------------


@dataclass
class HITLResponse:
    choice: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HITLEvent:
    kind: Literal["role_start", "role_end", "tool_call", "progress", "error"]
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Observer event
# ---------------------------------------------------------------------------


@dataclass
class ObserverEvent:
    """Standardized observer event — see design doc 04 §G1.

    ``name`` uses dotted notation (e.g. ``"orchestrator.role.invoke.start"``).
    Backend adapters translate this into Langfuse spans, structlog entries,
    OTel traces, etc.
    """

    name: str
    timestamp: datetime
    role: str | None = None
    tool: str | None = None
    duration_ms: int | None = None
    ok: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
