"""Retrieval planner role — turns a classification into an ExecutionPlan."""

from __future__ import annotations

from types import SimpleNamespace

from minyoung_mah import InvocationContext

from ..models.plan import ExecutionPlan
from ..prompts.retrieval_planner import PLANNER_SYSTEM_PROMPT


def _build_user_message(ctx: InvocationContext) -> str:
    classification = ctx.parent_outputs.get("classifier")
    classification_json = (
        classification.model_dump_json(indent=2)
        if classification is not None
        else "{}"
    )
    return (
        f"사용자 질문:\n{ctx.user_request}\n\n"
        f"분류 결과 (DisputeClassification):\n{classification_json}\n\n"
        "위 정보를 바탕으로 MCP tool 호출 계획(ExecutionPlan)을 생성하세요."
    )


RETRIEVAL_PLANNER_ROLE = SimpleNamespace(
    name="retrieval_planner",
    system_prompt=PLANNER_SYSTEM_PROMPT,
    tool_allowlist=[],
    model_tier="default",
    output_schema=ExecutionPlan,
    max_iterations=1,
    build_user_message=_build_user_message,
)
