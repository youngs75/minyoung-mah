"""ToolInvocationEngine — retry on transient errors, parallel fan-out."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from minyoung_mah import (
    CollectingObserver,
    ErrorCategory,
    ToolCallRequest,
    ToolInvocationEngine,
    ToolResult,
    ToolRetryPolicy,
)


class _Args(BaseModel):
    n: int


class _FlakyAdapter:
    name = "flaky"
    description = "Fails N-1 times, then succeeds."
    arg_schema = _Args

    def __init__(self, fails: int, category: ErrorCategory = ErrorCategory.TIMEOUT) -> None:
        self._remaining = fails
        self._category = category
        self.attempts = 0

    async def call(self, args: _Args) -> ToolResult:
        self.attempts += 1
        if self._remaining > 0:
            self._remaining -= 1
            return ToolResult(
                ok=False,
                value=None,
                error="transient",
                error_category=self._category,
                duration_ms=1,
            )
        return ToolResult(ok=True, value={"n": args.n}, duration_ms=1)


@pytest.mark.asyncio
async def test_retry_on_timeout_then_success() -> None:
    engine = ToolInvocationEngine(
        CollectingObserver(),
        retry=ToolRetryPolicy(
            max_attempts=3, initial_backoff_s=0.0, backoff_multiplier=1.0
        ),
    )
    adapter = _FlakyAdapter(fails=2, category=ErrorCategory.TIMEOUT)
    result = await engine.call_one(
        adapter, ToolCallRequest(call_id="c1", tool_name="flaky", args={"n": 5})
    )
    assert result.ok
    assert adapter.attempts == 3
    assert result.value == {"n": 5}


@pytest.mark.asyncio
async def test_auth_failure_not_retried() -> None:
    engine = ToolInvocationEngine(
        CollectingObserver(),
        retry=ToolRetryPolicy(max_attempts=5, initial_backoff_s=0.0),
    )
    adapter = _FlakyAdapter(fails=5, category=ErrorCategory.AUTH)
    result = await engine.call_one(
        adapter, ToolCallRequest(call_id="c1", tool_name="flaky", args={"n": 1})
    )
    assert result.ok is False
    assert adapter.attempts == 1  # no retry for AUTH


@pytest.mark.asyncio
async def test_parse_error_on_bad_args() -> None:
    engine = ToolInvocationEngine(CollectingObserver())
    adapter = _FlakyAdapter(fails=0)
    result = await engine.call_one(
        adapter,
        ToolCallRequest(call_id="c1", tool_name="flaky", args={"n": "not-an-int"}),
    )
    assert result.ok is False
    assert result.error_category is ErrorCategory.PARSE_ERROR
    assert adapter.attempts == 0  # never reached


@pytest.mark.asyncio
async def test_parallel_fan_out() -> None:
    engine = ToolInvocationEngine(CollectingObserver())
    adapters = [_FlakyAdapter(fails=0) for _ in range(3)]
    pairs = [
        (a, ToolCallRequest(call_id=f"c{i}", tool_name="flaky", args={"n": i}))
        for i, a in enumerate(adapters)
    ]
    results = await engine.call_parallel(pairs)
    assert all(r.ok for r in results)
    assert [r.value["n"] for r in results] == [0, 1, 2]
