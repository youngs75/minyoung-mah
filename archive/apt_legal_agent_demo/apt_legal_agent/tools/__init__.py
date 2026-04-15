"""MCP client + ToolAdapter wrappers for apt-legal."""

from .mcp_adapters import (
    CompareLawsArgs,
    GetLawArticleArgs,
    GetPrecedentDetailArgs,
    McpProxyToolAdapter,
    SearchInterpretationArgs,
    SearchLawArgs,
    SearchPrecedentArgs,
    make_mcp_adapters,
)
from .mcp_client import MCPClient

__all__ = [
    "CompareLawsArgs",
    "GetLawArticleArgs",
    "GetPrecedentDetailArgs",
    "McpProxyToolAdapter",
    "MCPClient",
    "SearchInterpretationArgs",
    "SearchLawArgs",
    "SearchPrecedentArgs",
    "make_mcp_adapters",
]
