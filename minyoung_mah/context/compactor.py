"""LLM summarize 호출 본체.

Claude Code 의 ``compactConversation`` (compact.ts:387-763) +
``streamCompactSummary`` (1136-1396) 핵심 흐름 포팅. 단순화 — chunked
streaming 은 안 하고 ainvoke 한 번에 받음 (작은 시나리오에서 충분, 큰
시나리오는 후속 PR 에서 streaming 추가 가능).

핵심 단계:
1. ``head_to_preserve`` (보통 [System, 첫 Human]) 와 ``preserved_tail``
   (가장 최근 N) 을 분리
2. summarize 대상 messages = head + tail 외 *중간 부분*
3. ``compact_model`` 에게 BASE_COMPACT_PROMPT 와 함께 ainvoke 호출
4. 응답에서 <summary> 본문 추출
5. boundary marker + summary message 빌드
6. 결과 반환 (head + boundary + summary + tail)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from minyoung_mah.context.boundary import (
    CompactBoundaryMessage,
    build_post_compact_messages,
)
from minyoung_mah.context.prompts import extract_summary_text, get_compact_prompt

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

log = logging.getLogger("minyoung_mah.context.compactor")


@dataclass
class CompactionOutput:
    """``compact_messages`` 의 raw 결과. ``ContextManager`` 가 이걸 받아서
    Observer 발화 + circuit breaker 처리."""

    new_messages: list[BaseMessage]
    summary_text: str
    boundary: CompactBoundaryMessage
    tokens_before: int  # 입력 시점 추정 토큰 (caller 가 측정)
    head_count: int
    tail_count: int
    summarized_count: int


def _split_head_and_tail(
    messages: list[BaseMessage],
    head_size: int,
    tail_size: int,
) -> tuple[list[BaseMessage], list[BaseMessage], list[BaseMessage]]:
    """messages 를 (head, middle, tail) 로 분할.

    head: 처음 N 개 (system + 첫 user 보존)
    tail: 마지막 M 개 (가장 최근 그대로 보존)
    middle: 그 사이 — 요약 대상

    head + tail >= len(messages) 면 middle 빈 list (요약할 게 없음).
    """
    n = len(messages)
    if head_size + tail_size >= n:
        return list(messages), [], []
    head = list(messages[:head_size])
    tail = list(messages[n - tail_size :])
    middle = list(messages[head_size : n - tail_size])
    return head, middle, tail


def _adjust_tail_for_pair_safety(
    tail: list[BaseMessage],
    middle: list[BaseMessage],
) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """``tail`` 의 첫 메시지가 ``ToolMessage`` 면 짝 ``AIMessage(tool_use)``
    가 ``middle`` 의 마지막에 있을 가능성 — Anthropic strict pair 보존
    위해 그 AIMessage 를 ``tail`` 로 이동.

    반대 케이스도 — ``middle`` 의 마지막이 ``AIMessage(tool_use)`` 인데
    그 짝 ``ToolMessage`` 가 tail 에 있으면 AIMessage 도 tail 로 이동.

    이 함수는 *방어적* — Compactor 가 tail 을 보존할 때 짝이 깨지지
    않게 한 번 더 정리. tail 이 비어 있으면 그대로.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    if not tail or not middle:
        return tail, middle

    # tail 의 시작이 ToolMessage 면 그 짝 AIMessage 찾기
    first_tail = tail[0]
    if isinstance(first_tail, ToolMessage):
        tcid = getattr(first_tail, "tool_call_id", None)
        if tcid:
            for i in range(len(middle) - 1, -1, -1):
                m = middle[i]
                if isinstance(m, AIMessage) and any(
                    tc.get("id") == tcid for tc in (m.tool_calls or [])
                ):
                    # AIMessage 와 그 사이 모든 메시지를 tail 로 끌어당김
                    moved = middle[i:]
                    new_middle = middle[:i]
                    new_tail = list(moved) + list(tail)
                    return new_tail, new_middle
    return tail, middle


async def compact_messages(
    *,
    messages: list[BaseMessage],
    compact_model: "BaseChatModel",
    tokens_before: int,
    head_size: int = 2,
    tail_size: int = 20,
    custom_instructions: str | None = None,
    reason: str = "auto",
) -> CompactionOutput:
    """LLM 으로 messages 의 *중간 부분* 을 요약하고 boundary + summary 로 교체.

    ``head_size`` (default 2): 보존할 처음 메시지 수 — 보통 [System, 첫
    HumanMessage] 두 개. consumer 가 system 이 없으면 1 권장.
    ``tail_size`` (default 20): 보존할 마지막 메시지 수. tool_use ↔
    tool_result 짝 보존을 위해 자동 조정될 수 있음.

    Returns: ``CompactionOutput``. ContextManager 가 받아서 후처리.
    """
    head, middle, tail = _split_head_and_tail(messages, head_size, tail_size)
    tail, middle = _adjust_tail_for_pair_safety(tail, middle)

    if not middle:
        # 요약할 게 없음 — caller 가 처리. 그래도 객체 반환 (compacted=False
        # 신호는 caller 가 결정).
        boundary = CompactBoundaryMessage.now(
            pre_compact_token_count=tokens_before,
            pre_compact_message_count=len(messages),
            preserved_tail_count=len(tail),
            reason=reason,
        )
        return CompactionOutput(
            new_messages=list(messages),
            summary_text="",
            boundary=boundary,
            tokens_before=tokens_before,
            head_count=len(head),
            tail_count=len(tail),
            summarized_count=0,
        )

    # summarize 호출 — system: NO_TOOLS_PREAMBLE + BASE_COMPACT_PROMPT,
    # user: 요약 대상 conversation 을 텍스트로 직렬화
    system_prompt = get_compact_prompt(custom_instructions)
    conversation_text = _serialize_messages_for_summary(middle)
    summary_request = (
        f"<conversation_to_summarize>\n{conversation_text}\n</conversation_to_summarize>"
    )

    summarize_messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=summary_request),
    ]

    try:
        response = await compact_model.ainvoke(summarize_messages)
    except Exception as exc:
        log.exception("minyoung_mah.context.compact.invoke_failed")
        raise RuntimeError(f"compact LLM invoke failed: {exc}") from exc

    raw_text = (
        response.content if isinstance(response.content, str) else str(response.content)
    )
    summary_text = extract_summary_text(raw_text)
    if not summary_text.strip():
        raise RuntimeError("compact LLM returned empty summary")

    # boundary marker 빌드 + 새 messages 시퀀스
    summary_token_estimate = len(summary_text) // 4  # 1 token ≈ 4 chars 추정
    boundary = CompactBoundaryMessage.now(
        pre_compact_token_count=tokens_before,
        pre_compact_message_count=len(messages),
        preserved_tail_count=len(tail),
        reason=reason,
        summary_token_count=summary_token_estimate,
    )
    new_messages = build_post_compact_messages(
        head_to_preserve=head,
        boundary=boundary,
        summary_text=summary_text,
        preserved_tail=tail,
    )

    return CompactionOutput(
        new_messages=new_messages,
        summary_text=summary_text,
        boundary=boundary,
        tokens_before=tokens_before,
        head_count=len(head),
        tail_count=len(tail),
        summarized_count=len(middle),
    )


def _serialize_messages_for_summary(messages: list[BaseMessage]) -> str:
    """요약 대상 messages 를 텍스트로 직렬화. role 표기 + content 본문."""
    lines: list[str] = []
    for m in messages:
        role = type(m).__name__.replace("Message", "")
        content = m.content if isinstance(m.content, str) else str(m.content)
        # tool_calls 가 있으면 별도 표기 (BaseMessage 일반)
        tool_calls = getattr(m, "tool_calls", None)
        if tool_calls:
            tc_lines = []
            for tc in tool_calls:
                name = tc.get("name", "?")
                args = tc.get("args", {})
                tc_lines.append(f"  - {name}({args})")
            content = (content or "").rstrip()
            if content:
                content += "\n"
            content += "tool_calls:\n" + "\n".join(tc_lines)
        # tool_call_id (ToolMessage) 도 표기
        tool_call_id = getattr(m, "tool_call_id", None)
        if tool_call_id:
            content = f"[tool_call_id: {tool_call_id}]\n{content}"
        lines.append(f"=== {role} ===\n{content}\n")
    return "\n".join(lines)
