"""Tests for the library-ness helpers added in 0.1.0.

Covers:

- ``StaticPipeline.shared_state`` merged into every step's
  ``InvocationContext``, with step-level values winning on conflict.
- ``PipelineStepResult.payload`` / ``payload_as`` typed accessors.
- ``RoleInvocationResult.has_usable_output`` /
  ``output_text`` / ``format_for_llm`` for downstream synthesizer prompts.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from minyoung_mah import (
    InvocationContext,
    PipelineStep,
    RoleInvocationResult,
    RoleStatus,
    StaticPipeline,
)

from .conftest import FakeChatModel, build_orchestrator, make_role


class Decision(BaseModel):
    go: bool
    reason: str


class OtherDecision(BaseModel):
    value: int


# ---------------------------------------------------------------------------
# StaticPipeline.shared_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_shared_state_reaches_every_step() -> None:
    seen: list[dict] = []

    def capture(ctx: InvocationContext) -> str:
        seen.append(dict(ctx.shared_state or {}))
        return ctx.user_request

    role = make_role(
        "capture",
        output_schema=Decision,
        max_iterations=1,
        build_user_message=capture,
    )
    model = FakeChatModel(
        structured_responses=[
            Decision(go=True, reason="first"),
            Decision(go=True, reason="second"),
        ]
    )
    orch = build_orchestrator(model=model, roles=[role])

    pipeline = StaticPipeline(
        shared_state={"complex_id": "APT-001", "tenant": "pilot"},
        steps=[
            PipelineStep(
                name="a",
                role="capture",
                input_mapping=lambda s: InvocationContext(
                    task_summary="", user_request="q"
                ),
            ),
            PipelineStep(
                name="b",
                role="capture",
                input_mapping=lambda s: InvocationContext(
                    task_summary="", user_request="q"
                ),
            ),
        ],
    )
    await orch.run_pipeline(pipeline, user_request="q")
    assert seen == [
        {"complex_id": "APT-001", "tenant": "pilot"},
        {"complex_id": "APT-001", "tenant": "pilot"},
    ]


@pytest.mark.asyncio
async def test_step_shared_state_wins_over_pipeline_shared_state() -> None:
    seen: list[dict] = []

    def capture(ctx: InvocationContext) -> str:
        seen.append(dict(ctx.shared_state or {}))
        return ctx.user_request

    role = make_role(
        "capture",
        output_schema=Decision,
        max_iterations=1,
        build_user_message=capture,
    )
    model = FakeChatModel(structured_responses=[Decision(go=True, reason="x")])
    orch = build_orchestrator(model=model, roles=[role])

    pipeline = StaticPipeline(
        shared_state={"complex_id": "APT-001", "tenant": "pilot"},
        steps=[
            PipelineStep(
                name="a",
                role="capture",
                input_mapping=lambda s: InvocationContext(
                    task_summary="",
                    user_request="q",
                    shared_state={"complex_id": "APT-999"},
                ),
            ),
        ],
    )
    await orch.run_pipeline(pipeline, user_request="q")
    # Step override wins, pipeline default survives for untouched keys.
    assert seen == [{"complex_id": "APT-999", "tenant": "pilot"}]


# ---------------------------------------------------------------------------
# PipelineStepResult.payload / payload_as
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_payload_and_payload_as() -> None:
    role = make_role("router", output_schema=Decision, max_iterations=1)
    model = FakeChatModel(
        structured_responses=[Decision(go=True, reason="yes")]
    )
    orch = build_orchestrator(model=model, roles=[role])

    pipeline = StaticPipeline(
        steps=[
            PipelineStep(
                name="route",
                role="router",
                input_mapping=lambda s: InvocationContext(
                    task_summary="", user_request="q"
                ),
            )
        ]
    )
    result = await orch.run_pipeline(pipeline, user_request="q")
    step = result.state["route"]

    assert isinstance(step.payload, Decision)
    assert step.payload.go is True

    typed = step.payload_as(Decision)
    assert typed is not None and typed.reason == "yes"

    # Wrong class returns None rather than raising.
    assert step.payload_as(OtherDecision) is None


def test_step_payload_none_on_skipped_step() -> None:
    from minyoung_mah import PipelineStepResult

    empty = PipelineStepResult(
        step_name="skipped", role_name="x", outputs=[], skipped=True
    )
    assert empty.payload is None
    assert empty.payload_as(Decision) is None
    assert empty.format_for_llm() == ""


# ---------------------------------------------------------------------------
# RoleInvocationResult formatting
# ---------------------------------------------------------------------------


def test_role_result_has_usable_output_false_for_incomplete() -> None:
    r = RoleInvocationResult(
        role_name="lookup",
        status=RoleStatus.INCOMPLETE,
        output="partial data",
        iterations=10,
        error="exceeded max_iterations",
    )
    assert r.has_usable_output is False


def test_role_result_has_usable_output_true_when_completed() -> None:
    r = RoleInvocationResult(
        role_name="lookup",
        status=RoleStatus.COMPLETED,
        output="final data",
        iterations=3,
    )
    assert r.has_usable_output is True


def test_role_result_format_for_llm_marks_incomplete_with_banner() -> None:
    r = RoleInvocationResult(
        role_name="domain_lookup",
        status=RoleStatus.INCOMPLETE,
        output="회의록 2건만 찾음",
        iterations=10,
        error="exceeded max_iterations=10",
    )
    out = r.format_for_llm()
    assert "status=INCOMPLETE" in out
    assert "iterations=10" in out
    assert "error=exceeded max_iterations=10" in out
    assert "회의록 2건만 찾음" in out


def test_role_result_format_for_llm_skips_incomplete_when_opted_out() -> None:
    r = RoleInvocationResult(
        role_name="x",
        status=RoleStatus.FAILED,
        output=None,
        error="boom",
    )
    assert r.format_for_llm(include_incomplete=False) == ""


def test_role_result_output_text_serializes_basemodel_and_dict() -> None:
    completed_basemodel = RoleInvocationResult(
        role_name="r",
        status=RoleStatus.COMPLETED,
        output=Decision(go=True, reason="ok"),
    )
    assert '"go":true' in completed_basemodel.output_text().replace(" ", "")

    completed_dict = RoleInvocationResult(
        role_name="r",
        status=RoleStatus.COMPLETED,
        output={"한글": "값"},
    )
    # ensure_ascii=False — Korean must survive.
    assert "한글" in completed_dict.output_text()


@pytest.mark.asyncio
async def test_step_format_for_llm_concatenates_fan_out_blocks() -> None:
    role = make_role("w", output_schema=Decision, max_iterations=1)
    model = FakeChatModel(
        structured_responses=[
            Decision(go=True, reason="one"),
            Decision(go=False, reason="two"),
        ]
    )
    orch = build_orchestrator(model=model, roles=[role])

    pipeline = StaticPipeline(
        steps=[
            PipelineStep(
                name="workers",
                role="w",
                input_mapping=lambda s: InvocationContext(
                    task_summary="", user_request="q"
                ),
                fan_out=lambda s: [
                    InvocationContext(task_summary=f"t{i}", user_request="q")
                    for i in range(2)
                ],
            )
        ]
    )
    result = await orch.run_pipeline(pipeline, user_request="q")
    formatted = result.state["workers"].format_for_llm()
    # Two blocks, each with the role banner.
    assert formatted.count("[role=w status=COMPLETED") == 2
    assert "one" in formatted and "two" in formatted
