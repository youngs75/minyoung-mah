"""Resilience policy — composition of watchdog/retry/progress_guard/safe_stop.
Resilience 정책 — watchdog/retry/progress_guard/safe_stop 의 조합.

Phase 2a scope: this module owns the *timeout* and *progress-guard* knobs.
Retry is split into two layers per decision C2:

Phase 2a 범위: 이 모듈은 *timeout* 과 *progress-guard* 노브를 소유한다.
재시도는 결정 C2 에 따라 두 계층으로 분리된다:

- **tool-level** (transient): lives in
  :mod:`minyoung_mah.core.tool_invocation` via :class:`ToolRetryPolicy`.
- **도구 수준**(일시적): :mod:`minyoung_mah.core.tool_invocation` 의
  :class:`ToolRetryPolicy` 가 담당.
- **role-level** (semantic): a role decides whether to re-invoke; the
  policy only exposes the *bound* on how many times it may do so.
- **역할 수준**(의미상): 역할이 재호출 여부를 결정한다. 정책은 횟수의
  *상한*만 노출한다.

Per decision F2, watchdog timeouts are **per role** via ``role_timeouts``
with a ``fallback_timeout`` for roles not explicitly listed. Per decision F3,
``default_resilience()`` ships opinionated defaults tuned from the 9th
ax coding agent E2E run — applications override what they need.

결정 F2 에 따라 watchdog 타임아웃은 ``role_timeouts`` 로 **역할별** 지정하고,
명시되지 않은 역할에는 ``fallback_timeout`` 을 적용한다. 결정 F3 에 따라
``default_resilience()`` 는 9차 ax coding agent E2E 실행에서 튜닝된 opinionated
기본값을 제공하며, 애플리케이션은 필요한 것만 override 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .progress_guard import ProgressGuard


@dataclass
class ResiliencePolicy:
    """Bundle of resilience knobs the Orchestrator reads at invoke time.
    Orchestrator 가 호출 시점에 읽는 resilience 노브 묶음.

    Parameters
    ----------
    role_timeouts:
        Per-role wall-clock timeout in seconds. Keys are role names.
        역할별 wall-clock 타임아웃(초). 키는 역할 이름.
    fallback_timeout_s:
        Used for roles missing from ``role_timeouts``.
        ``role_timeouts`` 에 없는 역할에 적용되는 폴백.
    role_max_retries:
        Per-role role-level retry cap (semantic retries, not transient).
        Keys are role names; missing roles use ``fallback_max_retries``.
        역할별 role-level 재시도 상한(의미상 재시도, 일시적 재시도 아님).
        키는 역할 이름. 누락된 역할은 ``fallback_max_retries`` 사용.
    fallback_max_retries:
        Default role-level retry cap.
        기본 role-level 재시도 상한.
    progress_guard:
        Loop-progress detector. Static pipelines use
        :meth:`ProgressGuard.disabled` because iteration is bounded by
        construction; consumers that run a dynamic loop on top of
        ``invoke_role`` wire a real guard in.
        루프 진전 감시기. 정적 파이프라인은 iteration 이 구성 단계에서 이미
        bound 되므로 :meth:`ProgressGuard.disabled` 를 사용. ``invoke_role``
        위에서 동적 루프를 돌리는 컨슈머는 실제 guard 를 주입한다.
    """

    role_timeouts: dict[str, float] = field(default_factory=dict)
    fallback_timeout_s: float = 180.0
    role_max_retries: dict[str, int] = field(default_factory=dict)
    fallback_max_retries: int = 1
    progress_guard: ProgressGuard = field(
        default_factory=lambda: ProgressGuard.disabled()
    )

    def timeout_for(self, role_name: str) -> float:
        return self.role_timeouts.get(role_name, self.fallback_timeout_s)

    def max_retries_for(self, role_name: str) -> int:
        return self.role_max_retries.get(role_name, self.fallback_max_retries)


def default_resilience(
    role_timeouts: dict[str, float] | None = None,
    fallback_timeout_s: float = 180.0,
    enable_progress_guard: bool = False,
) -> ResiliencePolicy:
    """Opinionated :class:`ResiliencePolicy` factory.
    Opinionated :class:`ResiliencePolicy` 팩토리.

    Defaults tuned from the apt-legal-agent first-consumer run (2026-04-15):
    apt-legal-agent first-consumer 실행(2026-04-15)에서 튜닝된 기본값:

    - ``fallback_timeout_s=180`` — the 90s default from the 9th coding-agent
      E2E was too tight for roles that autonomously explore a large MCP
      tool catalog (legal_lookup exceeded 90s on the 15-tool kor-legal-mcp
      within two iterations). 180s keeps most single-role budgets under
      one model provider's request timeout while leaving room for
      multi-tool deliberation.
    - ``fallback_timeout_s=180`` — 9차 coding-agent E2E 의 90초 기본값은 큰 MCP
      도구 카탈로그를 자율 탐색하는 역할에 너무 타이트했다(legal_lookup 이
      15-tool kor-legal-mcp 에서 두 iteration 만에 90초 초과). 180초는 대부분의
      단일 역할 예산을 한 모델 provider 의 요청 타임아웃 아래로 유지하면서
      multi-tool 숙고 여유를 확보한다.
    - ``fallback_max_retries=1`` — one semantic retry before escalation.
      ``fallback_max_retries=1`` — 에스컬레이션 전 한 번의 의미상 재시도.
    - ``progress_guard`` **disabled by default** for static pipelines,
      which are bounded by construction. Consumers that run a dynamic
      driver loop on top of ``invoke_role`` should pass
      ``enable_progress_guard=True`` or inject a custom
      :class:`ProgressGuard` via :class:`ResiliencePolicy` directly.
      구성 단계에서 bound 된 정적 파이프라인을 위해 ``progress_guard`` 는
      **기본 비활성**. ``invoke_role`` 위에 동적 driver 루프를 돌리는 컨슈머는
      ``enable_progress_guard=True`` 를 넘기거나 :class:`ResiliencePolicy` 를
      통해 커스텀 :class:`ProgressGuard` 를 직접 주입해야 한다.

    Recommended per-role overrides (apt-legal reference values)::
    역할별 권장 override (apt-legal 참조값)::

        default_resilience(
            role_timeouts={
                "router": 30.0,         # structured fast path, 1 LLM call
                "domain_lookup": 240.0, # 8-tool MCP, up to 10 iterations
                "legal_lookup": 300.0,  # 15-tool MCP, up to 10 iterations
                "synthesizer": 120.0,   # 1 LLM call over accumulated state
            },
            fallback_timeout_s=180.0,
        )
    """
    guard = (
        ProgressGuard(
            window_size=10,
            stall_threshold=3,
            max_iterations=50,
            secondary_window_size=12,
            secondary_repeat_threshold=6,
        )
        if enable_progress_guard
        else ProgressGuard.disabled()
    )
    return ResiliencePolicy(
        role_timeouts=dict(role_timeouts or {}),
        fallback_timeout_s=fallback_timeout_s,
        progress_guard=guard,
    )
