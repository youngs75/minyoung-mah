"""RoleInvocationResult.metadata["usage"] propagation from provider AIMessage.

- Fast path (`_invoke_structured`): include_raw=True 경로에서 usage 추출
- General path (`_invoke_loop`): iteration 마다 누적
- 결과에 usage 가 빠져도 graceful (metadata = {})
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from minyoung_mah import InvocationContext, RoleStatus

from .conftest import FakeChatModel, build_orchestrator, make_role


class _Plan(BaseModel):
    headline: str
    confidence: float


def _ai_with_usage(
    content: str = "",
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    tool_calls: list[dict] | None = None,
) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


@pytest.mark.asyncio
async def test_structured_path_propagates_usage() -> None:
    role = make_role("macro", output_schema=_Plan, max_iterations=1)
    plan = _Plan(headline="Neutral", confidence=0.7)
    raw = _ai_with_usage("", input_tokens=1200, output_tokens=300)
    model = FakeChatModel(structured_responses=[plan], structured_raw_messages=[raw])
    orch = build_orchestrator(model=model, roles=[role])

    result = await orch.invoke_role(
        "macro",
        InvocationContext(task_summary="macro check", user_request="what regime"),
    )

    assert result.status is RoleStatus.COMPLETED
    assert result.output == plan
    assert result.metadata.get("usage") == {
        "input_tokens": 1200,
        "output_tokens": 300,
        "total_tokens": 1500,
    }


@pytest.mark.asyncio
async def test_structured_path_without_usage_returns_empty_metadata() -> None:
    role = make_role("macro", output_schema=_Plan, max_iterations=1)
    plan = _Plan(headline="Ok", confidence=0.5)
    raw = AIMessage(content="")  # no usage_metadata
    model = FakeChatModel(structured_responses=[plan], structured_raw_messages=[raw])
    orch = build_orchestrator(model=model, roles=[role])

    result = await orch.invoke_role(
        "macro",
        InvocationContext(task_summary="x", user_request="y"),
    )

    assert result.status is RoleStatus.COMPLETED
    assert "usage" not in result.metadata


@pytest.mark.asyncio
async def test_tool_loop_accumulates_usage_across_iterations() -> None:
    role = make_role("echoer", tool_allowlist=[], max_iterations=3)
    model = FakeChatModel(
        responses=[
            _ai_with_usage(
                "",
                input_tokens=100,
                output_tokens=20,
                tool_calls=[{"name": "echo", "args": {"text": "x"}, "id": "c1"}],
            ),
            _ai_with_usage("done", input_tokens=150, output_tokens=40),
        ]
    )
    orch = build_orchestrator(model=model, roles=[role])

    result = await orch.invoke_role(
        "echoer",
        InvocationContext(task_summary="do it", user_request="go"),
    )

    # Tool 없는 상태로 tool_call 을 하면 adapter 없음 → ok=False 이지만 loop 는 이어짐.
    # 두 번째 iteration 에서 tool_calls 가 없어 종료.
    assert result.status is RoleStatus.COMPLETED
    assert result.metadata.get("usage") == {
        "input_tokens": 250,
        "output_tokens": 60,
        "total_tokens": 310,
    }


@pytest.mark.asyncio
async def test_usage_extractor_handles_openai_naming() -> None:
    """OpenAI-compat 프로바이더 (prompt_tokens/completion_tokens) 도 매핑되는지."""
    role = make_role("macro", output_schema=_Plan, max_iterations=1)
    plan = _Plan(headline="x", confidence=0.1)
    raw = AIMessage(content="")
    # usage_metadata 없이 response_metadata 경로로 내려주는 provider 시뮬.
    raw.response_metadata = {"usage": {"prompt_tokens": 500, "completion_tokens": 100}}
    model = FakeChatModel(structured_responses=[plan], structured_raw_messages=[raw])
    orch = build_orchestrator(model=model, roles=[role])

    result = await orch.invoke_role("macro", InvocationContext(task_summary="x", user_request="y"))

    assert result.metadata.get("usage") == {
        "input_tokens": 500,
        "output_tokens": 100,
        "total_tokens": 600,
    }
