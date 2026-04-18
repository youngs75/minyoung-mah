"""Shared fixtures for Phase 2a library tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from minyoung_mah import (
    CollectingObserver,
    InvocationContext,
    NullHITLChannel,
    NullMemoryStore,
    Orchestrator,
    RoleRegistry,
    SingleModelRouter,
    SubAgentRole,
    ToolRegistry,
    default_resilience,
)
from minyoung_mah.core.types import ToolResult


# ---------------------------------------------------------------------------
# Fake chat model — minimal LangChain-compatible stand-in
# ---------------------------------------------------------------------------


@dataclass
class FakeChatModel:
    """A minimal stand-in for :class:`BaseChatModel`.

    ``responses`` is a list of ``AIMessage`` instances returned in order on
    successive ``ainvoke`` calls. ``structured_responses`` feeds
    ``with_structured_output`` calls. Set ``bind_tools_used`` to inspect
    whether the orchestrator wired tools into the model.
    """

    responses: list[AIMessage] = field(default_factory=list)
    structured_responses: list[BaseModel] = field(default_factory=list)
    structured_raw_messages: list[AIMessage] = field(default_factory=list)
    bind_tools_used: bool = False
    bound_tool_defs: list[Any] = field(default_factory=list)

    async def ainvoke(self, messages: list[Any]) -> AIMessage:  # noqa: ARG002
        if not self.responses:
            raise RuntimeError("FakeChatModel ran out of responses")
        return self.responses.pop(0)

    def bind_tools(self, tool_defs: list[Any]) -> "FakeChatModel":
        self.bind_tools_used = True
        self.bound_tool_defs = list(tool_defs)
        return self

    def with_structured_output(
        self, schema: type[BaseModel], *, include_raw: bool = False
    ) -> "_StructuredModel":
        return _StructuredModel(self, schema, include_raw=include_raw)


class _StructuredModel:
    def __init__(
        self, parent: FakeChatModel, schema: type[BaseModel], *, include_raw: bool = False
    ) -> None:
        self._parent = parent
        self._schema = schema
        self._include_raw = include_raw

    async def ainvoke(self, messages: list[Any]) -> BaseModel | dict[str, Any]:  # noqa: ARG002
        if not self._parent.structured_responses:
            raise RuntimeError("FakeChatModel has no structured responses queued")
        parsed = self._parent.structured_responses.pop(0)
        if self._include_raw:
            # Orchestrator 가 raw 에서 usage_metadata 를 읽으므로 structured_raw_messages 에서
            # 꺼내고, 없으면 usage 없는 AIMessage 하나를 생성.
            raw = (
                self._parent.structured_raw_messages.pop(0)
                if self._parent.structured_raw_messages
                else AIMessage(content="")
            )
            return {"raw": raw, "parsed": parsed, "parsing_error": None}
        return parsed


# ---------------------------------------------------------------------------
# Role factory
# ---------------------------------------------------------------------------


def make_role(
    name: str,
    *,
    system_prompt: str = "You are a test role.",
    tool_allowlist: list[str] | None = None,
    model_tier: str = "default",
    output_schema: type[BaseModel] | None = None,
    max_iterations: int = 5,
    build_user_message: Callable[[InvocationContext], str] | None = None,
) -> SubAgentRole:
    return SimpleNamespace(
        name=name,
        system_prompt=system_prompt,
        tool_allowlist=list(tool_allowlist or []),
        model_tier=model_tier,
        output_schema=output_schema,
        max_iterations=max_iterations,
        build_user_message=build_user_message or (lambda ctx: ctx.user_request),
    )


# ---------------------------------------------------------------------------
# Minimal tool adapter
# ---------------------------------------------------------------------------


class EchoArgs(BaseModel):
    text: str


class EchoToolAdapter:
    name = "echo"
    description = "Echo back the provided text."
    arg_schema = EchoArgs

    def __init__(self) -> None:
        self.calls: list[EchoArgs] = []

    async def call(self, args: EchoArgs) -> ToolResult:
        self.calls.append(args)
        return ToolResult(ok=True, value={"echoed": args.text}, duration_ms=1)


# ---------------------------------------------------------------------------
# Orchestrator fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def observer() -> CollectingObserver:
    return CollectingObserver()


@pytest.fixture
def echo_tool() -> EchoToolAdapter:
    return EchoToolAdapter()


@pytest.fixture
def fake_model() -> FakeChatModel:
    return FakeChatModel()


def build_orchestrator(
    *,
    model: FakeChatModel,
    roles: list[SubAgentRole],
    tools: list[Any] | None = None,
    observer: CollectingObserver | None = None,
) -> Orchestrator:
    return Orchestrator(
        role_registry=RoleRegistry.of(*roles),
        tool_registry=ToolRegistry.of(*(tools or [])),
        model_router=SingleModelRouter(model),
        memory=NullMemoryStore(),
        hitl=NullHITLChannel(),
        resilience=default_resilience(),
        observer=observer or CollectingObserver(),
    )
