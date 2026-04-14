"""ExecuteToolsStep — LLM-less parallel tool dispatch step.

Verifies priority grouping, parallel execution, failure handling, and
continue_on_failure semantics.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from minyoung_mah import (
    ExecuteToolsStep,
    InvocationContext,
    PipelineStep,
    RoleStatus,
    StaticPipeline,
    ToolCallRequest,
    ToolResult,
)

from .conftest import FakeChatModel, build_orchestrator, make_role


class _SleepyArgs(BaseModel):
    key: str
    delay_ms: int = 0


class _SleepyAdapter:
    """Records call order and optionally delays — lets us verify parallelism."""

    def __init__(self, name: str, *, fail_on: set[str] | None = None) -> None:
        self.name = name
        self.description = f"sleepy tool {name}"
        self.arg_schema = _SleepyArgs
        self.calls: list[str] = []
        self._fail_on = fail_on or set()

    async def call(self, args: _SleepyArgs) -> ToolResult:
        if args.delay_ms:
            await asyncio.sleep(args.delay_ms / 1000)
        self.calls.append(args.key)
        if args.key in self._fail_on:
            return ToolResult(ok=False, value=None, error=f"failed on {args.key}")
        return ToolResult(ok=True, value={"key": args.key}, duration_ms=args.delay_ms)


def _plan_from_state(
    items: list[tuple[str, str, int, int]],
) -> "Callable":
    """Build a tool_calls_from callable for a fixed list of (tool, key, priority, delay)."""

    def _callable(state):  # noqa: ARG001
        return [
            (
                ToolCallRequest(
                    call_id=f"c-{i}",
                    tool_name=tool,
                    args={"key": key, "delay_ms": delay},
                ),
                priority,
            )
            for i, (tool, key, priority, delay) in enumerate(items)
        ]

    return _callable


@pytest.mark.asyncio
async def test_execute_tools_step_runs_group_in_parallel() -> None:
    """All p=1 calls start concurrently — total latency ≈ max(delays), not sum."""
    tool = _SleepyAdapter("slow")
    role = make_role("noop")  # unused but keeps Orchestrator happy
    model = FakeChatModel()
    orch = build_orchestrator(model=model, roles=[role], tools=[tool])

    plan = _plan_from_state(
        [
            ("slow", "a", 1, 80),
            ("slow", "b", 1, 80),
            ("slow", "c", 1, 80),
        ]
    )
    step = ExecuteToolsStep(name="exec", tool_calls_from=plan)
    pipeline = StaticPipeline(steps=[step])

    start = asyncio.get_event_loop().time()
    result = await orch.run_pipeline(pipeline, user_request="x")
    elapsed = asyncio.get_event_loop().time() - start

    assert result.completed
    assert len(result.state["exec"].tool_results) == 3
    assert all(r.ok for r in result.state["exec"].tool_results)
    # Parallel within priority: 3 × 80ms should finish well under 200ms.
    assert elapsed < 0.2, f"expected parallel execution, took {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_priority_groups_run_sequentially() -> None:
    """p=1 calls finish before p=2 calls start."""
    tool = _SleepyAdapter("t")
    role = make_role("noop")
    model = FakeChatModel()
    orch = build_orchestrator(model=model, roles=[role], tools=[tool])

    plan = _plan_from_state(
        [
            ("t", "first-p1", 1, 20),
            ("t", "second-p1", 1, 20),
            ("t", "first-p2", 2, 20),
        ]
    )
    step = ExecuteToolsStep(name="exec", tool_calls_from=plan)
    result = await orch.run_pipeline(StaticPipeline(steps=[step]), user_request="x")

    assert result.completed
    # p=1 calls must come before the p=2 call in the adapter call log.
    p1 = {"first-p1", "second-p1"}
    assert set(tool.calls[:2]) == p1
    assert tool.calls[2] == "first-p2"


@pytest.mark.asyncio
async def test_continue_on_failure_true_collects_all_results() -> None:
    tool = _SleepyAdapter("t", fail_on={"bad"})
    role = make_role("noop")
    model = FakeChatModel()
    orch = build_orchestrator(model=model, roles=[role], tools=[tool])

    plan = _plan_from_state(
        [
            ("t", "good", 1, 0),
            ("t", "bad", 1, 0),
            ("t", "also-good", 2, 0),
        ]
    )
    step = ExecuteToolsStep(
        name="exec", tool_calls_from=plan, continue_on_failure=True
    )
    result = await orch.run_pipeline(StaticPipeline(steps=[step]), user_request="x")

    assert result.completed  # continue_on_failure preserves completion
    results = result.state["exec"].tool_results
    assert len(results) == 3
    assert [r.ok for r in results] == [True, False, True]


@pytest.mark.asyncio
async def test_continue_on_failure_false_aborts_pipeline() -> None:
    tool = _SleepyAdapter("t", fail_on={"bad"})
    role_a = make_role("noop")
    role_b = make_role("after")
    model = FakeChatModel()
    orch = build_orchestrator(model=model, roles=[role_a, role_b], tools=[tool])

    plan = _plan_from_state(
        [
            ("t", "good", 1, 0),
            ("t", "bad", 1, 0),
            ("t", "never", 2, 0),  # should not run because p=1 failed
        ]
    )
    step = ExecuteToolsStep(
        name="exec", tool_calls_from=plan, continue_on_failure=False
    )
    # Follow with a role step to verify the pipeline aborts before reaching it.
    follow = PipelineStep(
        name="after",
        role="after",
        input_mapping=lambda s: InvocationContext(task_summary="", user_request=""),
    )
    pipeline = StaticPipeline(steps=[step, follow], on_step_failure="abort")
    result = await orch.run_pipeline(pipeline, user_request="x")

    assert not result.completed
    assert result.aborted_at == "exec"
    # p=2 call "never" must not have been issued.
    assert "never" not in tool.calls


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_result() -> None:
    tool = _SleepyAdapter("t")
    role = make_role("noop")
    model = FakeChatModel()
    orch = build_orchestrator(model=model, roles=[role], tools=[tool])

    plan = _plan_from_state([("missing_tool", "x", 1, 0)])
    step = ExecuteToolsStep(name="exec", tool_calls_from=plan)
    result = await orch.run_pipeline(StaticPipeline(steps=[step]), user_request="x")

    assert result.completed  # continue_on_failure=True by default
    assert len(result.state["exec"].tool_results) == 1
    assert result.state["exec"].tool_results[0].ok is False
    assert "not registered" in (result.state["exec"].tool_results[0].error or "")
