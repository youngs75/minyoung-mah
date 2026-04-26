"""Context compaction — token-aware threshold + LLM summarize.

Claude Code (claude-code-haha/src/services/compact/) 의 autoCompact 패턴을
Python 으로 포팅. consumer (ax / apt-legal 등) 가 ``ContextManager`` 를
인스턴스화해서 매 LLM 호출 직전 ``compact_if_needed`` 호출하면, 모델별
context window 의 비율 기반으로 자동 압축이 일어난다. 압축은 *별도 LLM*
이 ``BASE_COMPACT_PROMPT`` 로 대화를 요약 → boundary marker + summary
message 로 교체. 잘려나간 메시지의 정보가 *보존*된다.

Opt-in: consumer 가 명시적 인스턴스화하지 않으면 활성화되지 않음.
기존 동작에 영향 없다.
"""

from minyoung_mah.context.boundary import (
    CompactBoundaryMessage,
    build_post_compact_messages,
    extract_messages_after_boundary,
    is_boundary_message,
)
from minyoung_mah.context.compactor import compact_messages
from minyoung_mah.context.manager import CompactResult, ContextManager
from minyoung_mah.context.policy import (
    CompactPolicy,
    default_policy,
    get_context_window,
)
from minyoung_mah.context.prompts import (
    BASE_COMPACT_PROMPT,
    DETAILED_ANALYSIS_INSTRUCTION_BASE,
    NO_TOOLS_PREAMBLE,
    PARTIAL_COMPACT_FROM_PROMPT,
    PARTIAL_COMPACT_UP_TO_PROMPT,
)

__all__ = [
    "BASE_COMPACT_PROMPT",
    "CompactBoundaryMessage",
    "CompactPolicy",
    "CompactResult",
    "ContextManager",
    "DETAILED_ANALYSIS_INSTRUCTION_BASE",
    "NO_TOOLS_PREAMBLE",
    "PARTIAL_COMPACT_FROM_PROMPT",
    "PARTIAL_COMPACT_UP_TO_PROMPT",
    "build_post_compact_messages",
    "compact_messages",
    "default_policy",
    "extract_messages_after_boundary",
    "get_context_window",
    "is_boundary_message",
]
