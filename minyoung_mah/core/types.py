"""Core data types shared across all minyoung-mah protocols.

This module holds the **passive data structures** that flow between the
Orchestrator, roles, tool adapters, memory, and HITL channels. Protocols
themselves live in :mod:`minyoung_mah.core.protocols`.

Everything here is either a ``dataclass`` or a plain ``Enum`` so that it is
cheap to construct, easy to serialize, and safe to pass across async
boundaries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


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

    @property
    def has_usable_output(self) -> bool:
        """True iff status is COMPLETED and ``output`` is not None.

        Use this in ``build_user_message`` / synthesizer prompts to decide
        whether to feed a result downstream. A role that ran out of
        iterations (``INCOMPLETE``) may have a partial ``output`` but the
        consumer should treat it as unreliable.
        """
        return self.status is RoleStatus.COMPLETED and self.output is not None

    def output_text(self) -> str:
        """Serialize ``output`` to a string the LLM can read.

        - ``None`` → empty string
        - ``str`` → as-is
        - ``BaseModel`` → ``model_dump_json()``
        - ``dict`` → ``json.dumps(..., ensure_ascii=False)``
        - other → ``str(value)``
        """
        value = self.output
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        if isinstance(value, dict):
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    def format_for_llm(self, *, include_incomplete: bool = True) -> str:
        """Return a labeled block suitable for inclusion in a downstream prompt.

        Shape::

            [role=<name> status=<STATUS> iterations=<N>]
            <output_text or '(no output)'>

        If the role is not usable (``INCOMPLETE``/``FAILED``/``ABORTED``) and
        ``include_incomplete=False``, returns an empty string. The default
        ``True`` surfaces partial results with their status banner so the
        downstream LLM can treat them as suspect rather than silently
        trusting them (the apt-legal scenario-3 hallucination trap).
        """
        if not self.has_usable_output and not include_incomplete:
            return ""
        body = self.output_text() or "(no output)"
        header = (
            f"[role={self.role_name} status={self.status.name} "
            f"iterations={self.iterations}]"
        )
        if self.error and not self.has_usable_output:
            header += f" error={self.error}"
        return f"{header}\n{body}"


# ---------------------------------------------------------------------------
# Static pipeline definition
# ---------------------------------------------------------------------------


PipelineState = dict[str, "PipelineStepResult"]


@dataclass
class PipelineStepResult:
    """Aggregated result of a single pipeline step.

    For role-based ``fan_out`` steps the ``outputs`` list holds all parallel
    role invocations. For :class:`ExecuteToolsStep` the ``outputs`` list is
    empty and ``tool_results`` holds the N parallel tool results in plan
    order. Role steps leave ``tool_results`` empty.
    """

    step_name: str
    role_name: str | None
    outputs: list[RoleInvocationResult]
    tool_results: list["ToolResult"] = field(default_factory=list)
    skipped: bool = False

    @property
    def output(self) -> RoleInvocationResult | None:
        """First role-invocation result, or ``None`` when the step was
        skipped / tool-only / fan_out empty.

        Prefer :attr:`payload` or :meth:`payload_as` for the actual value
        produced by the role. Prefer :meth:`format_for_llm` when feeding
        downstream synthesizers.
        """
        return self.outputs[0] if self.outputs else None

    @property
    def payload(self) -> Any:
        """Return the first role invocation's ``.output`` payload.

        Shortcut for the common ``state["step"].output.output`` access
        pattern — returns ``None`` if the step is skipped, empty, or the
        first output has no value.
        """
        out = self.output
        if out is None:
            return None
        return out.output

    def payload_as(self, cls: type[T]) -> T | None:
        """Return :attr:`payload` when it is an instance of ``cls``, else ``None``.

        Typed accessor for structured-output roles. Typical usage::

            decision = state["route"].payload_as(RouterDecision)
            if decision and decision.need_legal:
                ...
        """
        payload = self.payload
        if isinstance(payload, cls):
            return payload
        return None

    def format_for_llm(self, *, include_incomplete: bool = True) -> str:
        """Concatenate every role invocation's ``format_for_llm`` output.

        ``fan_out`` steps produce N blocks separated by blank lines. Tool-
        only / skipped steps return an empty string. See
        :meth:`RoleInvocationResult.format_for_llm` for the shape of each
        block and the rationale for surfacing INCOMPLETE results.
        """
        blocks = [
            out.format_for_llm(include_incomplete=include_incomplete)
            for out in self.outputs
        ]
        return "\n\n".join(b for b in blocks if b)


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
class ExecuteToolsStep:
    """A pipeline step that runs tool calls without an LLM.

    Use this when an upstream role has produced an execution plan and the
    next step is purely mechanical tool dispatch. The step pulls
    :class:`ToolCallRequest` instances out of the accumulated pipeline
    state via ``tool_calls_from`` and runs them through the shared
    :class:`ToolInvocationEngine`.

    Parameters
    ----------
    name:
        Unique step name — becomes the key in ``PipelineState``.
    tool_calls_from:
        Callable returning the list of tool calls to run. Each call may
        include a ``priority`` (1 = required, 2 = supplementary, 3 =
        optional). Calls with the same priority run in parallel; lower
        priority groups run first.
    condition:
        Optional skip predicate — same shape as :class:`PipelineStep`.
    continue_on_failure:
        When True (default), a failed tool call does not abort the step.
        When False, the step surfaces the first failing priority group as
        a step failure and subsequent priority groups are skipped.
    """

    name: str
    tool_calls_from: Callable[
        [PipelineState], list[tuple["ToolCallRequest", int]]
    ]
    condition: Callable[[PipelineState], bool] | None = None
    continue_on_failure: bool = True


@dataclass
class StaticPipeline:
    """Declaration of a sequential DAG of steps plus pipeline-wide context.

    ``shared_state`` is merged into every step's
    :class:`InvocationContext` before the role runs — per-step
    ``input_mapping`` values win on key conflicts. Use it for constants
    that every role needs to see (e.g. ``{"complex_id": "..."}``) so
    each ``input_mapping`` does not have to re-copy the same dict.
    """

    steps: list[PipelineStep | ExecuteToolsStep]
    on_step_failure: Literal["abort", "continue", "escalate_hitl"] = "abort"
    shared_state: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    state: PipelineState
    completed: bool
    aborted_at: str | None = None
    error: str | None = None
    duration_ms: int = 0


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
