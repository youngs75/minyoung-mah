"""Orchestrator general path — tool-calling loop + serialization."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from minyoung_mah import InvocationContext, RoleStatus

from .conftest import EchoToolAdapter, FakeChatModel, build_orchestrator, make_role


def _ai_with_tool_call(tool_name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args, "id": call_id}],
    )


@pytest.mark.asyncio
async def test_tool_loop_executes_tool_then_finishes() -> None:
    role = make_role(
        "echoer",
        tool_allowlist=["echo"],
        max_iterations=5,
    )
    echo = EchoToolAdapter()
    model = FakeChatModel(
        responses=[
            _ai_with_tool_call("echo", {"text": "hi"}),
            AIMessage(content="done"),
        ]
    )
    orch = build_orchestrator(model=model, roles=[role], tools=[echo])

    result = await orch.invoke_role(
        "echoer",
        InvocationContext(task_summary="echo hi", user_request="please echo hi"),
    )

    assert result.status is RoleStatus.COMPLETED
    assert result.output == "done"
    assert result.iterations == 2
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "echo"
    assert result.tool_results[0].ok
    assert len(echo.calls) == 1
    assert echo.calls[0].text == "hi"
    # Model had bind_tools called with our OpenAI-style tool def.
    assert model.bind_tools_used
    assert model.bound_tool_defs[0]["function"]["name"] == "echo"


@pytest.mark.asyncio
async def test_max_iterations_enforced() -> None:
    """If the LLM keeps calling tools, we stop at max_iterations."""
    role = make_role("looper", tool_allowlist=["echo"], max_iterations=2)
    echo = EchoToolAdapter()
    model = FakeChatModel(
        responses=[
            _ai_with_tool_call("echo", {"text": "a"}, "c1"),
            _ai_with_tool_call("echo", {"text": "b"}, "c2"),
        ]
    )
    orch = build_orchestrator(model=model, roles=[role], tools=[echo])

    result = await orch.invoke_role(
        "looper",
        InvocationContext(task_summary="loop", user_request="loop forever"),
    )

    assert result.status is RoleStatus.INCOMPLETE
    assert result.iterations == 2
    assert "max_iterations=2" in (result.error or "")


@pytest.mark.asyncio
async def test_unknown_tool_in_call_surfaces_error_to_llm() -> None:
    """LLM requests a tool not in the allowlist — return error tool result."""
    role = make_role("misbehaver", tool_allowlist=["echo"], max_iterations=3)
    echo = EchoToolAdapter()
    model = FakeChatModel(
        responses=[
            _ai_with_tool_call("nonexistent", {"text": "x"}),
            AIMessage(content="gave up"),
        ]
    )
    orch = build_orchestrator(model=model, roles=[role], tools=[echo])

    result = await orch.invoke_role(
        "misbehaver",
        InvocationContext(task_summary="", user_request="x"),
    )

    assert result.status is RoleStatus.COMPLETED
    assert result.output == "gave up"
    assert result.tool_results[0].ok is False
    assert "not in allowlist" in (result.tool_results[0].error or "")
