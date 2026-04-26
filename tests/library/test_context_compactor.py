"""compactor.compact_messages 단위 테스트 — mock LLM 으로."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from minyoung_mah.context import compact_messages, is_boundary_message
from minyoung_mah.context.boundary import is_compact_summary
from minyoung_mah.context.compactor import (
    _adjust_tail_for_pair_safety,
    _serialize_messages_for_summary,
    _split_head_and_tail,
)


class _FakeChatModel:
    """compact_model 으로 사용. ainvoke 가 미리 박은 응답 반환."""

    def __init__(self, response_text: str = "<analysis>thinking</analysis>\n<summary>compact summary body</summary>"):
        self.response_text = response_text
        self.invocations: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.invocations.append(list(messages))
        return AIMessage(content=self.response_text)


def _build_long_conversation(n: int) -> list[BaseMessage]:
    msgs: list[BaseMessage] = [
        SystemMessage(content="you are agent"),
        HumanMessage(content="initial user request"),
    ]
    for i in range(n):
        msgs.append(AIMessage(content=f"ai turn {i}"))
        msgs.append(HumanMessage(content=f"user turn {i}"))
    return msgs


# ── _split_head_and_tail ──────────────────────────────────────────────────────


def test_split_basic():
    msgs = _build_long_conversation(10)  # 2 + 20 = 22
    head, middle, tail = _split_head_and_tail(msgs, head_size=2, tail_size=5)
    assert len(head) == 2
    assert len(tail) == 5
    assert len(middle) == 22 - 2 - 5


def test_split_returns_full_when_too_short():
    msgs = _build_long_conversation(2)  # 2 + 4 = 6
    head, middle, tail = _split_head_and_tail(msgs, head_size=2, tail_size=10)
    # head + tail (12) >= 6 → middle 비어있음
    assert head == msgs
    assert middle == []
    assert tail == []


# ── _adjust_tail_for_pair_safety ─────────────────────────────────────────────


def test_pair_safety_pulls_ai_to_tail():
    """tail 시작이 ToolMessage 면 짝 AIMessage 를 middle 에서 tail 로 이동."""
    ai_with_tool = AIMessage(
        content="",
        tool_calls=[{"name": "x", "args": {}, "id": "t1", "type": "tool_call"}],
    )
    middle = [HumanMessage(content="m1"), ai_with_tool]
    tail = [
        ToolMessage(content="result", tool_call_id="t1"),
        AIMessage(content="next"),
    ]
    new_tail, new_middle = _adjust_tail_for_pair_safety(tail, middle)
    # AIMessage 가 tail 로 이동
    assert ai_with_tool in new_tail
    assert ai_with_tool not in new_middle
    # tail 이 AIMessage(tool_use) 부터 시작
    assert new_tail[0] is ai_with_tool


def test_pair_safety_no_op_when_safe():
    middle = [HumanMessage(content="m1"), AIMessage(content="ai")]
    tail = [HumanMessage(content="user latest")]
    new_tail, new_middle = _adjust_tail_for_pair_safety(tail, middle)
    assert new_tail == tail
    assert new_middle == middle


def test_pair_safety_empty_inputs():
    new_tail, new_middle = _adjust_tail_for_pair_safety([], [])
    assert new_tail == []
    assert new_middle == []


# ── compact_messages 본체 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compact_messages_happy_path():
    msgs = _build_long_conversation(20)  # 42 messages
    fake = _FakeChatModel()
    output = await compact_messages(
        messages=msgs,
        compact_model=fake,
        tokens_before=10_000,
        head_size=2,
        tail_size=5,
    )
    # head + boundary + summary + tail = 9
    assert len(output.new_messages) == 2 + 1 + 1 + 5
    # head 보존
    assert isinstance(output.new_messages[0], SystemMessage)
    assert isinstance(output.new_messages[1], HumanMessage)
    # boundary
    assert is_boundary_message(output.new_messages[2])
    # summary
    assert is_compact_summary(output.new_messages[3])
    assert "compact summary body" in output.new_messages[3].content
    # tail (마지막 5)
    assert output.new_messages[-5:] == msgs[-5:]
    # 출력 metadata
    assert output.summarized_count == 42 - 2 - 5
    assert output.head_count == 2
    assert output.tail_count == 5


@pytest.mark.asyncio
async def test_compact_messages_invokes_with_no_tools_preamble():
    msgs = _build_long_conversation(10)
    fake = _FakeChatModel()
    await compact_messages(
        messages=msgs,
        compact_model=fake,
        tokens_before=5000,
        head_size=2,
        tail_size=2,
    )
    # 호출이 1번 + system 메시지에 NO_TOOLS_PREAMBLE 포함
    assert len(fake.invocations) == 1
    sys_msg = fake.invocations[0][0]
    assert isinstance(sys_msg, SystemMessage)
    assert "Do NOT call any tools" in sys_msg.content


@pytest.mark.asyncio
async def test_compact_messages_returns_original_when_no_middle():
    msgs = _build_long_conversation(2)  # 6 messages
    fake = _FakeChatModel()
    output = await compact_messages(
        messages=msgs,
        compact_model=fake,
        tokens_before=500,
        head_size=2,
        tail_size=10,  # 10 > 4 → middle 빈 list
    )
    assert output.summarized_count == 0
    assert output.new_messages == msgs
    # LLM 호출도 안 일어남
    assert len(fake.invocations) == 0


@pytest.mark.asyncio
async def test_compact_messages_raises_on_empty_summary():
    msgs = _build_long_conversation(20)
    fake = _FakeChatModel(response_text="")  # 빈 응답
    with pytest.raises(RuntimeError, match="empty summary"):
        await compact_messages(
            messages=msgs,
            compact_model=fake,
            tokens_before=10_000,
            head_size=2,
            tail_size=5,
        )


@pytest.mark.asyncio
async def test_compact_messages_raises_on_invoke_failure():
    class _FailingModel:
        async def ainvoke(self, messages: list[BaseMessage]) -> Any:
            raise ValueError("API down")

    msgs = _build_long_conversation(20)
    with pytest.raises(RuntimeError, match="compact LLM invoke failed"):
        await compact_messages(
            messages=msgs,
            compact_model=_FailingModel(),
            tokens_before=10_000,
            head_size=2,
            tail_size=5,
        )


# ── _serialize_messages_for_summary ─────────────────────────────────────────


def test_serialize_includes_role_label():
    text = _serialize_messages_for_summary(
        [HumanMessage(content="hi"), AIMessage(content="hello")]
    )
    assert "=== Human ===" in text
    assert "=== AI ===" in text
    assert "hi" in text
    assert "hello" in text


def test_serialize_includes_tool_calls():
    text = _serialize_messages_for_summary(
        [
            AIMessage(
                content="thinking",
                tool_calls=[{"name": "read", "args": {"path": "/tmp/x"}, "id": "t1", "type": "tool_call"}],
            )
        ]
    )
    assert "tool_calls:" in text
    assert "read" in text


def test_serialize_includes_tool_message_id():
    text = _serialize_messages_for_summary(
        [ToolMessage(content="result", tool_call_id="t1")]
    )
    assert "[tool_call_id: t1]" in text
