"""ContextManager — token-aware threshold 검사 + 자동 compact 트리거.

Consumer (ax / apt-legal 등) 가 매 LLM 호출 직전 ``compact_if_needed`` 만
호출하면 됨. 임계값 미달이면 원본 그대로 반환, 도달하면 ``compact_messages``
호출 + Observer 발화 + circuit breaker 처리.

설계 결정:
- ``target_model`` 의 ``get_num_tokens_from_messages`` 로 정확한 토큰 측정
- ``compact_model`` 은 보통 fast tier — summarize 비용 절약
- Observer 는 옵셔널 — minyoung_mah.Observer 호환 객체 받으면 발화
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage

from minyoung_mah.context.boundary import (
    CompactBoundaryMessage,
    extract_messages_after_boundary,
)
from minyoung_mah.context.compactor import compact_messages
from minyoung_mah.context.policy import (
    CompactPolicy,
    default_policy,
    get_context_window,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from minyoung_mah.core.types import ObserverEvent
    from minyoung_mah.observer import Observer

log = logging.getLogger("minyoung_mah.context.manager")


@dataclass
class CompactResult:
    """``compact_if_needed`` 의 반환값. consumer 가 ``messages`` 를 그대로
    LLM 호출에 사용. ``compacted=False`` 면 원본 그대로."""

    compacted: bool
    messages: list[BaseMessage]
    tokens_before: int
    tokens_after: int | None = None
    summary_text: str | None = None
    boundary_message: BaseMessage | None = None
    reason: str = "below_threshold"
    # "below_threshold" | "auto" | "manual" | "blocking"
    # | "skipped:circuit_breaker" | "skipped:disabled"
    # | "failed:<exception_type>" | "no_middle_to_summarize"


@dataclass
class _ManagerState:
    """Internal — circuit breaker counter."""

    consecutive_failures: int = 0
    total_compactions: int = 0
    last_warning_emitted_at: str | None = None


class ContextManager:
    """Token-aware context compaction orchestrator.

    Usage::

        cm = ContextManager(
            policy=default_policy(),
            compact_model=fast_tier_model,
            observer=orchestrator.observer,  # 옵셔널
        )

        # 매 LLM 호출 직전
        result = await cm.compact_if_needed(messages, target_model)
        if result.compacted:
            log.info("compacted", before=result.tokens_before, after=result.tokens_after)
        messages = result.messages   # 항상 사용 가능 (원본 또는 compact 결과)

    ``target_model`` 의 token_counter 와 ``get_context_window`` 결과로
    임계값 비교. ``policy.auto_compact_ratio`` 도달 시 compact_model 로
    summarize.
    """

    def __init__(
        self,
        *,
        policy: CompactPolicy | None = None,
        compact_model: "BaseChatModel",
        observer: "Observer | None" = None,
        prompt_override: str | None = None,
        head_size: int = 2,
        tail_size: int = 20,
    ) -> None:
        self.policy = policy or default_policy()
        self.compact_model = compact_model
        self.observer = observer
        self.prompt_override = prompt_override
        self.head_size = head_size
        self.tail_size = tail_size
        self._state = _ManagerState()

    @property
    def consecutive_failures(self) -> int:
        return self._state.consecutive_failures

    @property
    def total_compactions(self) -> int:
        return self._state.total_compactions

    def count_tokens(
        self, messages: list[BaseMessage], target_model: "BaseChatModel"
    ) -> int:
        """target_model 의 표준 ``get_num_tokens_from_messages`` 활용.

        모델이 그 메서드 미지원 시 *char count / 4* 로 fallback (보수적
        근사).
        """
        try:
            counter = getattr(target_model, "get_num_tokens_from_messages", None)
            if counter:
                return int(counter(messages))
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "minyoung_mah.context.token_count_failed",
                error=str(exc),
            )
        # Fallback — char count / 4 (영어 평균)
        total_chars = 0
        for m in messages:
            content = m.content if isinstance(m.content, str) else str(m.content)
            total_chars += len(content)
        return total_chars // 4

    async def compact_if_needed(
        self,
        messages: list[BaseMessage],
        target_model: "BaseChatModel",
    ) -> CompactResult:
        """매 LLM 호출 직전 호출. threshold 도달 시 compact, 아니면 skip."""
        if not self.policy.enabled:
            return CompactResult(
                compacted=False,
                messages=list(messages),
                tokens_before=0,
                reason="skipped:disabled",
            )
        if self._state.consecutive_failures >= self.policy.max_consecutive_failures:
            return CompactResult(
                compacted=False,
                messages=list(messages),
                tokens_before=0,
                reason="skipped:circuit_breaker",
            )

        context_window = get_context_window(target_model)
        tokens = self.count_tokens(messages, target_model)
        auto_threshold = self.policy.auto_threshold_tokens(context_window)
        warning_threshold = self.policy.warning_threshold_tokens(context_window)

        # Warning 이벤트 — auto 임계값 미만이지만 warning 넘으면
        if (
            warning_threshold <= tokens < auto_threshold
            and self._state.last_warning_emitted_at != _today_iso()
        ):
            await self._emit(
                "orchestrator.context.compact.warning",
                {
                    "tokens": tokens,
                    "warning_threshold": warning_threshold,
                    "auto_threshold": auto_threshold,
                    "context_window": context_window,
                },
            )
            self._state.last_warning_emitted_at = _today_iso()

        if tokens < auto_threshold:
            return CompactResult(
                compacted=False,
                messages=list(messages),
                tokens_before=tokens,
                reason="below_threshold",
            )

        # 자동 compact 실행
        return await self.compact(messages, target_model, reason="auto")

    async def compact(
        self,
        messages: list[BaseMessage],
        target_model: "BaseChatModel",
        reason: str = "manual",
    ) -> CompactResult:
        """명시적 compact 호출 (auto / manual / blocking 분기 외부에서 결정)."""
        # 이미 boundary 가 있으면 그 *이후* 메시지만 다시 compact 대상.
        # head 는 boundary 이전 (system + 첫 user) 보존을 위해 messages 전체에서
        # 추출. 단순화: head_size=2 로 항상 messages 처음 2개 보존.
        # tail_size 는 그대로.
        tokens_before = self.count_tokens(messages, target_model)

        await self._emit(
            "orchestrator.context.compact.start",
            {
                "tokens_before": tokens_before,
                "messages_before": len(messages),
                "reason": reason,
            },
        )

        try:
            output = await compact_messages(
                messages=messages,
                compact_model=self.compact_model,
                tokens_before=tokens_before,
                head_size=self.head_size,
                tail_size=self.tail_size,
                custom_instructions=self.prompt_override,
                reason=reason,
            )
        except Exception as exc:
            self._state.consecutive_failures += 1
            log.exception(
                "minyoung_mah.context.compact.failed",
                extra={"consecutive_failures": self._state.consecutive_failures},
            )
            await self._emit(
                "orchestrator.context.compact.end",
                {
                    "ok": False,
                    "error": str(exc),
                    "consecutive_failures": self._state.consecutive_failures,
                },
            )
            return CompactResult(
                compacted=False,
                messages=list(messages),
                tokens_before=tokens_before,
                reason=f"failed:{type(exc).__name__}",
            )

        if output.summarized_count == 0:
            await self._emit(
                "orchestrator.context.compact.end",
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "no_middle_to_summarize",
                    "tokens_before": tokens_before,
                },
            )
            return CompactResult(
                compacted=False,
                messages=list(messages),
                tokens_before=tokens_before,
                reason="no_middle_to_summarize",
            )

        # 성공 — circuit breaker 리셋
        self._state.consecutive_failures = 0
        self._state.total_compactions += 1
        tokens_after = self.count_tokens(output.new_messages, target_model)

        await self._emit(
            "orchestrator.context.compact.end",
            {
                "ok": True,
                "tokens_before": tokens_before,
                "tokens_after": tokens_after,
                "summarized_count": output.summarized_count,
                "preserved_tail_count": output.tail_count,
                "reason": reason,
            },
        )

        return CompactResult(
            compacted=True,
            messages=output.new_messages,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            summary_text=output.summary_text,
            boundary_message=output.boundary.to_message(),
            reason=reason,
        )

    async def _emit(self, name: str, metadata: dict[str, Any]) -> None:
        """Observer 가 있으면 ObserverEvent 발화. 실패 무시."""
        if self.observer is None:
            return
        try:
            from minyoung_mah.core.types import ObserverEvent

            await self.observer.emit(
                ObserverEvent(
                    name=name,
                    timestamp=datetime.now(timezone.utc),
                    metadata=metadata,
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "minyoung_mah.context.observer_emit_failed",
                extra={"event": name, "error": str(exc)},
            )


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()
