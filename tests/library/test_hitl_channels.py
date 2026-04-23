"""Unit tests for built-in :class:`HITLChannel` implementations.
:class:`HITLChannel` 기본 구현체 단위 테스트.
"""

from __future__ import annotations

import asyncio

import pytest

from minyoung_mah import HITLEvent, NullHITLChannel, QueueHITLChannel


@pytest.mark.asyncio
async def test_null_channel_notify_is_no_op() -> None:
    # NullHITLChannel keeps notify as a no-op by design — automated runs
    # should never need to surface HITL events.
    # NullHITLChannel 의 notify 는 의도적으로 no-op — 자동 실행은 HITL 이벤트를
    # 노출할 필요가 없음.
    channel = NullHITLChannel()
    await channel.notify(HITLEvent(kind="role_start", data={"role": "x"}))


@pytest.mark.asyncio
async def test_queue_channel_notify_pushes_to_notifications() -> None:
    # The application reads ``channel.notifications`` and forwards events
    # to its user surface (SSE stream, webhook, log, etc.).
    # 애플리케이션이 ``channel.notifications`` 를 읽어 사용자 surface(SSE,
    # webhook, 로그 등)로 전달.
    channel = QueueHITLChannel()
    event = HITLEvent(kind="progress", data={"step": "lookup"})
    await channel.notify(event)
    delivered = await asyncio.wait_for(channel.notifications.get(), timeout=0.1)
    assert delivered is event


@pytest.mark.asyncio
async def test_queue_channel_notify_supports_critic_escalate_kind() -> None:
    # The ``critic_escalate`` kind was added in 0.1.8 for sufficiency loops
    # that ask a human to review when the LLM critic verdict is uncertain.
    # ``critic_escalate`` kind 는 0.1.8 에서 sufficiency loop 가 LLM critic
    # verdict 가 불확실할 때 사람 검토를 요청하기 위해 추가됨.
    channel = QueueHITLChannel()
    event = HITLEvent(
        kind="critic_escalate",
        data={"verdict": "escalate_hitl", "reason": "동일 사이클 반복"},
    )
    await channel.notify(event)
    delivered = await asyncio.wait_for(channel.notifications.get(), timeout=0.1)
    assert delivered.kind == "critic_escalate"
    assert delivered.data["verdict"] == "escalate_hitl"


@pytest.mark.asyncio
async def test_queue_channel_pending_and_notifications_are_independent() -> None:
    # ``ask`` puts a (question, future) pair on ``pending``; ``notify`` puts a
    # one-way event on ``notifications``. The two queues never cross.
    # ``ask`` 는 ``pending`` 에 (질문, future) 쌍을 넣고, ``notify`` 는
    # ``notifications`` 에 단방향 이벤트를 넣는다. 두 큐는 절대 섞이지 않는다.
    channel = QueueHITLChannel()
    ask_task = asyncio.create_task(channel.ask("계속할까요?", options=["yes", "no"]))
    # Yield once so ``ask`` reaches ``_pending.put(...)`` before we assert.
    # Without this, the create_task above hasn't run yet on the event loop.
    # ``ask`` 가 ``_pending.put(...)`` 에 도달하도록 한 번 yield. 이게 없으면
    # 위의 create_task 가 아직 실행되지 않아 assert 가 실패한다.
    await asyncio.sleep(0)
    await channel.notify(HITLEvent(kind="progress", data={"step": "halfway"}))

    assert channel.notifications.qsize() == 1
    assert channel.pending.qsize() == 1

    # Drain the ask path so the test does not leak the pending future.
    # 테스트가 pending future 를 누수하지 않도록 ask 경로를 비워준다.
    question, future = await channel.pending.get()
    assert question == "계속할까요?"
    from minyoung_mah import HITLResponse

    await channel.submit_answer(future, HITLResponse(choice="yes"))
    response = await ask_task
    assert response.choice == "yes"
