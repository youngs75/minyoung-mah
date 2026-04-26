"""ContextManager — compact_if_needed 분기 + circuit breaker + Observer."""

from __future__ import annotations

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from minyoung_mah.context import (
    CompactPolicy,
    CompactResult,
    ContextManager,
    default_policy,
)


class _FakeModel:
    """compact_model + target_model 모두 사용. token_counter 도 mock."""

    def __init__(self, model_name: str = "claude-opus-4-7", token_per_msg: int = 1000):
        self.model_name = model_name
        self.token_per_msg = token_per_msg
        self.invocations: list[list[BaseMessage]] = []
        self.response_text = (
            "<analysis>analysis here</analysis>\n"
            "<summary>this is the compact summary body</summary>"
        )

    def get_num_tokens_from_messages(self, messages: list[BaseMessage]) -> int:
        return len(messages) * self.token_per_msg

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.invocations.append(list(messages))
        return AIMessage(content=self.response_text)


class _RecorderObserver:
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, event) -> None:  # noqa: ANN001
        self.events.append(event)


def _build_messages(n: int) -> list[BaseMessage]:
    msgs: list[BaseMessage] = [
        SystemMessage(content="you are agent"),
        HumanMessage(content="initial request"),
    ]
    for i in range(n):
        msgs.append(AIMessage(content=f"ai {i}"))
        msgs.append(HumanMessage(content=f"user {i}"))
    return msgs


# ── compact_if_needed: 임계값 미달 → skip ───────────────────────────────────


@pytest.mark.asyncio
async def test_skip_when_below_threshold():
    fake = _FakeModel(token_per_msg=100)  # 6 messages * 100 = 600 tokens
    cm = ContextManager(compact_model=fake)
    msgs = _build_messages(2)  # 6 messages

    result = await cm.compact_if_needed(msgs, fake)
    assert result.compacted is False
    assert result.reason == "below_threshold"
    assert result.tokens_before == 600
    assert len(fake.invocations) == 0  # LLM 안 호출


# ── compact_if_needed: 임계값 도달 → compact ────────────────────────────────


@pytest.mark.asyncio
async def test_triggers_compact_above_auto_threshold():
    # 200K * 0.85 = 170K. 200 messages * 1000 = 200K tokens → 임계값 도달
    fake = _FakeModel(token_per_msg=1000)
    cm = ContextManager(compact_model=fake, head_size=2, tail_size=5)
    msgs = _build_messages(100)  # 202 messages

    result = await cm.compact_if_needed(msgs, fake)
    assert result.compacted is True
    assert result.reason == "auto"
    assert result.tokens_after is not None
    assert result.tokens_after < result.tokens_before
    assert "compact summary body" in result.summary_text
    # head + boundary + summary + tail = 9
    assert len(result.messages) == 2 + 1 + 1 + 5


# ── circuit breaker ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_circuit_breaker_after_consecutive_failures():
    class _FailingModel(_FakeModel):
        async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
            raise RuntimeError("fail")

    fake = _FailingModel(token_per_msg=1000)
    cm = ContextManager(
        policy=CompactPolicy(
            auto_compact_ratio=0.85,
            output_reserve_tokens=20_000,
            max_consecutive_failures=2,
            enabled_env=None,
            ratio_override_env=None,
            blocking_override_env=None,
        ),
        compact_model=fake,
        head_size=2,
        tail_size=5,
    )
    msgs = _build_messages(100)

    # 1st 실패
    r1 = await cm.compact_if_needed(msgs, fake)
    assert r1.compacted is False
    assert r1.reason.startswith("failed:")
    assert cm.consecutive_failures == 1

    # 2nd 실패 → circuit breaker 도달
    r2 = await cm.compact_if_needed(msgs, fake)
    assert r2.compacted is False
    assert cm.consecutive_failures == 2

    # 3rd → skipped:circuit_breaker
    r3 = await cm.compact_if_needed(msgs, fake)
    assert r3.compacted is False
    assert r3.reason == "skipped:circuit_breaker"


@pytest.mark.asyncio
async def test_success_resets_circuit_breaker():
    class _FlakeyModel(_FakeModel):
        def __init__(self) -> None:
            super().__init__(token_per_msg=1000)
            self.call_count = 0

        async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
            self.call_count += 1
            if self.call_count == 1:
                raise RuntimeError("first call fails")
            return await super().ainvoke(messages)

    fake = _FlakeyModel()
    cm = ContextManager(compact_model=fake, head_size=2, tail_size=5)
    msgs = _build_messages(100)

    r1 = await cm.compact_if_needed(msgs, fake)
    assert cm.consecutive_failures == 1

    r2 = await cm.compact_if_needed(msgs, fake)
    assert r2.compacted is True
    assert cm.consecutive_failures == 0  # 리셋
    assert cm.total_compactions == 1


# ── policy.enabled=False → skip ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_policy_skips():
    fake = _FakeModel(token_per_msg=1000)
    policy = CompactPolicy(
        enabled=False,
        enabled_env=None,
        ratio_override_env=None,
        blocking_override_env=None,
    )
    cm = ContextManager(policy=policy, compact_model=fake)
    msgs = _build_messages(100)

    result = await cm.compact_if_needed(msgs, fake)
    assert result.compacted is False
    assert result.reason == "skipped:disabled"


# ── Observer 발화 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observer_emits_start_and_end_on_compact():
    fake = _FakeModel(token_per_msg=1000)
    obs = _RecorderObserver()
    cm = ContextManager(compact_model=fake, observer=obs, head_size=2, tail_size=5)
    msgs = _build_messages(100)

    await cm.compact_if_needed(msgs, fake)
    names = [e.name for e in obs.events]
    assert "orchestrator.context.compact.start" in names
    assert "orchestrator.context.compact.end" in names


@pytest.mark.asyncio
async def test_observer_emits_warning_in_warning_band():
    # warning_ratio 0.75 ≤ tokens < auto 0.85 일 때 warning 발화
    # 200K * 0.75 ≈ 135K, 200K * 0.85 ≈ 170K → 150 messages * 1000 = 150K
    fake = _FakeModel(token_per_msg=1000)
    obs = _RecorderObserver()
    cm = ContextManager(compact_model=fake, observer=obs)
    # 150K 토큰이려면 messages 75개 필요 — 2 head + 73 = 75 messages
    msgs = _build_messages(36)  # 2 + 72 = 74 → ≈ 74K. warning 미달
    msgs2 = _build_messages(75)  # 2 + 150 = 152 → ≈ 152K. warning 도달

    await cm.compact_if_needed(msgs2, fake)
    names = [e.name for e in obs.events]
    assert "orchestrator.context.compact.warning" in names


# ── token counter fallback ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_counter_fallback_to_char_estimate():
    class _NoCounterModel:
        model_name = "unknown-model"

        async def ainvoke(self, messages):
            return AIMessage(content="<summary>x</summary>")

    fake = _NoCounterModel()
    cm = ContextManager(compact_model=fake)
    msgs = [HumanMessage(content="a" * 100)]
    tokens = cm.count_tokens(msgs, fake)
    # fallback: char count / 4 = 25
    assert tokens == 25
