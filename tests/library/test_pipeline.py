"""Static pipeline execution — sequential steps, conditions, fan_out."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from minyoung_mah import (
    InvocationContext,
    PipelineStep,
    RoleStatus,
    StaticPipeline,
)

from .conftest import FakeChatModel, build_orchestrator, make_role


class SimpleOutput(BaseModel):
    kind: str
    detail: str


@pytest.mark.asyncio
async def test_two_step_pipeline_passes_state_forward() -> None:
    role_a = make_role("a", output_schema=SimpleOutput, max_iterations=1)
    role_b = make_role("b", output_schema=SimpleOutput, max_iterations=1)
    model = FakeChatModel(
        structured_responses=[
            SimpleOutput(kind="first", detail="A done"),
            SimpleOutput(kind="second", detail="B saw first"),
        ]
    )
    orch = build_orchestrator(model=model, roles=[role_a, role_b])

    pipeline = StaticPipeline(
        steps=[
            PipelineStep(
                name="first",
                role="a",
                input_mapping=lambda state: InvocationContext(
                    task_summary="run a", user_request=""
                ),
            ),
            PipelineStep(
                name="second",
                role="b",
                input_mapping=lambda state: InvocationContext(
                    task_summary="run b",
                    user_request="",
                    parent_outputs={"a": state["first"].output.output},
                ),
            ),
        ]
    )
    result = await orch.run_pipeline(pipeline, user_request="hello")

    assert result.completed
    assert result.state["first"].output.status is RoleStatus.COMPLETED
    assert result.state["second"].output.status is RoleStatus.COMPLETED
    assert result.state["second"].output.output.kind == "second"


@pytest.mark.asyncio
async def test_condition_skips_step() -> None:
    role_a = make_role("a", output_schema=SimpleOutput, max_iterations=1)
    role_b = make_role("b", output_schema=SimpleOutput, max_iterations=1)
    model = FakeChatModel(
        structured_responses=[SimpleOutput(kind="only", detail="A")]
    )
    orch = build_orchestrator(model=model, roles=[role_a, role_b])

    pipeline = StaticPipeline(
        steps=[
            PipelineStep(
                name="first",
                role="a",
                input_mapping=lambda s: InvocationContext(
                    task_summary="", user_request=""
                ),
            ),
            PipelineStep(
                name="second",
                role="b",
                input_mapping=lambda s: InvocationContext(
                    task_summary="", user_request=""
                ),
                condition=lambda s: False,  # always skip
            ),
        ]
    )
    result = await orch.run_pipeline(pipeline, user_request="go")
    assert result.completed
    assert result.state["second"].skipped


@pytest.mark.asyncio
async def test_fan_out_runs_in_parallel_and_collects_outputs() -> None:
    role = make_role("worker", output_schema=SimpleOutput, max_iterations=1)
    model = FakeChatModel(
        structured_responses=[
            SimpleOutput(kind="w", detail="w-0"),
            SimpleOutput(kind="w", detail="w-1"),
            SimpleOutput(kind="w", detail="w-2"),
        ]
    )
    orch = build_orchestrator(model=model, roles=[role])

    pipeline = StaticPipeline(
        steps=[
            PipelineStep(
                name="workers",
                role="worker",
                input_mapping=lambda s: InvocationContext(
                    task_summary="unused", user_request=""
                ),
                fan_out=lambda s: [
                    InvocationContext(task_summary=f"task {i}", user_request="")
                    for i in range(3)
                ],
            ),
        ]
    )

    result = await orch.run_pipeline(pipeline, user_request="work")
    assert result.completed
    step = result.state["workers"]
    assert len(step.outputs) == 3
    details = sorted(o.output.detail for o in step.outputs)
    assert details == ["w-0", "w-1", "w-2"]


@pytest.mark.asyncio
async def test_pipeline_aborts_on_failure() -> None:
    role_a = make_role("a", output_schema=SimpleOutput, max_iterations=1)
    role_b = make_role("b", output_schema=SimpleOutput, max_iterations=1)
    model = FakeChatModel(structured_responses=[])  # a will fail (no queued response)
    orch = build_orchestrator(model=model, roles=[role_a, role_b])

    pipeline = StaticPipeline(
        steps=[
            PipelineStep(
                name="first",
                role="a",
                input_mapping=lambda s: InvocationContext(
                    task_summary="", user_request=""
                ),
            ),
            PipelineStep(
                name="second",
                role="b",
                input_mapping=lambda s: InvocationContext(
                    task_summary="", user_request=""
                ),
            ),
        ]
    )
    result = await orch.run_pipeline(pipeline, user_request="x")

    assert not result.completed
    assert result.aborted_at == "first"
    assert "second" not in result.state
