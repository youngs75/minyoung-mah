"""Output schema of the retrieval_planner role.

The planner returns a flat list of :class:`ToolCallStep` entries. Each
step carries its own priority; the :class:`ExecuteToolsStep` executor
groups calls by priority and runs each priority in parallel.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCallStep(BaseModel):
    """One tool invocation in the retrieval plan."""

    index: int = Field(ge=0)
    tool_name: str = Field(
        description=(
            "One of the 6 MCP tool names: search_law, get_law_article, "
            "search_precedent, get_precedent_detail, search_interpretation, "
            "compare_laws."
        )
    )
    arguments: dict = Field(
        description="Arguments to pass to the tool. Must match the tool's schema."
    )
    priority: int = Field(
        ge=1,
        le=3,
        description="1 = required, 2 = supplementary, 3 = optional. Lower runs first.",
    )
    depends_on: list[int] = Field(
        default_factory=list,
        description=(
            "Indices of steps this call depends on. Phase 3 executor honors "
            "priority ordering only; dynamic dependency rewriting is deferred."
        ),
    )
    rationale: str = Field(
        description="Why this call is needed — used for observability traces."
    )


class ExecutionPlan(BaseModel):
    """The full plan emitted by the retrieval_planner role."""

    steps: list[ToolCallStep] = Field(
        default_factory=list,
        max_length=8,
        description="Between 1 and 8 tool calls in execution order.",
    )
