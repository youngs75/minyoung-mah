"""Composition root for the apt-legal Orchestrator.

Everything that is supplied at process startup — the chat model, the MCP
client, the HITL channel, the observer — is wired here. Tests should
call :func:`build_orchestrator` with their own injected model/client
instead of relying on environment-based config.
"""

from __future__ import annotations

from typing import Any

from minyoung_mah import (
    HITLChannel,
    NullHITLChannel,
    NullMemoryStore,
    NullObserver,
    Observer,
    Orchestrator,
    RoleRegistry,
    SingleModelRouter,
    ToolRegistry,
    default_resilience,
)

from .config import AptLegalConfig, get_config
from .roles import CLASSIFIER_ROLE, RESPONDER_ROLE, RETRIEVAL_PLANNER_ROLE
from .tools.mcp_adapters import make_mcp_adapters
from .tools.mcp_client import HttpxMCPClient, MCPClient


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------


_MCP_CLIENT: MCPClient | None = None


def _default_mcp_client(cfg: AptLegalConfig) -> MCPClient:
    global _MCP_CLIENT
    if _MCP_CLIENT is None:
        _MCP_CLIENT = HttpxMCPClient(cfg.mcp_server_url)
    return _MCP_CLIENT


def _default_chat_model(cfg: AptLegalConfig) -> Any:
    # Imported lazily because tests normally inject their own model and we
    # don't want to require langchain_openai at import time.
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,
        temperature=cfg.llm_temperature,
    )


# ---------------------------------------------------------------------------
# Composition root
# ---------------------------------------------------------------------------


def build_orchestrator(
    *,
    model: Any | None = None,
    mcp_client: MCPClient | None = None,
    hitl: HITLChannel | None = None,
    observer: Observer | None = None,
    config: AptLegalConfig | None = None,
) -> Orchestrator:
    """Assemble an :class:`Orchestrator` wired for apt-legal.

    All dependencies are injectable so tests can swap in fakes. The
    defaults load from environment via :class:`AptLegalConfig`.
    """
    cfg = config or get_config()

    chat_model = model if model is not None else _default_chat_model(cfg)
    client = mcp_client if mcp_client is not None else _default_mcp_client(cfg)

    role_reg = RoleRegistry.of(
        CLASSIFIER_ROLE, RETRIEVAL_PLANNER_ROLE, RESPONDER_ROLE
    )
    tool_reg = ToolRegistry.of(*make_mcp_adapters(client))

    return Orchestrator(
        role_registry=role_reg,
        tool_registry=tool_reg,
        model_router=SingleModelRouter(chat_model),
        memory=NullMemoryStore(),  # privacy: no per-user persistence
        hitl=hitl or NullHITLChannel(),
        resilience=default_resilience(
            role_timeouts={
                "classifier": 10.0,
                "retrieval_planner": 15.0,
                "responder": 30.0,
            },
            fallback_timeout_s=cfg.watchdog_timeout_s,
        ),
        observer=observer or NullObserver(),
    )
