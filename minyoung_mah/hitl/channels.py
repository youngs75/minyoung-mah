"""Default :class:`HITLChannel` implementations.
:class:`HITLChannel` 기본 구현체들.

These cover the three situations an application typically finds itself in:

애플리케이션이 보통 마주치는 세 가지 상황을 커버한다:

- :class:`NullHITLChannel` — automated runs (CI, pipelines) where any
  ``ask`` should pick a deterministic default.
- :class:`NullHITLChannel` — 자동 실행(CI, 파이프라인)에서 모든 ``ask`` 가
  결정론적 기본값을 선택해야 할 때.
- :class:`TerminalHITLChannel` — interactive local dev.
- :class:`TerminalHITLChannel` — 로컬 개발 시 대화형 사용.
- :class:`QueueHITLChannel` — external delivery (A2A SSE, webhooks, tests)
  where questions are queued and answers are pushed back in.
- :class:`QueueHITLChannel` — 외부 전달(A2A SSE, webhook, 테스트) 환경에서
  질문을 큐에 쌓고 답변을 다시 밀어넣는 방식.
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
    모든 질문에 고정 기본값으로 응답 — 절대 블로킹하지 않는다.

    ``notify`` is a no-op. Suitable for pipelines where HITL is optional
    and the app guarantees it will not be triggered, or for tests.

    ``notify`` 는 no-op. HITL 이 optional 이고 앱이 트리거되지 않음을 보장하는
    파이프라인이나 테스트에 적합.
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
    질문을 stdout 에 출력하고 stdin 에서 한 줄을 읽는다.

    Purposefully simple — uses :func:`asyncio.to_thread` around ``input``
    so the event loop is not blocked. Real UIs should implement their
    own channel (Rich prompt, SSE, etc.).

    의도적으로 단순한 구현 — 이벤트 루프가 블로킹되지 않도록 ``input`` 주위를
    :func:`asyncio.to_thread` 로 감싼다. 실제 UI 는 자체 채널(Rich prompt, SSE
    등)을 구현해야 한다.
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
    큐를 통해 질문하고 future 로 응답을 기다린다.

    The application owns two coroutines: one that consumes ``pending``
    to present questions to the user, and one that calls
    :meth:`submit_answer` to unblock the waiting ``ask`` call. The channel
    is implementation-agnostic about how questions are delivered (SSE,
    WebSocket, webhook) — only the answer path goes back through
    :meth:`submit_answer`.

    애플리케이션이 두 개의 코루틴을 소유한다: 하나는 ``pending`` 을 소비해
    사용자에게 질문을 보여주고, 다른 하나는 :meth:`submit_answer` 를 호출해
    대기 중인 ``ask`` 를 풀어준다. 채널은 질문 전달 방식(SSE, WebSocket,
    webhook 등)에 대해 구현 중립적이며, 응답 경로만 :meth:`submit_answer` 를
    통한다.
    """

    def __init__(self) -> None:
        self._pending: asyncio.Queue[tuple[str, asyncio.Future[HITLResponse]]] = (
            asyncio.Queue()
        )
        # Notifications are one-way (no reply expected). The application
        # consumes this queue in parallel to ``pending`` and forwards each
        # event to the user surface (SSE stream, webhook, log, etc.).
        # 알림은 단방향(응답 없음). 애플리케이션이 ``pending`` 과 병렬로 이 큐를
        # 소비해 사용자 surface(SSE 스트림, webhook, 로그 등)로 전달한다.
        self._notifications: asyncio.Queue[HITLEvent] = asyncio.Queue()

    @property
    def pending(self) -> asyncio.Queue[tuple[str, asyncio.Future[HITLResponse]]]:
        return self._pending

    @property
    def notifications(self) -> asyncio.Queue[HITLEvent]:
        return self._notifications

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

    async def notify(self, event: HITLEvent) -> None:
        await self._notifications.put(event)
