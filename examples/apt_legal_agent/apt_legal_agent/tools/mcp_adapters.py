"""Six :class:`ToolAdapter` wrappers around the apt-legal MCP tools.

Each adapter declares a Pydantic argument schema and delegates execution
to the injected :class:`MCPClient`. Failures are surfaced as structured
:class:`ToolResult` — the library's tool-level retry layer will
automatically retry transient transport errors.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from minyoung_mah import ErrorCategory, ToolResult

from .mcp_client import MCPClient


# ---------------------------------------------------------------------------
# Argument schemas — one per MCP tool
# ---------------------------------------------------------------------------


class SearchLawArgs(BaseModel):
    query: str = Field(description="검색어 (한국어)")
    law_name: str | None = Field(
        default=None,
        description="법령명을 지정하면 해당 법령 내에서만 검색.",
    )
    max_results: int = Field(default=5, ge=1, le=20)


class GetLawArticleArgs(BaseModel):
    law_name: str
    article_number: str = Field(description="예: '제20조', '제35조의2'")
    include_history: bool = False


class SearchPrecedentArgs(BaseModel):
    query: str
    court_level: Literal["대법원", "고등법원", "지방법원"] | None = None
    max_results: int = Field(default=5, ge=1, le=20)


class GetPrecedentDetailArgs(BaseModel):
    case_number: str = Field(description="사건번호 (예: '2023다12345')")


class SearchInterpretationArgs(BaseModel):
    query: str
    source: str | None = Field(
        default=None,
        description="발행 기관 필터 (예: '법제처', '국토교통부')",
    )
    max_results: int = Field(default=5, ge=1, le=20)


class CompareLawsArgs(BaseModel):
    comparisons: list[dict] = Field(
        description="비교할 조문/법령 페어 목록. 각 항목은 MCP 서버 스펙을 따름."
    )
    focus: str | None = Field(default=None, description="비교 초점 (예: '관리비')")


# ---------------------------------------------------------------------------
# Generic wrapper
# ---------------------------------------------------------------------------


class McpProxyToolAdapter:
    """Wraps a single MCP tool as a minyoung-mah :class:`ToolAdapter`.

    The same class is parameterized by name, description, and argument
    schema — apt-legal instantiates it six times via
    :func:`make_mcp_adapters`.
    """

    def __init__(
        self,
        client: MCPClient,
        name: str,
        description: str,
        arg_schema: type[BaseModel],
    ) -> None:
        self.name = name
        self.description = description
        self.arg_schema = arg_schema
        self._client = client

    async def call(self, args: BaseModel) -> ToolResult:
        start = time.monotonic()
        payload = args.model_dump(exclude_none=True)
        try:
            raw = await self._client.call_tool(self.name, payload)
        except Exception as exc:  # noqa: BLE001 — categorize then surface
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                ok=False,
                value=None,
                error=f"{type(exc).__name__}: {exc}",
                error_category=_categorize_exception(exc),
                duration_ms=duration_ms,
                metadata={"via": "mcp", "tool": self.name},
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        return ToolResult(
            ok=True,
            value=raw if isinstance(raw, (dict, str)) else {"result": raw},
            duration_ms=duration_ms,
            metadata={"via": "mcp", "tool": self.name},
        )


def _categorize_exception(exc: BaseException) -> ErrorCategory:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return ErrorCategory.TIMEOUT
    if "ratelimit" in name or "429" in msg:
        return ErrorCategory.RATE_LIMIT
    if "connect" in name or "network" in name or "dns" in msg:
        return ErrorCategory.NETWORK
    if "401" in msg or "403" in msg or "unauthorized" in msg:
        return ErrorCategory.AUTH
    return ErrorCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Factory — build all six adapters from a shared client
# ---------------------------------------------------------------------------


_TOOL_SPECS: list[tuple[str, str, type[BaseModel]]] = [
    ("search_law", "키워드로 법령 조문을 검색합니다.", SearchLawArgs),
    ("get_law_article", "법령명과 조문번호로 전문을 조회합니다.", GetLawArticleArgs),
    ("search_precedent", "판례를 검색합니다.", SearchPrecedentArgs),
    ("get_precedent_detail", "사건번호로 판례 상세를 조회합니다.", GetPrecedentDetailArgs),
    ("search_interpretation", "법제처/정부 부처 행정해석을 검색합니다.", SearchInterpretationArgs),
    ("compare_laws", "여러 법령·조문을 비교합니다.", CompareLawsArgs),
]


def make_mcp_adapters(client: MCPClient) -> list[McpProxyToolAdapter]:
    return [
        McpProxyToolAdapter(client, name, desc, schema)
        for name, desc, schema in _TOOL_SPECS
    ]
