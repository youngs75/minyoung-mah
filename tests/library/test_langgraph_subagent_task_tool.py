"""Unit tests for ``minyoung_mah.langgraph.subagent_task_tool``.

Focus: the replay-safety primitive and the HITL marker bridge. We stub out
``orchestrator.invoke_role`` with a counter so we can assert cache behaviour
without standing up a real LLM.
"""

from __future__ import annotations

from typing import Any

import pytest

# Skip the whole module if the optional langgraph extra isn't installed.
pytest.importorskip("langgraph")

from minyoung_mah import (  # noqa: E402
    HITL_INTERRUPT_MARKER,
    RoleInvocationResult,
    RoleStatus,
    ToolCallRequest,
    ToolResult,
    make_interrupt_marker,
)
from minyoung_mah.langgraph import (  # noqa: E402
    SubAgentTaskInput,
    build_subagent_task_tool,
    replay_safe_tool_call,
)
from minyoung_mah.langgraph import subagent_task_tool as module_under_test  # noqa: E402


def _tc(name: str, args: dict[str, Any], tool_call_id: str) -> dict[str, Any]:
    """Build the full ToolCall envelope LangChain expects when the schema
    declares ``InjectedToolCallId``. ``tool.invoke(...)`` with plain args
    fails because InjectedToolCallId can only be supplied this way.
    """
    return {
        "name": name,
        "args": args,
        "type": "tool_call",
        "id": tool_call_id,
    }


def _content(tool_output: Any) -> str:
    """ToolCall-envelope invokes return a ``ToolMessage``; raw invokes a str.
    Both are valid — we only assert on the content text.
    """
    return tool_output if isinstance(tool_output, str) else tool_output.content


class _CountingOrchestrator:
    """Stand-in for ``Orchestrator`` — records invoke_role calls."""

    def __init__(self, results: list[RoleInvocationResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, Any]] = []

    async def invoke_role(self, role_name: str, ctx: Any) -> RoleInvocationResult:
        self.calls.append((role_name, ctx))
        if not self._results:
            raise AssertionError("orchestrator stub ran out of queued results")
        return self._results.pop(0)


def _completed_result(text: str = "done") -> RoleInvocationResult:
    return RoleInvocationResult(
        role_name="tester",
        status=RoleStatus.COMPLETED,
        output=text,
        iterations=1,
    )


def _hitl_result(payload: dict[str, Any]) -> RoleInvocationResult:
    # Role hit the ask adapter: the marker rides on a successful ToolResult.
    tool_call = ToolCallRequest(tool_name="ask_user_question", args={}, call_id="ask-0")
    tool_result = ToolResult(
        ok=True,
        value=make_interrupt_marker(payload),
    )
    return RoleInvocationResult(
        role_name="tester",
        status=RoleStatus.COMPLETED,
        output="asked",
        tool_calls=[tool_call],
        tool_results=[tool_result],
        iterations=1,
    )


def test_schema_declares_injected_tool_call_id():
    # The schema carries tool_call_id; LangChain's InjectedToolCallId magic
    # hides it from the LLM-facing side while still requiring it at invoke
    # time via the ToolCall envelope.
    schema = SubAgentTaskInput.model_json_schema()
    assert "tool_call_id" in schema["properties"]
    assert "description" in schema["properties"]


def test_successful_call_clears_cache():
    orchestrator = _CountingOrchestrator([_completed_result("ok")])

    tool = build_subagent_task_tool(
        orchestrator,
        resolve_role=lambda agent_type, desc: "tester",
    )

    out = _content(tool.invoke(_tc("task", {"description": "do it"}, "tc-1")))

    assert "[Task COMPLETED — tester]" in out
    assert "ok" in out
    assert len(orchestrator.calls) == 1
    # Cache cleared on normal terminal so future calls with same id are fresh.
    assert "tc-1" not in module_under_test._TOOL_CALL_CACHE


def test_failure_path_uses_format_failure_and_clears_cache():
    failed = RoleInvocationResult(
        role_name="tester",
        status=RoleStatus.FAILED,
        output=None,
        error="boom",
    )
    orchestrator = _CountingOrchestrator([failed])

    tool = build_subagent_task_tool(
        orchestrator,
        resolve_role=lambda *_: "tester",
    )

    out = _content(tool.invoke(_tc("task", {"description": "x"}, "tc-fail")))
    assert "SubAgent failed" in out
    assert "boom" in out
    assert "tc-fail" not in module_under_test._TOOL_CALL_CACHE


def test_hitl_marker_triggers_interrupt_and_preserves_cache(
    monkeypatch: pytest.MonkeyPatch,
):
    payload = {"kind": "ask_user_question", "questions": [{"id": "q1"}]}
    orchestrator = _CountingOrchestrator([_hitl_result(payload)])

    raised: dict[str, Any] = {}

    def _fake_interrupt(value: Any) -> Any:
        # The real LangGraph interrupt raises GraphInterrupt with the payload
        # on the first pass. We simulate that contract here.
        from langgraph.errors import GraphInterrupt

        raised["payload"] = value
        raise GraphInterrupt(value)

    monkeypatch.setattr(module_under_test, "interrupt", _fake_interrupt)

    tool = build_subagent_task_tool(
        orchestrator,
        resolve_role=lambda *_: "tester",
    )

    from langgraph.errors import GraphInterrupt

    with pytest.raises(GraphInterrupt):
        tool.invoke(_tc("task", {"description": "ask me"}, "tc-hitl"))

    assert raised["payload"] == payload
    # Cache MUST persist across GraphInterrupt so the LangGraph replay on
    # resume sees the cached invocation and does not re-call the LLM.
    assert "tc-hitl" in module_under_test._TOOL_CALL_CACHE
    assert 0 in module_under_test._TOOL_CALL_CACHE["tc-hitl"]

    # Cleanup so the module-level cache does not leak between tests.
    module_under_test._TOOL_CALL_CACHE.pop("tc-hitl", None)


def test_replay_safe_tool_call_preserves_on_interrupt_clears_on_success():
    from langgraph.errors import GraphInterrupt

    # Success path clears.
    with replay_safe_tool_call("tc-ok") as bucket:
        bucket[0] = "result"
    assert "tc-ok" not in module_under_test._TOOL_CALL_CACHE

    # GraphInterrupt path preserves.
    with pytest.raises(GraphInterrupt):
        with replay_safe_tool_call("tc-int") as bucket:
            bucket[0] = "pending"
            raise GraphInterrupt("asked")
    assert module_under_test._TOOL_CALL_CACHE["tc-int"][0] == "pending"
    module_under_test._TOOL_CALL_CACHE.pop("tc-int", None)

    # Other exceptions clear too (tool raised a real error — no replay).
    with pytest.raises(RuntimeError):
        with replay_safe_tool_call("tc-err") as bucket:
            bucket[0] = "wip"
            raise RuntimeError("boom")
    assert "tc-err" not in module_under_test._TOOL_CALL_CACHE


def test_hooks_fire_with_expected_arguments():
    orchestrator = _CountingOrchestrator([_completed_result("done")])
    starts: list[tuple[str, str]] = []
    ends: list[tuple[str, str, str]] = []

    tool = build_subagent_task_tool(
        orchestrator,
        resolve_role=lambda at, desc: "tester",
        on_tool_call_start=lambda role, desc: starts.append((role, desc)),
        on_tool_call_end=lambda role, desc, result, tag: ends.append((role, desc, tag)),
    )

    _content(tool.invoke(_tc("task", {"description": "do"}, "tc-hooks")))

    assert starts == [("tester", "do")]
    assert ends == [("tester", "do", "COMPLETED")]


def test_hook_exceptions_do_not_break_tool_call():
    orchestrator = _CountingOrchestrator([_completed_result("done")])

    def _broken(role: str, desc: str) -> None:
        raise ValueError("hook failed")

    tool = build_subagent_task_tool(
        orchestrator,
        resolve_role=lambda *_: "tester",
        on_tool_call_start=_broken,
    )

    # Hook explodes but tool still returns normally — logs the exception.
    out = _content(tool.invoke(_tc("task", {"description": "d"}, "tc-brk")))
    assert "COMPLETED" in out


def test_marker_constant_is_consumer_owned():
    # Consumers that author ask adapters need to import the marker, not
    # hardcode the string. This asserts the public re-export lives where
    # callers expect it.
    assert HITL_INTERRUPT_MARKER == "__mm_interrupt__"
