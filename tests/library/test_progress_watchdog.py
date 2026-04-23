"""Progress-based watchdog — deadline extension on novel tool calls.
진전 기반 워치독 — 고유한 도구 호출 시 마감 시각 연장.

Unit tests for :class:`ProgressWatchdog` plus an integration test that
exercises the context-var plumbing all the way through
:class:`ToolInvocationEngine`.

:class:`ProgressWatchdog` 에 대한 단위 테스트와 ``ToolInvocationEngine`` 을
통한 contextvar 배관 전체를 검증하는 통합 테스트.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from minyoung_mah.core.tool_invocation import (
    DEFAULT_TOOL_RETRY,
    ToolInvocationEngine,
    _compute_args_hash,
)
from minyoung_mah.core.types import ToolCallRequest, ToolResult
from minyoung_mah.observer.events import NullObserver
from minyoung_mah.resilience.progress_watchdog import (
    CURRENT_WATCHDOG,
    ProgressWatchdog,
    install as install_watchdog,
    signal_current_progress,
)


# ── ProgressWatchdog unit tests ─────────────────────────────────────────────


def test_watchdog_rejects_nonpositive_base():
    with pytest.raises(ValueError):
        ProgressWatchdog(base_timeout_s=0)
    with pytest.raises(ValueError):
        ProgressWatchdog(base_timeout_s=-5)


def test_watchdog_rejects_negative_extend():
    with pytest.raises(ValueError):
        ProgressWatchdog(base_timeout_s=10, extend_s=-1)


def test_watchdog_rejects_cap_below_base():
    with pytest.raises(ValueError):
        ProgressWatchdog(base_timeout_s=100, max_total_s=50)


def test_watchdog_start_sets_initial_deadline():
    wd = ProgressWatchdog(base_timeout_s=30, extend_s=10, max_total_s=120)
    wd.start(now=1000.0)
    assert wd.remaining_s(now=1000.0) == pytest.approx(30.0)
    assert wd.remaining_s(now=1020.0) == pytest.approx(10.0)
    assert wd.expired(now=1030.0) is True


def test_watchdog_novel_hash_extends_deadline():
    wd = ProgressWatchdog(base_timeout_s=30, extend_s=10, max_total_s=120)
    wd.start(now=1000.0)
    # 10s in, novel signal → deadline moves to max(1030, 1010) + 10 = 1040
    assert wd.signal_progress(hash_("a"), now=1010.0) is True
    assert wd.remaining_s(now=1010.0) == pytest.approx(30.0)
    # 20s in, another novel → deadline to 1050
    assert wd.signal_progress(hash_("b"), now=1020.0) is True
    assert wd.remaining_s(now=1020.0) == pytest.approx(30.0)


def test_watchdog_repeat_hash_does_not_extend():
    wd = ProgressWatchdog(base_timeout_s=30, extend_s=10, max_total_s=120)
    wd.start(now=1000.0)
    wd.signal_progress(hash_("a"), now=1005.0)
    deadline_before = wd._deadline  # type: ignore[attr-defined]
    # Same hash — no extension
    assert wd.signal_progress(hash_("a"), now=1010.0) is False
    assert wd._deadline == deadline_before  # type: ignore[attr-defined]


def test_watchdog_respects_max_total_cap():
    wd = ProgressWatchdog(base_timeout_s=30, extend_s=20, max_total_s=60)
    wd.start(now=1000.0)
    # Multiple novel signals — deadline can only go up to 1000 + 60 = 1060
    wd.signal_progress(hash_("a"), now=1010.0)  # tries 1040, caps ok
    wd.signal_progress(hash_("b"), now=1020.0)  # tries 1060, caps at 1060
    wd.signal_progress(hash_("c"), now=1030.0)  # tries 1080, capped → no change
    assert wd.remaining_s(now=1030.0) == pytest.approx(30.0)
    assert wd.expired(now=1060.0) is True
    assert wd.signal_count == 3


def test_watchdog_signal_count_tracks_distinct_signals():
    wd = ProgressWatchdog(base_timeout_s=30, extend_s=5, max_total_s=100)
    wd.start(now=1000.0)
    wd.signal_progress(hash_("a"))
    wd.signal_progress(hash_("a"))  # dup — still 1
    wd.signal_progress(hash_("b"))  # 2
    wd.signal_progress(hash_("c"))  # 3
    assert wd.signal_count == 3


# ── ContextVar plumbing ─────────────────────────────────────────────────────


def test_install_scopes_the_watchdog():
    wd = ProgressWatchdog(base_timeout_s=10)
    assert CURRENT_WATCHDOG.get() is None
    with install_watchdog(wd):
        assert CURRENT_WATCHDOG.get() is wd
    assert CURRENT_WATCHDOG.get() is None


def test_install_nests_and_restores():
    outer = ProgressWatchdog(base_timeout_s=10)
    inner = ProgressWatchdog(base_timeout_s=5)
    with install_watchdog(outer):
        with install_watchdog(inner):
            assert CURRENT_WATCHDOG.get() is inner
        assert CURRENT_WATCHDOG.get() is outer


def test_signal_current_progress_no_watchdog_is_noop():
    # Outside install(), signaling just returns False — never raises.
    assert signal_current_progress(hash_("anything")) is False


def test_signal_current_progress_routes_to_active_watchdog():
    wd = ProgressWatchdog(base_timeout_s=10, extend_s=5, max_total_s=60)
    wd.start()
    with install_watchdog(wd):
        assert signal_current_progress(hash_("a")) is True
        assert signal_current_progress(hash_("a")) is False  # dup
        assert signal_current_progress(hash_("b")) is True
    assert wd.signal_count == 2


# ── ToolInvocationEngine integration ────────────────────────────────────────


class _EchoArgs(BaseModel):
    key: str


@dataclass
class _FakeAdapter:
    name: str = "echo"
    arg_schema: type = _EchoArgs

    async def call(self, args: _EchoArgs) -> ToolResult:
        return ToolResult(ok=True, value=args.key, error=None, duration_ms=1)


@pytest.mark.asyncio
async def test_tool_invocation_signals_watchdog_on_novel_success():
    wd = ProgressWatchdog(base_timeout_s=30, extend_s=10, max_total_s=120)
    wd.start()
    engine = ToolInvocationEngine(observer=NullObserver(), retry=DEFAULT_TOOL_RETRY)
    adapter = _FakeAdapter()

    with install_watchdog(wd):
        # Two distinct args, one dup — expect 2 signals
        await engine.call_one(adapter, ToolCallRequest(call_id="c1", tool_name="echo", args={"key": "a"}))
        await engine.call_one(adapter, ToolCallRequest(call_id="c2", tool_name="echo", args={"key": "b"}))
        await engine.call_one(adapter, ToolCallRequest(call_id="c3", tool_name="echo", args={"key": "a"}))

    assert wd.signal_count == 2


@pytest.mark.asyncio
async def test_tool_invocation_does_not_signal_on_failure():
    @dataclass
    class _FailingAdapter:
        name: str = "fail"
        arg_schema: type = _EchoArgs

        async def call(self, args: _EchoArgs) -> ToolResult:
            return ToolResult(
                ok=False,
                value=None,
                error="nope",
                duration_ms=1,
            )

    wd = ProgressWatchdog(base_timeout_s=30, extend_s=10, max_total_s=120)
    wd.start()
    engine = ToolInvocationEngine(observer=NullObserver(), retry=DEFAULT_TOOL_RETRY)

    with install_watchdog(wd):
        await engine.call_one(
            _FailingAdapter(),
            ToolCallRequest(call_id="c1", tool_name="fail", args={"key": "a"}),
        )

    assert wd.signal_count == 0


# ── _compute_args_hash stability ────────────────────────────────────────────


def test_compute_args_hash_stable_for_same_args():
    h1 = _compute_args_hash("tool", {"a": 1, "b": [2, 3]})
    h2 = _compute_args_hash("tool", {"b": [2, 3], "a": 1})  # different key order
    assert h1 == h2


def test_compute_args_hash_differs_by_tool_name():
    h1 = _compute_args_hash("tool_a", {"x": 1})
    h2 = _compute_args_hash("tool_b", {"x": 1})
    assert h1 != h2


def test_compute_args_hash_differs_by_args():
    h1 = _compute_args_hash("tool", {"x": 1})
    h2 = _compute_args_hash("tool", {"x": 2})
    assert h1 != h2


def test_compute_args_hash_handles_pydantic_model():
    m1 = _EchoArgs(key="a")
    m2 = _EchoArgs(key="a")
    assert _compute_args_hash("echo", m1) == _compute_args_hash("echo", m2)
    assert _compute_args_hash("echo", m1) != _compute_args_hash("echo", _EchoArgs(key="b"))


# ── helper ─────────────────────────────────────────────────────────────────


def hash_(s: str) -> int:
    """Stable int hash helper for readable test IDs."""
    return hash(("test", s))
