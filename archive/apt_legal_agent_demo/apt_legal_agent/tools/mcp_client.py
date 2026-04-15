"""MCP client protocol + a stub HTTP implementation.

The real wire protocol for ``apt-legal-mcp`` is Streamable HTTP defined by
the MCP spec. This module ships two things:

- :class:`MCPClient` — a narrow async protocol the tool adapters depend on.
  Anything that implements ``call_tool(name, args) -> dict`` satisfies it.
- :class:`HttpxMCPClient` — a minimal httpx-based implementation placeholder.
  The E2E tests inject a fake client instead, so this class only needs to be
  wire-compatible enough for manual local runs and will be fleshed out in
  the next session when we wire up the real ``apt-legal-mcp`` server.
"""

from __future__ import annotations

from typing import Any, Protocol


class MCPClient(Protocol):
    """Minimum surface the apt-legal tool adapters depend on."""

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        ...


class HttpxMCPClient:
    """Placeholder httpx-based MCP client.

    Not yet wired to the real ``apt-legal-mcp`` streaming HTTP protocol —
    that work lands when the MCP server itself is built. For now this class
    raises a clear error if actually invoked, so tests must inject a fake.
    """

    def __init__(self, base_url: str, timeout_s: float = 30.0) -> None:
        self.base_url = base_url
        self.timeout_s = timeout_s

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "HttpxMCPClient is a placeholder — inject a real MCPClient or a "
            "fake in tests. Real implementation lands with apt-legal-mcp."
        )
