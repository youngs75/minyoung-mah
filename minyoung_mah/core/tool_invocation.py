"""Tool invocation engine — parallel/serial execution with tool-level retry.

This module owns the *Safety* and *Detection* responsibilities at the tool
boundary:

- **Retry (transient failures)**: ``TIMEOUT``, ``RATE_LIMIT``, ``NETWORK``
  errors are retried with exponential backoff. ``AUTH`` and semantic errors
  surface immediately.
- **Timeout enforcement**: Each call is wrapped in ``asyncio.wait_for``.
- **Observer hooks**: ``tool.call.start``/``tool.call.end`` events are emitted
  for every attempt so dashboards can see retry count and duration.

The engine is composed from the Orchestrator; both static (``ExecuteToolsStep``-
like use) and dynamic (``delegate`` tool loop) flows share it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from pydantic import BaseModel, ValidationError

from .protocols import Observer, ToolAdapter
from .types import (
    ErrorCategory,
    ObserverEvent,
    ToolCallRequest,
    ToolResult,
    TRANSIENT_ERRORS,
)


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolRetryPolicy:
    """Tool-level retry policy applied to transient errors only.

    Semantic failures (``TOOL_ERROR``, ``PARSE_ERROR``) are passed through to
    the calling role so the LLM can react. Retrying them blindly would hide
    legitimate signals.
    """

    max_attempts: int = 3
    initial_backoff_s: float = 0.5
    backoff_multiplier: float = 2.0
    max_backoff_s: float = 8.0
    per_call_timeout_s: float = 60.0


DEFAULT_TOOL_RETRY = ToolRetryPolicy()


# ---------------------------------------------------------------------------
# Error classification helper
# ---------------------------------------------------------------------------


def classify_exception(exc: BaseException) -> ErrorCategory:
    """Best-effort exception → :class:`ErrorCategory` mapping.

    Adapters are encouraged to categorize their own failures inside
    ``ToolResult.error_category``; this helper is only a fallback for
    exceptions that escape the adapter.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return ErrorCategory.TIMEOUT
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "ratelimit" in name or "rate_limit" in msg or "429" in msg:
        return ErrorCategory.RATE_LIMIT
    if "timeout" in name or "timeout" in msg:
        return ErrorCategory.TIMEOUT
    if "auth" in name or "unauthorized" in msg or "401" in msg or "403" in msg:
        return ErrorCategory.AUTH
    if (
        "connection" in name
        or "network" in name
        or "dns" in msg
        or "econnrefused" in msg
    ):
        return ErrorCategory.NETWORK
    if isinstance(exc, ValidationError):
        return ErrorCategory.PARSE_ERROR
    return ErrorCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ToolInvocationEngine:
    """Executes tool calls with retry, timeout, and observer hooks.

    The engine does not know about LLMs or roles — it only needs adapters
    and call requests. That lets the static ``ExecuteToolsStep`` and the
    dynamic tool loop reuse the same code path.
    """

    def __init__(
        self,
        observer: Observer,
        retry: ToolRetryPolicy = DEFAULT_TOOL_RETRY,
    ) -> None:
        self._observer = observer
        self._retry = retry

    async def call_one(
        self,
        adapter: ToolAdapter,
        request: ToolCallRequest,
    ) -> ToolResult:
        """Run a single tool call with retry + timeout + observer events."""
        args_model = self._parse_args(adapter, request)
        if isinstance(args_model, ToolResult):
            return args_model  # Parse failure short-circuits retries.

        last_error: ToolResult | None = None
        backoff = self._retry.initial_backoff_s

        for attempt in range(1, self._retry.max_attempts + 1):
            await self._emit(
                "orchestrator.tool.call.start",
                tool=adapter.name,
                metadata={"attempt": attempt, "call_id": request.call_id},
            )
            start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    adapter.call(args_model),
                    timeout=self._retry.per_call_timeout_s,
                )
            except asyncio.TimeoutError:
                result = ToolResult(
                    ok=False,
                    value=None,
                    error=f"tool '{adapter.name}' timed out after "
                    f"{self._retry.per_call_timeout_s}s",
                    error_category=ErrorCategory.TIMEOUT,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
            except Exception as exc:  # noqa: BLE001 — adapters may raise anything
                result = ToolResult(
                    ok=False,
                    value=None,
                    error=f"{type(exc).__name__}: {exc}",
                    error_category=classify_exception(exc),
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            await self._emit(
                "orchestrator.tool.call.end",
                tool=adapter.name,
                ok=result.ok,
                duration_ms=result.duration_ms,
                metadata={
                    "attempt": attempt,
                    "call_id": request.call_id,
                    "error_category": (
                        result.error_category.name if result.error_category else None
                    ),
                },
            )

            if result.ok:
                return result

            last_error = result
            if (
                result.error_category not in TRANSIENT_ERRORS
                or attempt >= self._retry.max_attempts
            ):
                return result

            await self._emit(
                "orchestrator.resilience.retry",
                tool=adapter.name,
                metadata={
                    "attempt": attempt,
                    "next_backoff_s": backoff,
                    "error_category": result.error_category.name,
                },
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * self._retry.backoff_multiplier, self._retry.max_backoff_s)

        assert last_error is not None  # the loop always produces at least one
        return last_error

    async def call_parallel(
        self,
        pairs: Iterable[tuple[ToolAdapter, ToolCallRequest]],
    ) -> list[ToolResult]:
        """Fan out multiple tool calls via ``asyncio.gather``.

        Results are returned in the same order as ``pairs``. Individual
        failures are kept as ``ToolResult(ok=False, ...)`` — the gather does
        not short-circuit.
        """
        tasks = [self.call_one(adapter, req) for adapter, req in pairs]
        return list(await asyncio.gather(*tasks))

    # -- helpers --------------------------------------------------------

    def _parse_args(
        self,
        adapter: ToolAdapter,
        request: ToolCallRequest,
    ) -> BaseModel | ToolResult:
        try:
            return adapter.arg_schema.model_validate(request.args)
        except ValidationError as exc:
            return ToolResult(
                ok=False,
                value=None,
                error=f"argument validation failed for '{adapter.name}': {exc}",
                error_category=ErrorCategory.PARSE_ERROR,
                duration_ms=0,
                metadata={"call_id": request.call_id},
            )

    async def _emit(
        self,
        name: str,
        *,
        tool: str | None = None,
        ok: bool | None = None,
        duration_ms: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        try:
            await self._observer.emit(
                ObserverEvent(
                    name=name,
                    timestamp=datetime.now(timezone.utc),
                    tool=tool,
                    ok=ok,
                    duration_ms=duration_ms,
                    metadata=metadata or {},
                )
            )
        except Exception:  # noqa: BLE001
            # Observer failures must never break the tool call.
            pass
