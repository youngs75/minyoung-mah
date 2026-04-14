"""Resilience policy — composition of watchdog/retry/progress_guard/safe_stop.

Phase 2a scope: this module owns the *timeout* and *progress-guard* knobs.
Retry is split into two layers per decision C2:

- **tool-level** (transient): lives in
  :mod:`minyoung_mah.core.tool_invocation` via :class:`ToolRetryPolicy`.
- **role-level** (semantic): a role decides whether to re-invoke; the
  policy only exposes the *bound* on how many times it may do so.

Per decision F2, watchdog timeouts are **per role** via ``role_timeouts``
with a ``fallback_timeout`` for roles not explicitly listed. Per decision F3,
``default_resilience()`` ships opinionated defaults tuned from the 9th
ax coding agent E2E run — applications override what they need.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .progress_guard import ProgressGuard


@dataclass
class ResiliencePolicy:
    """Bundle of resilience knobs the Orchestrator reads at invoke time.

    Parameters
    ----------
    role_timeouts:
        Per-role wall-clock timeout in seconds. Keys are role names.
    fallback_timeout_s:
        Used for roles missing from ``role_timeouts``.
    role_max_retries:
        Per-role role-level retry cap (semantic retries, not transient).
        Keys are role names; missing roles use ``fallback_max_retries``.
    fallback_max_retries:
        Default role-level retry cap.
    progress_guard:
        Loop-progress detector. Phase 2a (static pipelines) pipelines use
        :meth:`ProgressGuard.disabled` because iteration is bounded by
        construction; dynamic loops use the real guard.
    """

    role_timeouts: dict[str, float] = field(default_factory=dict)
    fallback_timeout_s: float = 90.0
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
    fallback_timeout_s: float = 90.0,
    enable_progress_guard: bool = False,
) -> ResiliencePolicy:
    """Opinionated :class:`ResiliencePolicy` factory.

    Defaults:

    - ``fallback_timeout_s=90`` — middle ground between apt-legal's 10–30s
      roles and coding's 180s coder.
    - ``fallback_max_retries=1`` — one semantic retry before escalation.
    - ``progress_guard`` **disabled by default** because Phase 2a focuses
      on static pipelines. Pass ``enable_progress_guard=True`` (or a
      custom ``ProgressGuard`` instance via :class:`ResiliencePolicy`
      directly) when building a dynamic loop.
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
