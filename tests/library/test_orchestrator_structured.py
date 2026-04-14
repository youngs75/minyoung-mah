"""Orchestrator fast path — output_schema + max_iterations=1 + no tools."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel

from minyoung_mah import InvocationContext, RoleStatus

from .conftest import FakeChatModel, build_orchestrator, make_role


class Classification(BaseModel):
    label: Literal["positive", "negative", "neutral"]
    confidence: float


@pytest.mark.asyncio
async def test_structured_fast_path_returns_model_instance() -> None:
    role = make_role(
        "classifier",
        tool_allowlist=[],
        output_schema=Classification,
        max_iterations=1,
    )
    model = FakeChatModel(
        structured_responses=[Classification(label="positive", confidence=0.92)]
    )
    orch = build_orchestrator(model=model, roles=[role])

    result = await orch.invoke_role(
        "classifier",
        InvocationContext(
            task_summary="classify",
            user_request="I love this",
        ),
    )

    assert result.status is RoleStatus.COMPLETED
    assert isinstance(result.output, Classification)
    assert result.output.label == "positive"
    assert result.iterations == 1
    # No tool_calls were made on the fast path.
    assert result.tool_calls == []
