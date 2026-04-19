"""``build_subagent_task_tool`` — LangGraph task tool with replay-safety.

LangGraph's ``interrupt()`` replays the entire tool function on resume, which
means every side effect that ran before the interrupt runs again. For a tool
whose job is to call a SubAgent (nondeterministic LLM) and then interrupt to
ask the user a question, the naive implementation drifts by one round: the
resumed replay generates a *new* pending question but receives the *previous*
answer back from ``interrupt()``.

The library-owned fix memoises each iteration's
:class:`~minyoung_mah.RoleInvocationResult` in a module-level cache keyed by
``(tool_call_id, iter_idx)``:

* fresh call → cache miss → ``invoke_role`` → cache write → ``interrupt``
* replay     → cache hit  → skip invoke → ``interrupt`` returns stored
                answer immediately → loop proceeds deterministically

The cache is cleared when the tool call reaches a terminal state (success or
non-GraphInterrupt failure); ``GraphInterrupt`` re-raises with the cache
intact so LangGraph can replay.

## Consumer integration

Consumers pass a set of hooks so the library owns only the replay-safety
loop while application concerns (role resolution, todo ledger advancement,
result formatting) stay at the consumer layer:

    from minyoung_mah.langgraph import build_subagent_task_tool

    tool = build_subagent_task_tool(
        orchestrator,
        resolve_role=lambda at, desc: my_classifier.resolve(at, desc),
        format_result=my_result_renderer,
        format_hitl_answer=my_answer_formatter,
        on_tool_call_start=my_ledger_in_progress,
        on_tool_call_end=my_ledger_complete,
        on_user_answer=my_user_decisions.record,
    )

Reference:
https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/#code-that-precedes-interrupts-is-replayed
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Annotated, Any, Callable, Iterator

import structlog
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from minyoung_mah.hitl.interrupt import extract_interrupt_payload

if TYPE_CHECKING:
    from minyoung_mah import Orchestrator, RoleInvocationResult


log = structlog.get_logger("minyoung_mah.langgraph.subagent_task_tool")


# Module-level cache for replay safety. Keyed by ``tool_call_id`` (injected
# by LangGraph per tool call); inner dict maps ``iter_idx`` → role result.
# Entries live for the duration of a single tool call — cleared on terminal
# via :func:`replay_safe_tool_call`.
_TOOL_CALL_CACHE: dict[str, dict[int, Any]] = {}


# One shared thread pool across all tool invocations — avoids per-call
# thread/loop startup cost. 4 workers is enough for single-user agents; if
# a consumer needs more concurrency they can call ``invoke_role`` on their
# own executor.
_shared_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


@contextmanager
def replay_safe_tool_call(tool_call_id: str) -> Iterator[dict[int, Any]]:
    """Yield a cache bucket that persists across LangGraph replays.

    Usage::

        with replay_safe_tool_call(tool_call_id) as cache_bucket:
            iter_idx = 0
            while True:
                cached = cache_bucket.get(iter_idx)
                if cached is None:
                    cached = expensive_nondeterministic_call()
                    cache_bucket[iter_idx] = cached
                ...

    On :class:`~langgraph.errors.GraphInterrupt` the bucket is preserved so
    the replay observes the same cached results. On any other exit — normal
    return or other exception — the bucket is cleared to free memory.
    """
    bucket = _TOOL_CALL_CACHE.setdefault(tool_call_id, {})
    try:
        yield bucket
    except GraphInterrupt:
        raise
    except BaseException:
        _TOOL_CALL_CACHE.pop(tool_call_id, None)
        raise
    else:
        _TOOL_CALL_CACHE.pop(tool_call_id, None)


def _run_async(coro: Any, timeout: float) -> Any:
    """Run ``coro`` to completion from sync code, even under a running loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        future = _shared_pool.submit(asyncio.run, coro)
        return future.result(timeout=timeout)
    return asyncio.run(coro)


class SubAgentTaskInput(BaseModel):
    """Default input schema for ``build_subagent_task_tool``.

    ``tool_call_id`` is injected by LangGraph at call time and excluded from
    the LLM-facing schema via :class:`InjectedToolCallId`. The model never
    supplies it; the library uses it as the replay cache key.
    """

    description: str = Field(
        description="A detailed description of the task to delegate to a SubAgent."
    )
    agent_type: str = Field(
        default="auto",
        description=(
            "Target role name, or 'auto' to let the consumer's resolver pick."
        ),
    )
    tool_call_id: Annotated[str, InjectedToolCallId] = ""


# ---------------------------------------------------------------------------
# Hook type aliases — Callable sigs for the builder kwargs.
# ---------------------------------------------------------------------------


ResolveRole = Callable[[str, str], str]
"""``(agent_type, description) -> role_name``"""

FormatResult = Callable[..., str]
"""``(role_name, description, result, elapsed_s, status_tag) -> str``

Receives only successful terminal results (``COMPLETED`` or ``INCOMPLETE``).
Failures are formatted by ``format_failure``.
"""

FormatFailure = Callable[..., str]
"""``(role_name, description, result, elapsed_s) -> str``

Called for ``FAILED`` / ``ABORTED`` statuses.
"""

FormatHITLAnswer = Callable[[dict[str, Any], Any], str]
"""``(payload, user_answer) -> formatted_for_role_prompt``"""

OnToolCallStart = Callable[[str, str], None]
"""``(role_name, description) -> None`` — before the first invoke."""

OnToolCallEnd = Callable[..., None]
"""``(role_name, description, result, status_tag) -> None`` — after terminal."""

OnUserAnswer = Callable[[str], None]
"""``(formatted_answer) -> None`` — each time the user resumes with an answer."""


# ---------------------------------------------------------------------------
# Default formatters — minimal, framework-neutral.
# ---------------------------------------------------------------------------


def _default_format_result(
    *,
    role_name: str,
    description: str,  # noqa: ARG001
    result: "RoleInvocationResult",
    elapsed_s: float,
    status_tag: str,
) -> str:
    output = result.output
    if output is None:
        body = ""
    elif isinstance(output, str):
        body = output
    elif isinstance(output, BaseModel):
        body = output.model_dump_json()
    else:
        body = str(output)
    return f"[Task {status_tag} — {role_name}]\n{body}\n[Duration: {elapsed_s:.1f}s]"


def _default_format_failure(
    *,
    role_name: str,
    description: str,  # noqa: ARG001
    result: "RoleInvocationResult",
    elapsed_s: float,  # noqa: ARG001
) -> str:
    err = result.error or f"role '{role_name}' terminated with {result.status.name}"
    return f"SubAgent failed: {err}"


def _default_format_hitl_answer(payload: dict[str, Any], answer: Any) -> str:  # noqa: ARG001
    return str(answer)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_subagent_task_tool(
    orchestrator: "Orchestrator",
    *,
    resolve_role: ResolveRole,
    format_result: FormatResult | None = None,
    format_failure: FormatFailure | None = None,
    format_hitl_answer: FormatHITLAnswer | None = None,
    on_tool_call_start: OnToolCallStart | None = None,
    on_tool_call_end: OnToolCallEnd | None = None,
    on_user_answer: OnUserAnswer | None = None,
    tool_name: str = "task",
    tool_description: str = (
        "Delegate a task to a specialized SubAgent. "
        "Use this when a task is complex enough to benefit from a dedicated agent "
        "with its own tool access and reasoning loop."
    ),
    args_schema: type[BaseModel] = SubAgentTaskInput,
    invoke_timeout_s: float = 600.0,
) -> StructuredTool:
    """Build a replay-safe LangGraph ``task`` tool over an Orchestrator.

    The returned ``StructuredTool`` is safe to bind to a LangGraph node whose
    model may interrupt for human input. Each call:

    1. Resolves the target role via ``resolve_role``.
    2. Invokes the role through ``orchestrator.invoke_role`` and scans the
       result for the HITL interrupt marker
       (``minyoung_mah.hitl.HITL_INTERRUPT_MARKER``).
    3. On marker → raises LangGraph ``interrupt(payload)``; on resume, feeds
       the formatted answer back into a new invocation via
       ``InvocationContext.parent_outputs['previous_ask']``.
    4. On terminal status → emits via ``format_result`` (success) or
       ``format_failure`` (FAILED/ABORTED).

    Replays of a single tool call reuse cached invocation results (see
    :func:`replay_safe_tool_call`) so the resume round does not re-call the
    nondeterministic LLM.
    """
    from minyoung_mah import InvocationContext, RoleStatus

    _format_result = format_result or _default_format_result
    _format_failure = format_failure or _default_format_failure
    _format_hitl_answer = format_hitl_answer or _default_format_hitl_answer

    def _find_pending_interrupt(result: "RoleInvocationResult") -> dict[str, Any] | None:
        for res in result.tool_results or []:
            if not res.ok:
                continue
            payload = extract_interrupt_payload(res.value)
            if payload is not None:
                return payload
        return None

    def _run_task(
        description: str,
        agent_type: str = "auto",
        tool_call_id: str = "",
    ) -> str:
        t0 = time.monotonic()
        role_name = resolve_role(agent_type, description)
        log.info(
            "subagent_task.start",
            role=role_name,
            agent_type=agent_type,
            desc=description[:80],
            tool_call_id=tool_call_id[:16] if tool_call_id else "",
        )

        if on_tool_call_start is not None:
            try:
                on_tool_call_start(role_name, description)
            except Exception:
                log.exception("subagent_task.on_start_hook_failed", role=role_name)

        parent_outputs: dict[str, Any] = {}

        with replay_safe_tool_call(tool_call_id) as cache_bucket:
            iter_idx = 0
            while True:
                cached = cache_bucket.get(iter_idx)
                if cached is not None:
                    result = cached
                    log.debug(
                        "subagent_task.replay_cache_hit",
                        role=role_name,
                        iter_idx=iter_idx,
                    )
                else:
                    ctx = InvocationContext(
                        task_summary=description,
                        user_request="",
                        parent_outputs=dict(parent_outputs),
                    )
                    result = _run_async(
                        orchestrator.invoke_role(role_name, ctx), invoke_timeout_s
                    )
                    cache_bucket[iter_idx] = result

                pending = _find_pending_interrupt(result)
                if pending is not None:
                    log.info(
                        "subagent_task.propagate_interrupt",
                        role=role_name,
                        payload_preview=str(pending)[:120],
                        iter_idx=iter_idx,
                    )
                    user_answer = interrupt(pending)
                    log.info(
                        "subagent_task.received_answer",
                        answer_preview=str(user_answer)[:80],
                        iter_idx=iter_idx,
                    )
                    formatted = _format_hitl_answer(pending, user_answer)
                    if on_user_answer is not None:
                        try:
                            on_user_answer(formatted)
                        except Exception:
                            log.exception(
                                "subagent_task.on_user_answer_hook_failed",
                                role=role_name,
                            )
                    parent_outputs["previous_ask"] = formatted
                    iter_idx += 1
                    continue

                break

            elapsed = time.monotonic() - t0
            log.info(
                "subagent_task.done",
                role=role_name,
                status=result.status.name,
                duration_s=round(elapsed, 1),
                role_duration_ms=result.duration_ms,
                iterations=result.iterations,
            )

            if result.status in (RoleStatus.COMPLETED, RoleStatus.INCOMPLETE):
                status_tag = (
                    "INCOMPLETE" if result.status is RoleStatus.INCOMPLETE else "COMPLETED"
                )
                if on_tool_call_end is not None:
                    try:
                        on_tool_call_end(role_name, description, result, status_tag)
                    except Exception:
                        log.exception(
                            "subagent_task.on_end_hook_failed", role=role_name
                        )
                return _format_result(
                    role_name=role_name,
                    description=description,
                    result=result,
                    elapsed_s=elapsed,
                    status_tag=status_tag,
                )

            if on_tool_call_end is not None:
                try:
                    on_tool_call_end(role_name, description, result, "FAILED")
                except Exception:
                    log.exception("subagent_task.on_end_hook_failed", role=role_name)
            return _format_failure(
                role_name=role_name,
                description=description,
                result=result,
                elapsed_s=elapsed,
            )

    return StructuredTool.from_function(
        func=_run_task,
        name=tool_name,
        description=tool_description,
        args_schema=args_schema,
    )


__all__ = [
    "SubAgentTaskInput",
    "build_subagent_task_tool",
    "replay_safe_tool_call",
]
