"""The apt-legal static pipeline — classifier → planner → executor → responder.

This is the entire orchestration contract for the agent. Roles live in
``apt_legal_agent.roles``; what order they run in and how they pass
state lives here. Per decision J1 the pipeline is static (no LLM-driven
routing) because the four-step shape is fixed by the product.
"""

from __future__ import annotations

from minyoung_mah import (
    ExecuteToolsStep,
    InvocationContext,
    PipelineStep,
    PipelineState,
    StaticPipeline,
    ToolCallRequest,
)

from .models.classification import DisputeClassification
from .models.plan import ExecutionPlan


# ---------------------------------------------------------------------------
# Input mappings — turn accumulated state into each role's InvocationContext
# ---------------------------------------------------------------------------


def _classifier_input(state: PipelineState) -> InvocationContext:
    # user_request is filled in by the Orchestrator via _ensure_user_request.
    return InvocationContext(task_summary="분쟁 분류", user_request="")


def _planner_input(state: PipelineState) -> InvocationContext:
    classifier_output = state["classifier"].output
    classification: DisputeClassification | None = (
        classifier_output.output if classifier_output is not None else None
    )
    return InvocationContext(
        task_summary="MCP 호출 계획 수립",
        user_request="",
        parent_outputs={"classifier": classification},
    )


def _responder_input(state: PipelineState) -> InvocationContext:
    classifier_output = state["classifier"].output
    classification: DisputeClassification | None = (
        classifier_output.output if classifier_output is not None else None
    )
    return InvocationContext(
        task_summary="최종 응답 생성",
        user_request="",
        parent_outputs={
            "classifier": classification,
            "tool_results": state["retrieval_executor"].tool_results,
        },
    )


# ---------------------------------------------------------------------------
# Tool-call plan builder — converts the planner output into executor input
# ---------------------------------------------------------------------------


def _tool_calls_from_plan(
    state: PipelineState,
) -> list[tuple[ToolCallRequest, int]]:
    planner_result = state["retrieval_planner"].output
    if planner_result is None or planner_result.output is None:
        return []
    plan: ExecutionPlan = planner_result.output
    return [
        (
            ToolCallRequest(
                call_id=f"plan-{step.index}",
                tool_name=step.tool_name,
                args=dict(step.arguments),
            ),
            step.priority,
        )
        for step in plan.steps
    ]


# ---------------------------------------------------------------------------
# Pipeline factory
# ---------------------------------------------------------------------------


def build_pipeline() -> StaticPipeline:
    """Assemble the 4-step static pipeline.

    Step order is fixed:

    1. ``classifier`` (structured LLM, no tools)
    2. ``retrieval_planner`` (structured LLM, no tools)
    3. ``retrieval_executor`` (:class:`ExecuteToolsStep`, parallel MCP calls)
    4. ``responder`` (structured LLM, no tools)

    ``continue_on_failure`` is True on the executor — a partial failure
    in MCP retrieval should still produce an answer that explicitly flags
    the gap, per the responder prompt.
    """
    return StaticPipeline(
        steps=[
            PipelineStep(
                name="classifier",
                role="classifier",
                input_mapping=_classifier_input,
            ),
            PipelineStep(
                name="retrieval_planner",
                role="retrieval_planner",
                input_mapping=_planner_input,
            ),
            ExecuteToolsStep(
                name="retrieval_executor",
                tool_calls_from=_tool_calls_from_plan,
                continue_on_failure=True,
            ),
            PipelineStep(
                name="responder",
                role="responder",
                input_mapping=_responder_input,
            ),
        ],
        on_step_failure="abort",
    )
