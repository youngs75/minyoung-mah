"""Shared fixtures for apt-legal tests.

Two fakes cover the external dependencies:

- :class:`FakeChatModel` — queues structured responses per role in the
  order the pipeline invokes them (classifier → planner → responder).
- :class:`FakeMCPClient` — returns canned dicts keyed by tool name,
  optionally per-invocation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# FakeChatModel
# ---------------------------------------------------------------------------


@dataclass
class FakeChatModel:
    """Minimal LangChain-compatible chat model that returns queued outputs.

    Only ``with_structured_output(...).ainvoke(...)`` is implemented —
    apt-legal roles never use the general tool-calling loop because all
    three roles set ``max_iterations=1`` + ``output_schema``.
    """

    structured_responses: list[BaseModel] = field(default_factory=list)

    def with_structured_output(self, schema: type[BaseModel]) -> "_StructuredModel":
        return _StructuredModel(self, schema)

    def bind_tools(self, *_args, **_kwargs) -> "FakeChatModel":
        return self


class _StructuredModel:
    def __init__(self, parent: FakeChatModel, schema: type[BaseModel]) -> None:
        self._parent = parent
        self._schema = schema

    async def ainvoke(self, messages: list[Any]) -> BaseModel:  # noqa: ARG002
        if not self._parent.structured_responses:
            raise RuntimeError(
                f"FakeChatModel queue is empty (expected {self._schema.__name__})"
            )
        response = self._parent.structured_responses.pop(0)
        if not isinstance(response, self._schema):
            raise TypeError(
                f"Queued response type {type(response).__name__} does not match "
                f"expected {self._schema.__name__}"
            )
        return response


# ---------------------------------------------------------------------------
# FakeMCPClient
# ---------------------------------------------------------------------------


class FakeMCPClient:
    """In-memory MCP client. Returns canned payloads per tool name.

    ``responses`` is ``{tool_name: payload}`` — every call to that tool
    gets the same payload back. For per-call variance set
    ``queues[tool_name] = [p1, p2, ...]`` instead.
    """

    def __init__(
        self,
        responses: dict[str, dict] | None = None,
        queues: dict[str, list[dict]] | None = None,
        raise_on: set[str] | None = None,
    ) -> None:
        self.responses = dict(responses or {})
        self.queues = {k: list(v) for k, v in (queues or {}).items()}
        self.raise_on = set(raise_on or set())
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, args))
        if name in self.raise_on:
            raise RuntimeError(f"FakeMCPClient configured to fail on '{name}'")
        if name in self.queues:
            return self.queues[name].pop(0)
        if name in self.responses:
            return self.responses[name]
        return {"tool": name, "args": args, "placeholder": True}
