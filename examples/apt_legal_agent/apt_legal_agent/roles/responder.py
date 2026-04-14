"""Responder role — composes the final AgentResponse from retrieved material."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from minyoung_mah import InvocationContext

from ..models.response import AgentResponse
from ..prompts.responder import RESPONDER_SYSTEM_PROMPT


def _format_tool_results(tool_results: list[Any] | None) -> str:
    """Render ToolResult list as Korean-friendly text for the responder LLM.

    We keep each block small — name + ok flag + a JSON dump of the value or
    the error message. The responder prompt tells the model how to cite.
    """
    if not tool_results:
        return "(도구 호출 결과 없음)"
    blocks: list[str] = []
    for i, result in enumerate(tool_results):
        tool_name = (result.metadata or {}).get("tool", "unknown")
        if result.ok:
            value = result.value
            if hasattr(value, "model_dump"):
                rendered = json.dumps(
                    value.model_dump(), ensure_ascii=False, indent=2
                )
            elif isinstance(value, (dict, list)):
                rendered = json.dumps(value, ensure_ascii=False, indent=2)
            else:
                rendered = str(value)
            blocks.append(f"[{i}] {tool_name} (OK):\n{rendered}")
        else:
            blocks.append(
                f"[{i}] {tool_name} (FAILED): {result.error or '알 수 없는 오류'}"
            )
    return "\n\n".join(blocks)


def _build_user_message(ctx: InvocationContext) -> str:
    classification = ctx.parent_outputs.get("classifier")
    tool_results = ctx.parent_outputs.get("tool_results", [])
    classification_json = (
        classification.model_dump_json(indent=2)
        if classification is not None
        else "{}"
    )
    return (
        f"[사용자 질문]\n{ctx.user_request}\n\n"
        f"[분류 결과]\n{classification_json}\n\n"
        f"[법령·판례·해석 조회 결과]\n{_format_tool_results(tool_results)}\n\n"
        "위 자료를 바탕으로 AgentResponse를 생성하세요."
    )


RESPONDER_ROLE = SimpleNamespace(
    name="responder",
    system_prompt=RESPONDER_SYSTEM_PROMPT,
    tool_allowlist=[],
    model_tier="default",
    output_schema=AgentResponse,
    max_iterations=1,
    build_user_message=_build_user_message,
)
