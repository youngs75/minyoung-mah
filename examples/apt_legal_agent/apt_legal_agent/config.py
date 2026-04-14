"""Runtime configuration for the apt-legal agent.

Environment variables:

- ``APT_LEGAL_LLM_MODEL`` (default: ``gpt-4o``)
- ``APT_LEGAL_LLM_API_KEY`` — required unless a dependency-injected router is used
- ``APT_LEGAL_LLM_TEMPERATURE`` (default: ``0.2``)
- ``APT_LEGAL_MCP_SERVER_URL`` — base URL for the ``apt-legal-mcp`` server
- ``APT_LEGAL_LANGFUSE_ENABLED`` (default: ``false``)
- ``APT_LEGAL_WATCHDOG_TIMEOUT_S`` (default: ``45``) — tuned to stay under the
  A2A task 60s ceiling
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AptLegalConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APT_LEGAL_",
        env_file=".env",
        extra="ignore",
    )

    llm_model: str = "gpt-4o"
    llm_api_key: str | None = None
    llm_temperature: float = 0.2

    mcp_server_url: str = "http://localhost:8001/mcp"

    langfuse_enabled: bool = False
    watchdog_timeout_s: float = 45.0


@lru_cache(maxsize=1)
def get_config() -> AptLegalConfig:
    return AptLegalConfig()
