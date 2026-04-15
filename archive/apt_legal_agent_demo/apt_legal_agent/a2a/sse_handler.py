"""SSE emitter + observer bridge for A2A streaming.

``SseEmitter`` is a tiny async pub/sub backed by ``asyncio.Queue``. A
single task owns one emitter; the pipeline pushes events into it while
the HTTP streaming endpoint drains them out as SSE messages.

``SseObserver`` adapts the library's :class:`Observer` protocol to an
emitter so orchestrator/step/role events flow into the SSE stream for
free. Only whitelisted event names are forwarded — internal fast-path
chatter stays off the wire.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from typing import Any, AsyncIterator

from minyoung_mah import Observer, ObserverEvent


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


_CLOSE_SENTINEL: dict[str, Any] = {"__closed__": True}


class SseEmitter:
    """Single-consumer SSE event queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._closed = False

    async def send(self, payload: dict[str, Any]) -> None:
        if self._closed:
            return
        await self._queue.put(payload)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(_CLOSE_SENTINEL)

    def is_closed(self) -> bool:
        return self._closed

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            payload = await self._queue.get()
            if payload is _CLOSE_SENTINEL:
                return
            yield payload


# ---------------------------------------------------------------------------
# Observer → emitter bridge
# ---------------------------------------------------------------------------


# Events worth forwarding. Internal timing events (tool retries, cache
# lookups, etc.) stay private to the library.
_FORWARDED_EVENTS: frozenset[str] = frozenset(
    {
        "orchestrator.run.start",
        "orchestrator.run.end",
        "orchestrator.pipeline.step.start",
        "orchestrator.pipeline.step.end",
        "orchestrator.role.invoke.start",
        "orchestrator.role.invoke.end",
        "orchestrator.tool.call.start",
        "orchestrator.tool.call.end",
    }
)


class SseObserver(Observer):
    """Forward a curated set of :class:`ObserverEvent` to an
    :class:`SseEmitter`. Events are serialized as JSON-friendly dicts."""

    def __init__(
        self,
        emitter: SseEmitter,
        *,
        forwarded_events: frozenset[str] = _FORWARDED_EVENTS,
    ) -> None:
        self._emitter = emitter
        self._forwarded = forwarded_events

    async def emit(self, event: ObserverEvent) -> None:
        if event.name not in self._forwarded:
            return
        await self._emitter.send(
            {
                "event": event.name,
                "role": event.role,
                "tool": event.tool,
                "duration_ms": event.duration_ms,
                "ok": event.ok,
                "metadata": event.metadata,
            }
        )


# ---------------------------------------------------------------------------
# HTTP streaming helper
# ---------------------------------------------------------------------------


def _jsonable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return obj


async def stream_events(emitter: SseEmitter) -> AsyncIterator[bytes]:
    """Adapt an emitter to the ``text/event-stream`` wire format.

    Each payload becomes a ``data: <json>\\n\\n`` frame. Callers wire
    this into FastAPI's ``StreamingResponse``.
    """
    async for payload in emitter:
        body = json.dumps(_jsonable(payload), ensure_ascii=False)
        yield f"data: {body}\n\n".encode("utf-8")
