"""Boundary marker + post-compact 메시지 빌더 단위 테스트."""

from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from minyoung_mah.context import (
    CompactBoundaryMessage,
    build_post_compact_messages,
    extract_messages_after_boundary,
    is_boundary_message,
)
from minyoung_mah.context.boundary import is_compact_summary


def test_boundary_now_creates_iso_timestamp():
    b = CompactBoundaryMessage.now(
        pre_compact_token_count=1000,
        pre_compact_message_count=50,
        preserved_tail_count=20,
    )
    assert b.timestamp.endswith("+00:00")
    assert b.reason == "auto"


def test_boundary_to_message_carries_metadata():
    b = CompactBoundaryMessage.now(
        pre_compact_token_count=1000,
        pre_compact_message_count=50,
        preserved_tail_count=20,
        reason="manual",
    )
    msg = b.to_message()
    assert isinstance(msg, SystemMessage)
    assert msg.additional_kwargs["compact_boundary"] is True
    assert msg.additional_kwargs["pre_compact_token_count"] == 1000
    assert msg.additional_kwargs["reason"] == "manual"
    assert "이 시점 이전의 대화는" in msg.content


def test_is_boundary_message_detects():
    b = CompactBoundaryMessage.now(
        pre_compact_token_count=1, pre_compact_message_count=1, preserved_tail_count=0
    )
    assert is_boundary_message(b.to_message()) is True
    assert is_boundary_message(SystemMessage(content="regular system")) is False
    assert is_boundary_message(HumanMessage(content="user")) is False


def test_extract_messages_after_boundary_no_boundary():
    msgs = [
        SystemMessage(content="sys"),
        HumanMessage(content="hi"),
        AIMessage(content="hello"),
    ]
    assert extract_messages_after_boundary(msgs) == msgs


def test_extract_messages_after_boundary_one_boundary():
    boundary = CompactBoundaryMessage.now(
        pre_compact_token_count=1, pre_compact_message_count=3, preserved_tail_count=2
    ).to_message()
    msgs = [
        SystemMessage(content="sys"),
        HumanMessage(content="hi"),
        boundary,
        HumanMessage(content="summary text"),
        AIMessage(content="ack"),
    ]
    after = extract_messages_after_boundary(msgs)
    assert len(after) == 2
    assert isinstance(after[0], HumanMessage)


def test_extract_messages_after_boundary_multiple_boundaries():
    """가장 *최근* boundary 이후만 반환."""
    b1 = CompactBoundaryMessage.now(
        pre_compact_token_count=1, pre_compact_message_count=1, preserved_tail_count=0
    ).to_message()
    b2 = CompactBoundaryMessage.now(
        pre_compact_token_count=2, pre_compact_message_count=5, preserved_tail_count=2
    ).to_message()
    msgs = [
        SystemMessage(content="sys"),
        b1,
        HumanMessage(content="early summary"),
        AIMessage(content="response"),
        b2,
        HumanMessage(content="late summary"),
        AIMessage(content="latest response"),
    ]
    after = extract_messages_after_boundary(msgs)
    assert len(after) == 2
    assert after[0].content == "late summary"


def test_build_post_compact_messages_full_layout():
    head = [SystemMessage(content="sys"), HumanMessage(content="user req")]
    boundary = CompactBoundaryMessage.now(
        pre_compact_token_count=1000,
        pre_compact_message_count=50,
        preserved_tail_count=2,
    )
    tail = [
        AIMessage(content="recent ai"),
        HumanMessage(content="latest user"),
    ]
    result = build_post_compact_messages(
        head_to_preserve=head,
        boundary=boundary,
        summary_text="this is the summary",
        preserved_tail=tail,
    )
    # head(2) + boundary(1) + summary(1) + tail(2) = 6
    assert len(result) == 6
    assert isinstance(result[0], SystemMessage)
    assert isinstance(result[1], HumanMessage)
    assert is_boundary_message(result[2])
    assert isinstance(result[3], HumanMessage)
    assert result[3].content == "this is the summary"
    assert is_compact_summary(result[3]) is True
    assert result[4] is tail[0]
    assert result[5] is tail[1]


def test_build_post_compact_messages_summary_marked():
    boundary = CompactBoundaryMessage.now(
        pre_compact_token_count=1, pre_compact_message_count=1, preserved_tail_count=0
    )
    result = build_post_compact_messages(
        head_to_preserve=[],
        boundary=boundary,
        summary_text="summary",
        preserved_tail=[],
    )
    summary_msg = result[1]
    assert summary_msg.additional_kwargs.get("compact_summary") is True
    assert summary_msg.additional_kwargs.get("boundary_timestamp") == boundary.timestamp
