"""Compact boundary marker + post-compact 메시지 빌더.

Claude Code 의 ``createCompactBoundaryMessage`` (compact.ts:614-624) +
``buildPostCompactMessages`` (compact.ts:330-338) 패턴 포팅.

압축 후 messages 형태:

    [
        SystemMessage(원래 system),
        HumanMessage(원래 첫 사용자 요청),         # 사용자 의도 보존
        SystemMessage(boundary marker),            # ← 여기까지가 압축 결과
        HumanMessage(LLM summary),                 # 요약 본문
        ...최근 N 개 *온전한* 메시지 (보존),
    ]

Boundary marker 의 metadata 에 ``pre_compact_token_count`` /
``compact_timestamp`` /  ``preserved_tail_count`` 등을 저장. 디버깅과
다음 압축 시 *이전 boundary 이후* 메시지만 다시 요약 (재요약 회피) 에
사용.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

# Boundary marker 의 content 식별자 — is_boundary_message 가 이걸로 인식.
_BOUNDARY_PREFIX = "[minyoung-mah:compact-boundary]"


@dataclass(frozen=True)
class CompactBoundaryMessage:
    """Compact 발생 시점을 표시하는 boundary marker 의 dataclass 표현.

    실제 메시지 객체는 ``to_message()`` 로 SystemMessage 변환. metadata
    는 ``additional_kwargs`` 에 저장 (LangChain 표준 경로).
    """

    timestamp: str  # ISO 8601 UTC
    pre_compact_token_count: int
    pre_compact_message_count: int
    preserved_tail_count: int  # boundary 이후 그대로 보존된 메시지 수
    summary_token_count: int | None = None
    reason: str = "auto"  # "auto" | "manual" | "blocking"

    def to_message(self) -> SystemMessage:
        return SystemMessage(
            content=(
                f"{_BOUNDARY_PREFIX} "
                f"이 시점 이전의 대화는 아래 요약으로 압축됨 "
                f"(토큰 {self.pre_compact_token_count} → 보존 메시지 "
                f"{self.preserved_tail_count}개, 사유: {self.reason})."
            ),
            additional_kwargs={
                "compact_boundary": True,
                "timestamp": self.timestamp,
                "pre_compact_token_count": self.pre_compact_token_count,
                "pre_compact_message_count": self.pre_compact_message_count,
                "preserved_tail_count": self.preserved_tail_count,
                "summary_token_count": self.summary_token_count,
                "reason": self.reason,
            },
        )

    @classmethod
    def now(
        cls,
        pre_compact_token_count: int,
        pre_compact_message_count: int,
        preserved_tail_count: int,
        reason: str = "auto",
        summary_token_count: int | None = None,
    ) -> "CompactBoundaryMessage":
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            pre_compact_token_count=pre_compact_token_count,
            pre_compact_message_count=pre_compact_message_count,
            preserved_tail_count=preserved_tail_count,
            summary_token_count=summary_token_count,
            reason=reason,
        )


def is_boundary_message(message: BaseMessage) -> bool:
    """``message`` 가 compact boundary marker 인지 판정."""
    if not isinstance(message, SystemMessage):
        return False
    ak = getattr(message, "additional_kwargs", None) or {}
    if ak.get("compact_boundary") is True:
        return True
    content = message.content if isinstance(message.content, str) else ""
    return content.startswith(_BOUNDARY_PREFIX)


def extract_messages_after_boundary(messages: list[BaseMessage]) -> list[BaseMessage]:
    """가장 최근 boundary marker *이후* 의 메시지만 반환.

    boundary 가 없으면 전체 반환. 다음 압축 시 *이전에 이미 압축된 부분*
    을 다시 요약하지 않게 한다 (Claude Code 의 ``getMessagesAfterCompactBoundary``).
    """
    last_idx = -1
    for i, m in enumerate(messages):
        if is_boundary_message(m):
            last_idx = i
    if last_idx < 0:
        return list(messages)
    return list(messages[last_idx + 1 :])


def build_post_compact_messages(
    *,
    head_to_preserve: list[BaseMessage],
    boundary: CompactBoundaryMessage,
    summary_text: str,
    preserved_tail: list[BaseMessage],
) -> list[BaseMessage]:
    """압축 후의 새 messages 시퀀스 빌드.

    Claude Code 의 ``buildPostCompactMessages`` 패턴:

    1. ``head_to_preserve`` — 보통 [SystemMessage, 첫 HumanMessage].
       사용자 원 의도 + 시스템 정체성 보존.
    2. boundary marker (SystemMessage) — 구분자 + 메타데이터.
    3. summary HumanMessage — LLM 이 요약한 본문 (assistant role 으로
       두면 모델이 *자기 응답으로 인식* 할 위험. user role 이 안전).
    4. ``preserved_tail`` — 가장 최근 메시지들 *그대로*. tool_use ↔
       tool_result 짝을 보존하는 책임은 caller (Compactor) 가 짐.

    Returns: head + boundary + summary + tail. add_messages reducer 와
    호환 (모두 BaseMessage 인스턴스).
    """
    summary_msg = HumanMessage(
        content=summary_text,
        additional_kwargs={
            "compact_summary": True,
            "boundary_timestamp": boundary.timestamp,
        },
    )
    return [
        *head_to_preserve,
        boundary.to_message(),
        summary_msg,
        *preserved_tail,
    ]


def is_compact_summary(message: BaseMessage) -> bool:
    """``message`` 가 compact summary HumanMessage 인지."""
    if not isinstance(message, HumanMessage):
        return False
    ak = getattr(message, "additional_kwargs", None) or {}
    return ak.get("compact_summary") is True


def get_summary_metadata(message: BaseMessage) -> dict[str, Any] | None:
    """boundary marker 의 metadata dict 반환 (디버깅용)."""
    if not is_boundary_message(message):
        return None
    return dict(getattr(message, "additional_kwargs", None) or {})
