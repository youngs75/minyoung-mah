"""The six core protocols of minyoung-mah.

These protocols define the **library's API surface**. Application code
(coding agent, apt-legal-agent, ...) implements them — or uses the
opinionated defaults the library ships — and composes them through the
:class:`minyoung_mah.core.orchestrator.Orchestrator`.

Design rationale: docs/design/01_core_abstractions.md.
The six responsibilities this library takes on — Safety, Detection,
Clarity, Context, Observation — are enforced here and nowhere else.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from .types import (
    HITLEvent,
    HITLResponse,
    InvocationContext,
    MemoryEntry,
    ObserverEvent,
    ToolResult,
)


# ---------------------------------------------------------------------------
# 1. SubAgentRole — "this role is what"
# ---------------------------------------------------------------------------


@runtime_checkable
class SubAgentRole(Protocol):
    """A role is a declarative bundle that tells the Orchestrator how to
    invoke a SubAgent for a specific purpose.

    Roles are *data*, not active objects. The Orchestrator owns execution.
    Applications typically declare roles as frozen dataclasses or
    ``SimpleNamespace`` instances that duck-type this protocol.
    """

    name: str
    system_prompt: str
    tool_allowlist: list[str]
    model_tier: str
    output_schema: type[BaseModel] | None
    max_iterations: int

    def build_user_message(self, invocation: InvocationContext) -> str:
        """Construct the initial user message for this invocation."""
        ...


# ---------------------------------------------------------------------------
# 2. ToolAdapter — "this tool is how"
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolAdapter(Protocol):
    """Unified contract for every tool the Orchestrator might call.

    Internal implementations (shell, file I/O) and external proxies (MCP
    clients, HTTP APIs) look identical to the Orchestrator.
    """

    name: str
    description: str
    arg_schema: type[BaseModel]

    async def call(self, args: BaseModel) -> ToolResult:
        """Execute the tool. Must not raise for expected failures — return
        ``ToolResult(ok=False, error=..., error_category=...)`` instead.
        """
        ...


# ---------------------------------------------------------------------------
# 3. ModelRouter — "which model for this tier/role"
# ---------------------------------------------------------------------------


# A ``ModelHandle`` is any object that satisfies the LangChain
# :class:`BaseChatModel` surface the Orchestrator uses:
# ``ainvoke``, ``bind_tools``, and ``with_structured_output``. We alias
# it to :class:`BaseChatModel` so consumers get real type checking —
# ``Any`` was a polite fiction that hid the actual requirement. Test
# fixtures that duck-type a subset of the interface still work at
# runtime because the Orchestrator only calls the subset it needs.
ModelHandle = BaseChatModel


@runtime_checkable
class ModelRouter(Protocol):
    """Resolves a ``(tier, role_name)`` pair to a concrete chat model.

    Tier names are strings chosen by the application (e.g. ``"reasoning"``,
    ``"fast"``, or just ``"default"``). Both arguments are passed so routers
    can override per-role when needed.
    """

    def resolve(self, tier: str, role_name: str) -> ModelHandle: ...


# ---------------------------------------------------------------------------
# 4. MemoryStore — "remember and recall"
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryStore(Protocol):
    """Async-first persistent memory.

    Tiers are application-defined strings. ``scope`` further partitions
    entries within a tier (e.g. a project id, a user id, a session id).
    Passing ``scope=None`` to ``search`` matches all scopes.
    """

    async def write(
        self,
        tier: str,
        key: str,
        value: str,
        scope: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def read(
        self,
        tier: str,
        key: str,
        scope: str | None = None,
    ) -> MemoryEntry | None: ...

    async def search(
        self,
        tier: str,
        query: str,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]: ...

    async def list_tiers(self) -> list[str]: ...


# ---------------------------------------------------------------------------
# 5. HITLChannel — "ask the human, wait for a reply"
# ---------------------------------------------------------------------------


@runtime_checkable
class HITLChannel(Protocol):
    """Bidirectional bridge between a running pipeline and a human user.

    ``ask`` is a blocking async call. How the implementation blocks is up to
    the channel — a terminal prompt, an SSE long-poll, an in-memory queue.
    ``notify`` is non-blocking; channels may no-op it.
    """

    async def ask(
        self,
        question: str,
        options: list[str] | None = None,
        description: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> HITLResponse: ...

    async def notify(self, event: HITLEvent) -> None: ...


# ---------------------------------------------------------------------------
# 6. Observer — "what happened, when, how long"
# ---------------------------------------------------------------------------


@runtime_checkable
class Observer(Protocol):
    """Receives standardized :class:`ObserverEvent` objects.

    Implementations fan them out to Langfuse, structlog, OpenTelemetry, or
    a test collector. Events are fire-and-forget; observers must never
    raise back into the Orchestrator.
    """

    async def emit(self, event: ObserverEvent) -> None: ...


# ---------------------------------------------------------------------------
# Optional: MemoryExtractor — application hook, not a core responsibility
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryExtractor(Protocol):
    """Pulls memory-worthy facts out of a completed pipeline run.

    The library ships **no default implementation** (privacy-sensitive apps
    must opt in). Passing ``memory_extractor=None`` to the Orchestrator
    disables extraction entirely.
    """

    async def extract(
        self,
        user_request: str,
        result: Any,
        memory: MemoryStore,
    ) -> None: ...
