"""Context compaction policy — token threshold + model-별 context window.

Claude Code 의 ``autoCompact.ts`` (33-91 lines) 의 임계값 정책을 Python 으로
포팅. 핵심 차이:

- Claude Code 는 ``getEffectiveContextWindowSize(model) - reserve - buffer``
  같이 *절대 토큰 수* 로 임계값 계산.
- 우리는 *비율* (default 85%) 로 단순화 — model 별 context window 만 알면
  됨. 비율은 ``CompactPolicy`` field 로 노출, 환경변수로 override.

3단계 임계값:

- ``warning_ratio`` (default 75%) — Observer 에 ``compact.warning`` 발화
- ``auto_compact_ratio`` (default 85%) — 자동 압축 트리거
- ``blocking_ratio`` (default 95%) — 새 메시지 차단 (consumer 가 결정)

Circuit breaker: 연속 실패 ``max_consecutive_failures`` (default 3) 회 도달
시 해당 세션의 자동 압축 모두 스킵.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


# 모델명 prefix → context window (tokens) 매핑.
# LangChain 표준에 ``get_context_window`` API 가 없어서 minyoung-mah 가
# 자체 dict 보유. 새 모델은 PR 또는 환경변수 override 로 추가.
_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic Claude (200K standard)
    "claude-opus-4-7": 200_000,
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-haiku-4-4": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
    # Deepseek V4 (128K)
    "deepseek-v4-pro": 128_000,
    "deepseek-v4-flash": 128_000,
    "deepseek-chat": 128_000,
    "deepseek-reasoner": 128_000,
    # Qwen3 (Dashscope, 일반 128K, max 시리즈는 더 큼)
    "dashscope/qwen3-max": 256_000,
    "dashscope/qwen3-coder-next": 128_000,
    "dashscope/qwen3.5-plus": 128_000,
    "dashscope/qwen3.5-flash": 128_000,
    "qwen3-max": 256_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "o1": 200_000,
    "o3": 200_000,
    # OpenRouter — 첫 segment 만 prefix 매칭 어렵, 별도 처리
    "openrouter/qwen/qwen3-max": 256_000,
    "openrouter/z-ai/glm-5.1": 128_000,
    "openrouter/qwen/qwen3-coder-next": 128_000,
}


def get_context_window(
    model: "BaseChatModel | str", default: int = 128_000
) -> int:
    """모델의 context window (tokens) 조회.

    ``model`` 이 ``BaseChatModel`` 이면 ``model.model_name`` 또는 ``model.model``
    에서 이름 추출. 문자열이면 그대로 매칭.

    매칭 우선순위:
    1. 환경변수 ``MINYOUNG_CONTEXT_WINDOW_<model_name>`` (대문자, '/'와 '.'은
       '_' 로 변환) — runtime override
    2. ``_CONTEXT_WINDOWS`` 의 prefix 매칭 (가장 긴 prefix 우선)
    3. ``default`` (보수적 128K)
    """
    if isinstance(model, str):
        name = model
    else:
        name = (
            getattr(model, "model_name", None)
            or getattr(model, "model", None)
            or ""
        )
    if not name:
        return default

    # 환경변수 override
    env_key = "MINYOUNG_CONTEXT_WINDOW_" + name.upper().replace("/", "_").replace(
        ".", "_"
    ).replace("-", "_")
    env_val = os.getenv(env_key)
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass

    # 가장 긴 prefix 매칭 — claude-opus-4-7-20240520 같은 dated 변형도 잡음
    best_match = ""
    for prefix in _CONTEXT_WINDOWS:
        if name.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
    if best_match:
        return _CONTEXT_WINDOWS[best_match]
    return default


@dataclass
class CompactPolicy:
    """Token threshold + circuit breaker + 환경변수 정책.

    Consumer 가 인스턴스화해 ``ContextManager`` 에 주입. ``default_policy()``
    가 합리적 default 반환.

    *비율 기반* — ``model_context_window * ratio`` 가 실제 임계값.
    ``output_reserve_tokens`` 만큼 입력 한도에서 빼서 *응답 공간* 확보.
    """

    # context window 의 자동 압축 트리거 비율 (default 85%)
    auto_compact_ratio: float = 0.85
    # 사용자 경고 시작 비율 (default 75%)
    warning_ratio: float = 0.75
    # 새 메시지 차단 비율 (default 95% — consumer 가 활용)
    blocking_ratio: float = 0.95
    # 압축 시 출력 토큰 예약 — claude-code 의 p99.99 (~17K) + buffer
    output_reserve_tokens: int = 20_000
    # circuit breaker — 연속 실패 한도
    max_consecutive_failures: int = 3
    # 자동 압축 enabled (False 면 모든 자동 압축 스킵 — manual 만 가능)
    enabled: bool = True
    # 환경변수 키 (None 이면 환경변수 안 봄)
    enabled_env: str | None = "MINYOUNG_AUTO_COMPACT"
    blocking_override_env: str | None = "MINYOUNG_COMPACT_BLOCKING_LIMIT"
    ratio_override_env: str | None = "MINYOUNG_COMPACT_RATIO"

    def __post_init__(self) -> None:
        # 환경변수 적용
        if self.enabled_env:
            v = os.getenv(self.enabled_env)
            if v is not None:
                self.enabled = v.strip().lower() not in ("0", "false", "no", "off", "")
        if self.ratio_override_env:
            v = os.getenv(self.ratio_override_env)
            if v:
                try:
                    self.auto_compact_ratio = float(v)
                except ValueError:
                    pass

    def auto_threshold_tokens(self, context_window: int) -> int:
        """자동 압축 임계값 (tokens)."""
        usable = max(0, context_window - self.output_reserve_tokens)
        return int(usable * self.auto_compact_ratio)

    def warning_threshold_tokens(self, context_window: int) -> int:
        usable = max(0, context_window - self.output_reserve_tokens)
        return int(usable * self.warning_ratio)

    def blocking_threshold_tokens(self, context_window: int) -> int:
        # blocking 은 환경변수 절대값 override 가능 (claude-code 의
        # CLAUDE_CODE_BLOCKING_LIMIT_OVERRIDE 패턴)
        if self.blocking_override_env:
            v = os.getenv(self.blocking_override_env)
            if v:
                try:
                    return int(v)
                except ValueError:
                    pass
        usable = max(0, context_window - self.output_reserve_tokens)
        return int(usable * self.blocking_ratio)


def default_policy() -> CompactPolicy:
    """기본 정책 — 75/85/95% threshold, 20K output reserve, 3회 circuit break."""
    return CompactPolicy()
