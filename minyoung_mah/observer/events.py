"""Standardized observer event names and built-in backends.

The event name set here is the library's *Clarity* contract: every
backend (Langfuse, OTel, structlog, custom) speaks the same vocabulary,
which keeps dashboards portable when the backend changes.

Event name schema: ``orchestrator.<subject>.<action>``. Common fields on
:class:`ObserverEvent` are ``role``, ``tool``, ``duration_ms``, ``ok``,
plus free-form ``metadata``.
"""

from __future__ import annotations

from typing import Any

import structlog

from ..core.types import ObserverEvent


# ---------------------------------------------------------------------------
# Canonical event names
# ---------------------------------------------------------------------------


EVENT_NAMES: frozenset[str] = frozenset(
    {
        "orchestrator.run.start",
        "orchestrator.run.end",
        "orchestrator.pipeline.step.start",
        "orchestrator.pipeline.step.end",
        "orchestrator.role.invoke.start",
        "orchestrator.role.invoke.end",
        # Tool-level events fire from inside a role invocation (the library's
        # ToolInvocationEngine is shared across every role — planner, coder,
        # verifier, etc). Name them ``role.*`` so they are not mistaken for
        # actions of a hypothetical top-level orchestrator. The *role*
        # itself is identified via the enclosing ``orchestrator.role.invoke``
        # span, not a field on each tool-call event (the engine intentionally
        # stays role-agnostic).
        "role.tool.call.start",
        "role.tool.call.end",
        "role.resilience.retry",
        "orchestrator.hitl.ask",
        "orchestrator.hitl.respond",
        "orchestrator.memory.read",
        "orchestrator.memory.write",
        "orchestrator.resilience.escalate",
    }
)


def is_canonical(name: str) -> bool:
    """Return True if ``name`` is part of the standardized vocabulary."""
    return name in EVENT_NAMES


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class NullObserver:
    """Drops every event. Useful in tests and CLI one-shot runs."""

    async def emit(self, event: ObserverEvent) -> None:  # noqa: ARG002
        return None


class CollectingObserver:
    """Keeps events in a list — the test-friendly observer.

    Tests can assert on the event trace without plugging in a real backend.
    """

    def __init__(self) -> None:
        self.events: list[ObserverEvent] = []

    async def emit(self, event: ObserverEvent) -> None:
        self.events.append(event)

    def names(self) -> list[str]:
        return [e.name for e in self.events]

    def clear(self) -> None:
        self.events.clear()


class StructlogObserver:
    """Forwards every event to a structlog logger as a structured log line."""

    def __init__(self, logger: structlog.BoundLogger | None = None) -> None:
        self._log = logger or structlog.get_logger("minyoung_mah.observer")

    async def emit(self, event: ObserverEvent) -> None:
        payload: dict[str, Any] = {
            "timestamp": event.timestamp.isoformat(),
            "role": event.role,
            "tool": event.tool,
            "duration_ms": event.duration_ms,
            "ok": event.ok,
            **event.metadata,
        }
        self._log.info(event.name, **{k: v for k, v in payload.items() if v is not None})


class CompositeObserver:
    """Fans out one event to several observer backends.

    Individual backend failures are swallowed — Observability must never
    break a running pipeline.
    """

    def __init__(self, *observers: Any) -> None:
        self._observers = list(observers)

    async def emit(self, event: ObserverEvent) -> None:
        for obs in self._observers:
            try:
                await obs.emit(event)
            except Exception:  # noqa: BLE001
                pass
