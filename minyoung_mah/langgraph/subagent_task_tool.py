"""``build_subagent_task_tool`` — LangGraph task tool with replay-safety.
``build_subagent_task_tool`` — replay-safety 가 적용된 LangGraph task 도구.

LangGraph's ``interrupt()`` replays the entire tool function on resume, which
means every side effect that ran before the interrupt runs again. For a tool
whose job is to call a SubAgent (nondeterministic LLM) and then interrupt to
ask the user a question, the naive implementation drifts by one round: the
resumed replay generates a *new* pending question but receives the *previous*
answer back from ``interrupt()``.

LangGraph 의 ``interrupt()`` 는 resume 시 도구 함수 전체를 replay 한다 — 즉
interrupt 이전에 실행된 모든 side effect 가 다시 실행된다. SubAgent
(비결정적 LLM)를 호출한 뒤 사용자에게 묻기 위해 interrupt 하는 도구의 경우,
나이브한 구현은 한 라운드씩 어긋난다: 재개된 replay 가 *새* 질문을 만들면서
``interrupt()`` 로부터 *이전* 답변을 받는다.

The library-owned fix memoises each iteration's
:class:`~minyoung_mah.RoleInvocationResult` in a module-level cache keyed by
``(tool_call_id, iter_idx)``:

라이브러리가 소유한 해법은 매 iteration 의
:class:`~minyoung_mah.RoleInvocationResult` 를 ``(tool_call_id, iter_idx)``
키의 모듈 레벨 캐시에 memoize 하는 것:

* fresh call → cache miss → ``invoke_role`` → cache write → ``interrupt``
  최초 호출 → cache miss → ``invoke_role`` → cache 기록 → ``interrupt``
* replay     → cache hit  → skip invoke → ``interrupt`` returns stored
                answer immediately → loop proceeds deterministically
  replay → cache hit → invoke 생략 → ``interrupt`` 가 저장된 답변을 즉시 반환
          → 루프가 결정론적으로 진행

The cache is cleared when the tool call reaches a terminal state (success or
non-GraphInterrupt failure); ``GraphInterrupt`` re-raises with the cache
intact so LangGraph can replay.

캐시는 도구 호출이 terminal 상태(성공 또는 GraphInterrupt 가 아닌 실패)에
도달했을 때 비워진다. ``GraphInterrupt`` 는 캐시를 유지한 채 re-raise 되어
LangGraph 가 replay 할 수 있게 한다.

## Consumer integration / 컨슈머 통합

Consumers pass a set of hooks so the library owns only the replay-safety
loop while application concerns (role resolution, todo ledger advancement,
result formatting) stay at the consumer layer:

컨슈머가 일련의 훅을 넘겨주어, 라이브러리는 replay-safety 루프만 소유하고
애플리케이션 관심사(역할 해석, 할 일 ledger 전진, 결과 포맷팅)는 컨슈머
계층에 남는다:

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

Reference / 참고:
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
#
# replay 안전성을 위한 모듈 레벨 캐시. 키는 ``tool_call_id`` (LangGraph 가
# 도구 호출마다 주입). 내부 dict 는 ``iter_idx`` → role result 매핑.
# 항목은 단일 도구 호출 기간 동안만 유지되며, terminal 시점에
# :func:`replay_safe_tool_call` 이 비운다.
_TOOL_CALL_CACHE: dict[str, dict[int, Any]] = {}


# One shared thread pool across all tool invocations — avoids per-call
# thread/loop startup cost. 4 workers is enough for single-user agents; if
# a consumer needs more concurrency they can call ``invoke_role`` on their
# own executor.
#
# 모든 도구 호출에서 공유하는 단일 thread pool — 호출마다 thread/loop 를
# 새로 시작하는 비용을 피한다. 단일 사용자 에이전트에게는 4 워커면 충분.
# 더 큰 동시성이 필요하면 컨슈머가 자신의 executor 에서 ``invoke_role`` 을
# 호출하면 된다.
_shared_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


@contextmanager
def replay_safe_tool_call(tool_call_id: str) -> Iterator[dict[int, Any]]:
    """Yield a cache bucket that persists across LangGraph replays.
    LangGraph replay 사이에서도 유지되는 cache bucket 을 yield 한다.

    Usage / 사용법::

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

    :class:`~langgraph.errors.GraphInterrupt` 가 발생하면 bucket 이 보존되어
    replay 가 같은 cached 결과를 관찰한다. 그 외의 종료(정상 return, 다른
    예외)에서는 메모리 회수를 위해 bucket 이 비워진다.
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
    """Run ``coro`` to completion from sync code, even under a running loop.
    동기 코드에서 ``coro`` 를 끝까지 실행 — 이미 실행 중인 loop 아래에서도 동작."""
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
    ``build_subagent_task_tool`` 의 기본 입력 스키마.

    ``tool_call_id`` is injected by LangGraph at call time and excluded from
    the LLM-facing schema via :class:`InjectedToolCallId`. The model never
    supplies it; the library uses it as the replay cache key.

    ``tool_call_id`` 는 호출 시 LangGraph 가 주입하며 :class:`InjectedToolCallId`
    로 LLM 노출 스키마에서 제외된다. 모델이 직접 채우지 않으며, 라이브러리가
    이를 replay cache 키로 사용한다.
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
# 훅 타입 alias — builder kwargs 용 Callable 시그니처.
# ---------------------------------------------------------------------------


ResolveRole = Callable[[str, str], str]
"""``(agent_type, description) -> role_name``"""

FormatResult = Callable[..., str]
"""``(role_name, description, result, elapsed_s, status_tag) -> str``

Receives only successful terminal results (``COMPLETED`` or ``INCOMPLETE``).
Failures are formatted by ``format_failure``.

성공한 terminal 결과(``COMPLETED`` 또는 ``INCOMPLETE``)만 받는다.
실패는 ``format_failure`` 가 포맷한다.
"""

FormatFailure = Callable[..., str]
"""``(role_name, description, result, elapsed_s) -> str``

Called for ``FAILED`` / ``ABORTED`` statuses.
``FAILED`` / ``ABORTED`` 상태에 대해 호출된다.
"""

FormatHITLAnswer = Callable[[dict[str, Any], Any], str]
"""``(payload, user_answer) -> formatted_for_role_prompt``"""

OnToolCallStart = Callable[[str, str], None]
"""``(role_name, description) -> None`` — before the first invoke / 첫 호출 전."""

OnToolCallEnd = Callable[..., None]
"""``(role_name, description, result, status_tag) -> None`` — after terminal / terminal 도달 후."""

OnUserAnswer = Callable[[str], None]
"""``(formatted_answer) -> None`` — each time the user resumes with an answer.
사용자가 답변과 함께 재개할 때마다 호출된다."""


# ---------------------------------------------------------------------------
# Default formatters — minimal, framework-neutral.
# 기본 포맷터 — 미니멀하고 프레임워크 중립.
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
# Builder — 빌더
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
    Orchestrator 위에서 동작하는 replay-safe LangGraph ``task`` 도구를 만든다.

    The returned ``StructuredTool`` is safe to bind to a LangGraph node whose
    model may interrupt for human input. Each call:

    반환되는 ``StructuredTool`` 은 모델이 사람 입력을 위해 interrupt 할 수 있는
    LangGraph 노드에 안전하게 bind 가능. 각 호출은:

    1. Resolves the target role via ``resolve_role``.
       ``resolve_role`` 로 대상 역할을 해석.
    2. Invokes the role through ``orchestrator.invoke_role`` and scans the
       result for the HITL interrupt marker
       (``minyoung_mah.hitl.HITL_INTERRUPT_MARKER``).
       ``orchestrator.invoke_role`` 로 역할을 호출하고 결과에서 HITL interrupt
       마커(``minyoung_mah.hitl.HITL_INTERRUPT_MARKER``)를 스캔.
    3. On marker → raises LangGraph ``interrupt(payload)``; on resume, feeds
       the formatted answer back into a new invocation via
       ``InvocationContext.parent_outputs['previous_ask']``.
       마커 발견 → LangGraph ``interrupt(payload)`` 를 raise. 재개 시 포맷된
       답변을 ``InvocationContext.parent_outputs['previous_ask']`` 로 새 호출에 주입.
    4. On terminal status → emits via ``format_result`` (success) or
       ``format_failure`` (FAILED/ABORTED).
       terminal 상태 → ``format_result``(성공) 또는 ``format_failure``
       (FAILED/ABORTED) 로 emit.

    Replays of a single tool call reuse cached invocation results (see
    :func:`replay_safe_tool_call`) so the resume round does not re-call the
    nondeterministic LLM.

    단일 도구 호출의 replay 는 cached invocation 결과(:func:`replay_safe_tool_call`
    참조)를 재사용하여, 재개 라운드가 비결정적 LLM 을 다시 호출하지 않게 한다.
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
