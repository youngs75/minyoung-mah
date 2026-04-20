"""Standardized observer event names and built-in backends.
표준화된 observer 이벤트 이름과 내장 백엔드들.

The event name set here is the library's *Clarity* contract: every
backend (Langfuse, OTel, structlog, custom) speaks the same vocabulary,
which keeps dashboards portable when the backend changes.

여기 정의된 이벤트 이름 집합이 라이브러리의 *Clarity* 계약이다. 모든 백엔드
(Langfuse, OTel, structlog, custom)가 같은 어휘를 사용하므로 백엔드를 바꿔도
대시보드의 portability 가 유지된다.

Event name schema: ``orchestrator.<subject>.<action>``. Common fields on
:class:`ObserverEvent` are ``role``, ``tool``, ``duration_ms``, ``ok``,
plus free-form ``metadata``.

이벤트 이름 스키마: ``orchestrator.<subject>.<action>``. :class:`ObserverEvent`
의 공통 필드는 ``role``, ``tool``, ``duration_ms``, ``ok`` 와 자유 형식
``metadata``.
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
        #
        # 도구 수준 이벤트는 역할 호출 내부에서 발화한다(라이브러리의
        # ToolInvocationEngine 은 planner, coder, verifier 등 모든 역할이 공유).
        # 가상의 top-level orchestrator 동작과 헷갈리지 않도록 ``role.*`` 로
        # 이름 짓는다. *역할* 자체는 둘러싸는 ``orchestrator.role.invoke``
        # span 으로 식별하며, 개별 tool-call 이벤트의 필드로 두지 않는다
        # (엔진은 의도적으로 역할 무관하게 유지).
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
    """Return True if ``name`` is part of the standardized vocabulary.
    ``name`` 이 표준 어휘에 속하면 True 반환."""
    return name in EVENT_NAMES


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class NullObserver:
    """Drops every event. Useful in tests and CLI one-shot runs.
    모든 이벤트를 버린다. 테스트와 CLI 일회성 실행에 유용."""

    async def emit(self, event: ObserverEvent) -> None:  # noqa: ARG002
        return None


class CollectingObserver:
    """Keeps events in a list — the test-friendly observer.
    이벤트를 리스트로 보관 — 테스트 친화적인 observer.

    Tests can assert on the event trace without plugging in a real backend.
    실제 백엔드 없이 테스트가 이벤트 trace 에 대해 assert 할 수 있다.
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
    """Forwards every event to a structlog logger as a structured log line.
    모든 이벤트를 structlog logger 의 구조화 로그 라인으로 전달한다."""

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
    하나의 이벤트를 여러 observer 백엔드로 fan-out 한다.

    Individual backend failures are swallowed — Observability must never
    break a running pipeline.

    개별 백엔드 실패는 삼킨다 — Observability 가 실행 중인 파이프라인을
    절대 깨뜨려서는 안 된다.
    """

    def __init__(self, *observers: Any) -> None:
        self._observers = list(observers)

    async def emit(self, event: ObserverEvent) -> None:
        for obs in self._observers:
            try:
                await obs.emit(event)
            except Exception:  # noqa: BLE001
                pass
