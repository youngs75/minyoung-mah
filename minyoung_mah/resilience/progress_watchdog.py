"""Progress-based wall-clock watchdog for role invocations.
진전 기반 wall-clock 워치독 — 역할 호출에서 사용.

Wraps the existing ``fallback_timeout_s`` with a dynamically-extending
deadline: every *novel* tool-call success (unique ``args_hash``) pushes the
deadline forward by ``extend_s``, capped at ``max_total_s``. Repeated tool
calls with the same arguments are treated as no progress (a signal the
role is stuck in a loop).

기존 ``fallback_timeout_s`` 에 동적으로 늘어나는 마감 시각을 더한 래퍼.
모든 *고유* 도구 호출 성공(유일한 ``args_hash``)마다 마감 시각을
``extend_s`` 만큼 연장하고, 상한은 ``max_total_s``. 같은 인자로 반복된
도구 호출은 진전이 아닌 것으로 간주 (역할이 루프에 갇힌 신호).

## 왜 필요한가

ax 9차 coding-agent v4 E2E (2026-04-23): coder subagent 가 TDD 로 Flask+JWT+
SQLAlchemy 통합 문제를 해결하느라 50+ 회 LLM 호출 + tool 호출을 수행했는데,
개별 호출은 빠르지만 (1-10s) 누적이 240s 벽을 넘어 ``watchdog_timeout`` 으로
abort. 정말 stuck 된 게 아니라 진전 중이었는데 시간만 초과.

Wall-clock 단일 상한은 "얼마나 오래 돌았나" 만 보고 "얼마나 진전했나"를
보지 않는다. 이 모듈은 진전을 1급 시민으로 올려, 생산적 역할은 연장 받고
진짜 막힌 역할은 짧게 abort 시킨다.

## 설계

- **Novelty = 진전**: 새로운 ``(tool_name, args_hash)`` 쌍이 성공하면 진전.
  이미 본 조합은 연장 트리거 안 됨.
- **상한은 절대적**: ``max_total_s`` 는 role invocation 시작 시점 기준.
  아무리 진전이 있어도 이를 초과 못함 (runaway 방지).
- **ContextVar 주입**: :data:`CURRENT_WATCHDOG` 를 통해 호출 사슬 내부에서
  찾을 수 있다. 호출자가 ``with install(watchdog)`` 로 스코프를 잡으면
  ToolInvocationEngine 이 자동으로 progress signal 을 보낸다.
"""

from __future__ import annotations

import contextlib
import contextvars
import time
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class ProgressWatchdog:
    """Wall-clock deadline with progress-triggered extensions.
    진전 시그널로 연장되는 wall-clock 마감 시각.

    Lifecycle: call :meth:`start` before the guarded coroutine begins.
    Downstream tool executions call :meth:`signal_progress` on success.
    The scheduler polls :meth:`remaining_s` / :meth:`expired` to decide
    whether to keep waiting.

    생애주기: 보호할 코루틴이 시작하기 전에 :meth:`start` 호출. 하위
    도구 실행은 성공 시 :meth:`signal_progress` 호출. 스케줄러는
    :meth:`remaining_s` / :meth:`expired` 로 대기 여부를 결정.
    """

    base_timeout_s: float
    extend_s: float = 60.0
    max_total_s: float = 900.0

    _start: float = field(default=0.0, init=False, repr=False)
    _deadline: float = field(default=0.0, init=False, repr=False)
    _seen: set[int] = field(default_factory=set, init=False, repr=False)
    _signals: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.base_timeout_s <= 0:
            raise ValueError("base_timeout_s must be positive")
        if self.extend_s < 0:
            raise ValueError("extend_s must be non-negative")
        if self.max_total_s < self.base_timeout_s:
            raise ValueError("max_total_s must be >= base_timeout_s")

    def start(self, *, now: float | None = None) -> None:
        """Begin the watchdog clock. Idempotent — resets state.
        워치독 시계를 시작. 멱등 — 상태 초기화.
        """
        t = time.monotonic() if now is None else now
        self._start = t
        self._deadline = t + self.base_timeout_s
        self._seen = set()
        self._signals = 0

    def signal_progress(self, args_hash: int, *, now: float | None = None) -> bool:
        """Register a progress signal. Returns True iff it extended the deadline.
        진전 시그널 등록. 마감 시각을 연장했으면 True 반환.

        Repeated signals with the same ``args_hash`` are ignored — they
        indicate the role is retrying the same action rather than moving
        forward. The extension cap (``max_total_s``) is enforced so even
        a highly productive role eventually terminates.

        같은 ``args_hash`` 의 반복 시그널은 무시 — 역할이 동일 행위를
        재시도하는 신호이지 전진이 아니다. 연장 상한(``max_total_s``)은
        강제되어 생산적 역할도 언젠가는 종료.
        """
        if args_hash in self._seen:
            return False
        self._seen.add(args_hash)
        self._signals += 1
        t = time.monotonic() if now is None else now
        proposed = max(self._deadline, t) + self.extend_s
        hard_cap = self._start + self.max_total_s
        new_deadline = min(proposed, hard_cap)
        if new_deadline <= self._deadline:
            return False  # already at/past cap
        self._deadline = new_deadline
        return True

    def remaining_s(self, *, now: float | None = None) -> float:
        """Seconds until deadline (never negative)."""
        t = time.monotonic() if now is None else now
        return max(0.0, self._deadline - t)

    def expired(self, *, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        return t >= self._deadline

    @property
    def signal_count(self) -> int:
        """Number of distinct progress signals recorded (for observability)."""
        return self._signals

    @property
    def elapsed_s(self) -> float:
        return max(0.0, time.monotonic() - self._start)


# ---------------------------------------------------------------------------
# ContextVar-based injection — the enclosing ``invoke_role`` installs the
# active watchdog so nested tool calls can find it without plumbing through
# every function signature.
# ContextVar 기반 주입 — 상위 ``invoke_role`` 가 활성 watchdog 을 설치하면
# 중첩된 도구 호출이 모든 함수 시그너처에 끼워넣지 않고도 찾을 수 있다.
# ---------------------------------------------------------------------------


CURRENT_WATCHDOG: contextvars.ContextVar["ProgressWatchdog | None"] = contextvars.ContextVar(
    "mm_progress_watchdog", default=None
)


@contextlib.contextmanager
def install(watchdog: "ProgressWatchdog | None") -> Iterator[None]:
    """Install ``watchdog`` as the active :data:`CURRENT_WATCHDOG` for this
    context. Safe to nest — inner scopes restore the outer watchdog on exit.
    ``watchdog`` 을 이 컨텍스트의 활성 :data:`CURRENT_WATCHDOG` 로 설치한다.
    중첩 안전 — 내부 스코프가 빠지면 외부 watchdog 으로 복원.

    Passing ``None`` explicitly disables the watchdog for this scope (useful
    in tests or when a caller wants to bypass progress tracking entirely).

    ``None`` 을 명시적으로 넘기면 이 스코프에서 watchdog 이 비활성화된다
    (테스트 또는 호출자가 진전 추적을 완전히 우회하려는 경우 유용).
    """
    token = CURRENT_WATCHDOG.set(watchdog)
    try:
        yield
    finally:
        CURRENT_WATCHDOG.reset(token)


def signal_current_progress(args_hash: int) -> bool:
    """Send a progress signal to the context's active watchdog, if any.
    컨텍스트의 활성 watchdog 에 진전 시그널 전송 (있으면).

    Intended for ToolInvocationEngine on a successful tool call. Returns the
    ``signal_progress`` result (True if deadline actually moved), or False
    when no watchdog is installed.

    성공한 도구 호출에서 ToolInvocationEngine 이 사용. ``signal_progress``
    의 결과(마감 시각이 실제로 이동했으면 True)를 반환하거나, 설치된
    watchdog 이 없으면 False.
    """
    wd = CURRENT_WATCHDOG.get()
    if wd is None:
        return False
    return wd.signal_progress(args_hash)


__all__ = [
    "CURRENT_WATCHDOG",
    "ProgressWatchdog",
    "install",
    "signal_current_progress",
]
