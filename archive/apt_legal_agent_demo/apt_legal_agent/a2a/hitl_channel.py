"""A2A-aware HITL channel.

apt-legal is a single-turn Q&A agent: users ask, the agent answers
without mid-flow clarification. So ``ask`` is wired to auto-select the
first option (or return an empty choice) rather than blocking. ``notify``
forwards to the per-task SSE emitter if one is attached, letting the
streaming endpoint surface HITL events as SSE messages.
"""

from __future__ import annotations

from typing import Any

from minyoung_mah import HITLChannel, HITLEvent, HITLResponse

from .sse_handler import SseEmitter


class A2AHITLChannel(HITLChannel):
    def __init__(self, task_id: str, sse_emitter: SseEmitter | None = None) -> None:
        self._task_id = task_id
        self._sse = sse_emitter

    async def ask(
        self,
        question: str,
        options: list[str] | None = None,
        description: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> HITLResponse:
        # apt-legal never interrupts mid-flow for clarification. If a role
        # calls `ask` we auto-pick the first option so the pipeline can
        # continue. This is the expected behaviour per design doc 03 §5.
        if options:
            return HITLResponse(choice=options[0], metadata={"auto": True})
        return HITLResponse(choice="", metadata={"auto": True})

    async def notify(self, event: HITLEvent) -> None:
        if self._sse is None:
            return
        await self._sse.send(
            {
                "event": f"hitl.{event.kind}",
                "task_id": self._task_id,
                "data": event.data,
            }
        )
