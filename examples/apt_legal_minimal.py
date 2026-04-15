"""A stripped-down, runnable reference of the apt-legal-agent pipeline shape.

This example exists so a new consumer can see — in a single file — how the
library is meant to be composed:

1. Declare roles as frozen dataclasses that duck-type :class:`SubAgentRole`.
2. Put a ``output_schema + max_iterations=1 + tool_allowlist=[]`` role at the
   top of the pipeline to hit the structured fast path (one LLM call, no
   tool loop, returns a typed ``BaseModel``).
3. Use ``StaticPipeline.shared_state`` for constants every role needs
   (e.g. a tenant id) instead of copying them into each ``input_mapping``.
4. Read the router's decision with ``state[name].payload_as(Decision)`` —
   no custom helper needed.
5. Let the synthesizer's ``build_user_message`` call
   ``PipelineStepResult.format_for_llm`` so INCOMPLETE upstream roles are
   surfaced with a status banner rather than silently trusted.

The example uses a tiny stub ``ChatModel`` so it can run without any real
LLM backend — the point is to show the shape, not the prompting. A real
consumer swaps ``StubChatModel`` for ``ChatLiteLLM`` (see
``apt-legal-agent/src/apt_legal_agent/model.py``) and plugs in MCP-backed
tools.

Run it with::

    uv run python examples/apt_legal_minimal.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from minyoung_mah import (
    InvocationContext,
    NullHITLChannel,
    NullMemoryStore,
    NullObserver,
    Orchestrator,
    PipelineStep,
    PipelineStepResult,
    RoleRegistry,
    SingleModelRouter,
    StaticPipeline,
    ToolRegistry,
    default_resilience,
)


# ---------------------------------------------------------------------------
# 1. Roles — plain frozen dataclasses that duck-type SubAgentRole
# ---------------------------------------------------------------------------


class RouterDecision(BaseModel):
    need_legal: bool
    need_domain: bool
    reason: str


@dataclass(frozen=True)
class StaticRole:
    name: str
    system_prompt: str
    tool_allowlist: list[str] = field(default_factory=list)
    model_tier: str = "default"
    output_schema: type[BaseModel] | None = None
    max_iterations: int = 1

    def build_user_message(self, invocation: InvocationContext) -> str:
        parts = [f"사용자 질문: {invocation.user_request}"]
        for step_name, step_result in (invocation.parent_outputs or {}).items():
            # format_for_llm() attaches a status banner so INCOMPLETE roles
            # are labeled rather than silently trusted.
            if isinstance(step_result, PipelineStepResult):
                block = step_result.format_for_llm()
                if block:
                    parts.append(f"\n[{step_name}]\n{block}")
        if (complex_id := (invocation.shared_state or {}).get("complex_id")):
            parts.append(f"\n단지 ID: {complex_id}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# 2. Stub chat model — stands in for ChatLiteLLM in real deployments
# ---------------------------------------------------------------------------


class _StructuredHandle:
    def __init__(self, decision: RouterDecision) -> None:
        self._decision = decision

    async def ainvoke(self, messages: list[Any]) -> RouterDecision:  # noqa: ARG002
        return self._decision


class StubChatModel:
    """Produces a canned router decision and a canned synthesis string.

    A real consumer uses ``langchain_litellm.ChatLiteLLM`` here.
    """

    async def ainvoke(self, messages: list[Any]) -> Any:  # noqa: ARG002
        from langchain_core.messages import AIMessage

        return AIMessage(content="합성된 답변(스텁): 법령 인용 + 단지 회의록 요약")

    def bind_tools(self, tool_defs: list[Any]) -> "StubChatModel":  # noqa: ARG002
        return self

    def with_structured_output(self, schema: type[BaseModel]) -> _StructuredHandle:
        assert schema is RouterDecision
        return _StructuredHandle(
            RouterDecision(
                need_legal=True,
                need_domain=True,
                reason="복합 질의 — 예제용 고정 응답",
            )
        )


# ---------------------------------------------------------------------------
# 3. Pipeline assembly
# ---------------------------------------------------------------------------


def build_pipeline() -> StaticPipeline:
    return StaticPipeline(
        shared_state={"complex_id": "APT-PILOT-001"},
        steps=[
            # Structured fast path: no tools, one iteration, typed output.
            PipelineStep(
                name="route",
                role="router",
                input_mapping=lambda state: InvocationContext(
                    task_summary="질의 라우팅", user_request=""
                ),
            ),
            # Conditional lookups read the router's decision via payload_as.
            PipelineStep(
                name="legal_lookup",
                role="legal_lookup",
                condition=lambda state: bool(
                    (d := state["route"].payload_as(RouterDecision)) and d.need_legal
                ),
                input_mapping=lambda state: InvocationContext(
                    task_summary="법령 조회", user_request=""
                ),
            ),
            PipelineStep(
                name="domain_lookup",
                role="domain_lookup",
                condition=lambda state: bool(
                    (d := state["route"].payload_as(RouterDecision)) and d.need_domain
                ),
                input_mapping=lambda state: InvocationContext(
                    task_summary="단지 도메인 조회", user_request=""
                ),
            ),
            # Synthesizer receives the whole state; its build_user_message
            # uses PipelineStepResult.format_for_llm to label INCOMPLETE
            # upstream results with a status banner.
            PipelineStep(
                name="synthesize",
                role="synthesizer",
                input_mapping=lambda state: InvocationContext(
                    task_summary="최종 답변 합성",
                    user_request="",
                    parent_outputs=state,
                ),
            ),
        ],
    )


async def main() -> None:
    role_registry = RoleRegistry.of(
        StaticRole(
            name="router",
            system_prompt="단지/법령 라우팅.",
            output_schema=RouterDecision,
            max_iterations=1,
        ),
        StaticRole(
            name="legal_lookup",
            system_prompt="국가 법령을 조회.",
            tool_allowlist=[],
            max_iterations=3,
        ),
        StaticRole(
            name="domain_lookup",
            system_prompt="단지 회의록을 조회.",
            tool_allowlist=[],
            max_iterations=3,
        ),
        StaticRole(
            name="synthesizer",
            system_prompt="근거 있는 답변만 생성.",
            max_iterations=1,
        ),
    )
    orchestrator = Orchestrator(
        role_registry=role_registry,
        tool_registry=ToolRegistry(),
        model_router=SingleModelRouter(StubChatModel()),
        memory=NullMemoryStore(),
        hitl=NullHITLChannel(),
        observer=NullObserver(),
        resilience=default_resilience(
            role_timeouts={
                "router": 30.0,
                "legal_lookup": 300.0,
                "domain_lookup": 240.0,
                "synthesizer": 120.0,
            },
        ),
    )
    result = await orchestrator.run_pipeline(
        build_pipeline(),
        user_request="장기수선충당금 사용 절차와 우리 단지 최근 결정을 비교해줘",
    )
    print("completed:", result.completed)
    for step_name, step_result in result.state.items():
        print(f"- {step_name}: skipped={step_result.skipped}", end=" ")
        if step_result.payload is not None:
            print(f"payload={type(step_result.payload).__name__}")
        else:
            print()


if __name__ == "__main__":
    asyncio.run(main())
