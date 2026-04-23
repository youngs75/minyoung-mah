"""Tool invocation engine — parallel/serial execution with tool-level retry.
도구 호출 엔진 — 도구 수준 재시도가 포함된 병렬/직렬 실행기.

This module owns the *Safety* and *Detection* responsibilities at the tool
boundary:

이 모듈은 도구 경계에서의 *Safety* 와 *Detection* 책임을 가진다:

- **Retry (transient failures)**: ``TIMEOUT``, ``RATE_LIMIT``, ``NETWORK``
  errors are retried with exponential backoff. ``AUTH`` and semantic errors
  surface immediately.
- **재시도(일시적 실패)**: ``TIMEOUT``, ``RATE_LIMIT``, ``NETWORK`` 오류는
  지수 백오프로 재시도. ``AUTH`` 및 의미상 오류는 즉시 surface.
- **Timeout enforcement**: Each call is wrapped in ``asyncio.wait_for``.
- **타임아웃 강제**: 각 호출은 ``asyncio.wait_for`` 로 감싼다.
- **Observer hooks**: ``tool.call.start``/``tool.call.end`` events are emitted
  for every attempt so dashboards can see retry count and duration.
- **Observer 훅**: 모든 시도마다 ``tool.call.start``/``tool.call.end`` 이벤트를
  emit 하여 대시보드에서 재시도 횟수와 지속시간을 볼 수 있게 한다.

The engine is composed from the Orchestrator; both static (``ExecuteToolsStep``-
like use) and dynamic (``delegate`` tool loop) flows share it.

이 엔진은 Orchestrator 가 조립해서 사용하며, 정적(``ExecuteToolsStep`` 류)
흐름과 동적(``delegate`` 도구 루프) 흐름이 모두 공유한다.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from pydantic import BaseModel, ValidationError

from ..resilience.progress_watchdog import signal_current_progress
from .protocols import Observer, ToolAdapter
from .types import (
    ErrorCategory,
    ObserverEvent,
    ToolCallRequest,
    ToolResult,
    TRANSIENT_ERRORS,
)


def _compute_args_hash(tool_name: str, args: dict | BaseModel) -> int:
    """Deterministic hash of ``(tool_name, args)`` for progress dedup.

    Uses ``json.dumps(sort_keys=True)`` so nested dicts hash consistently
    across invocations. Falls back to ``repr`` if JSON serialization fails
    (e.g. the adapter's arg model embeds a non-JSON type).
    """
    if isinstance(args, BaseModel):
        try:
            payload = args.model_dump_json()
        except Exception:  # noqa: BLE001
            payload = repr(args)
    else:
        try:
            payload = json.dumps(args, sort_keys=True, default=str)
        except Exception:  # noqa: BLE001
            payload = repr(args)
    return hash((tool_name, payload))


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolRetryPolicy:
    """Tool-level retry policy applied to transient errors only.
    일시적 오류에만 적용되는 도구 수준 재시도 정책.

    Semantic failures (``TOOL_ERROR``, ``PARSE_ERROR``) are passed through to
    the calling role so the LLM can react. Retrying them blindly would hide
    legitimate signals.

    의미상 실패(``TOOL_ERROR``, ``PARSE_ERROR``)는 호출 측 역할로 그대로
    전달되어 LLM 이 반응할 수 있게 한다. 무작정 재시도하면 정상적인 신호를
    가려버린다.
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
    예외 → :class:`ErrorCategory` 의 best-effort 매핑.

    Adapters are encouraged to categorize their own failures inside
    ``ToolResult.error_category``; this helper is only a fallback for
    exceptions that escape the adapter.

    Adapter 가 직접 ``ToolResult.error_category`` 에 자기 실패를 분류하는 것이
    권장된다. 이 헬퍼는 adapter 를 빠져나온 예외에 대한 폴백일 뿐이다.
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
    재시도·타임아웃·observer 훅이 포함된 도구 호출 실행기.

    The engine does not know about LLMs or roles — it only needs adapters
    and call requests. That lets the static ``ExecuteToolsStep`` and the
    dynamic tool loop reuse the same code path.

    엔진은 LLM 이나 역할을 알지 못한다 — adapter 와 호출 요청만 있으면 된다.
    덕분에 정적 ``ExecuteToolsStep`` 과 동적 도구 루프가 같은 코드 경로를
    재사용할 수 있다.
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
        """Run a single tool call with retry + timeout + observer events.
        단일 도구 호출을 재시도·타임아웃·observer 이벤트와 함께 실행."""
        args_model = self._parse_args(adapter, request)
        if isinstance(args_model, ToolResult):
            # Parse failure short-circuits retries. — 인자 파싱 실패는 재시도 없이 즉시 반환.
            return args_model

        last_error: ToolResult | None = None
        backoff = self._retry.initial_backoff_s

        for attempt in range(1, self._retry.max_attempts + 1):
            await self._emit(
                "role.tool.call.start",
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
            except Exception as exc:  # noqa: BLE001 — adapters may raise anything / adapter 는 무엇이든 raise 할 수 있음
                result = ToolResult(
                    ok=False,
                    value=None,
                    error=f"{type(exc).__name__}: {exc}",
                    error_category=classify_exception(exc),
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            await self._emit(
                "role.tool.call.end",
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
                # Progress signal — novel (tool_name, args) success extends
                # the enclosing role invocation's watchdog deadline.
                try:
                    signal_current_progress(
                        _compute_args_hash(adapter.name, args_model)
                    )
                except Exception:  # noqa: BLE001
                    # Watchdog failures must never break a successful tool.
                    pass
                return result

            last_error = result
            if (
                result.error_category not in TRANSIENT_ERRORS
                or attempt >= self._retry.max_attempts
            ):
                return result

            await self._emit(
                "role.resilience.retry",
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
        ``asyncio.gather`` 로 여러 도구 호출을 fan-out 한다.

        Results are returned in the same order as ``pairs``. Individual
        failures are kept as ``ToolResult(ok=False, ...)`` — the gather does
        not short-circuit.

        결과는 ``pairs`` 와 같은 순서로 반환된다. 개별 실패는
        ``ToolResult(ok=False, ...)`` 로 유지되며, gather 는 short-circuit
        하지 않는다.
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
            # observer 실패가 도구 호출을 깨뜨려서는 안 된다.
            pass
