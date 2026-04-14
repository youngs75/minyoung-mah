"""Default :class:`HITLChannel` implementations.

These cover the three situations an application typically finds itself in:

- :class:`NullHITLChannel` — automated runs (CI, pipelines) where any
  ``ask`` should pick a deterministic default.
- :class:`TerminalHITLChannel` — interactive local dev.
- :class:`QueueHITLChannel` — external delivery (A2A SSE, webhooks, tests)
  where questions are queued and answers are pushed back in.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..core.types import HITLEvent, HITLResponse


# ---------------------------------------------------------------------------
# NullHITLChannel
# ---------------------------------------------------------------------------


class NullHITLChannel:
    """Answers every question with a fixed default — never blocks.

    ``notify`` is a no-op. Suitable for pipelines where HITL is optional
    and the app guarantees it will not be triggered, or for tests.
    """

    def __init__(self, default_choice: str = "") -> None:
        self._default = default_choice

    async def ask(
        self,
        question: str,  # noqa: ARG002
        options: list[str] | None = None,
        description: str | None = None,  # noqa: ARG002
        context: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> HITLResponse:
        choice = self._default
        if options and self._default not in options:
            choice = options[0]
        return HITLResponse(choice=choice, metadata={"channel": "null"})

    async def notify(self, event: HITLEvent) -> None:  # noqa: ARG002
        return None


# ---------------------------------------------------------------------------
# TerminalHITLChannel
# ---------------------------------------------------------------------------


class TerminalHITLChannel:
    """Prints the question to stdout and reads a line from stdin.

    Purposefully simple — uses :func:`asyncio.to_thread` around ``input``
    so the event loop is not blocked. Real UIs should implement their
    own channel (Rich prompt, SSE, etc.).
    """

    async def ask(
        self,
        question: str,
        options: list[str] | None = None,
        description: str | None = None,
        context: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> HITLResponse:
        prompt_lines = [question]
        if description:
            prompt_lines.append(description)
        if options:
            prompt_lines.append("선택지: " + " / ".join(options))
        prompt = "\n".join(prompt_lines) + "\n> "
        choice = await asyncio.to_thread(input, prompt)
        return HITLResponse(choice=choice.strip(), metadata={"channel": "terminal"})

    async def notify(self, event: HITLEvent) -> None:
        print(f"[{event.kind}] {event.data}")


# ---------------------------------------------------------------------------
# QueueHITLChannel
# ---------------------------------------------------------------------------


class QueueHITLChannel:
    """Asks via a queue, waits on a future for the reply.

    The application owns two coroutines: one that consumes ``pending``
    to present questions to the user, and one that calls
    :meth:`submit_answer` to unblock the waiting ``ask`` call. The channel
    is implementation-agnostic about how questions are delivered (SSE,
    WebSocket, webhook) — only the answer path goes back through
    :meth:`submit_answer`.
    """

    def __init__(self) -> None:
        self._pending: asyncio.Queue[tuple[str, asyncio.Future[HITLResponse]]] = (
            asyncio.Queue()
        )

    @property
    def pending(self) -> asyncio.Queue[tuple[str, asyncio.Future[HITLResponse]]]:
        return self._pending

    async def ask(
        self,
        question: str,
        options: list[str] | None = None,  # noqa: ARG002
        description: str | None = None,  # noqa: ARG002
        context: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> HITLResponse:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[HITLResponse] = loop.create_future()
        await self._pending.put((question, future))
        return await future

    async def submit_answer(
        self,
        future: asyncio.Future[HITLResponse],
        response: HITLResponse,
    ) -> None:
        if not future.done():
            future.set_result(response)

    async def notify(self, event: HITLEvent) -> None:  # noqa: ARG002
        return None
