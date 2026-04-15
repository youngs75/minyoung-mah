"""Resilience package — policy + progress guard are the library surface.

The legacy watchdog / retry_policy / safe_stop / error_handler modules
are still present as broken copies of the coding-agent originals (they
import ``coding_agent.*``). Importing this package must NOT pull them
in — otherwise ``minyoung_mah.core.orchestrator`` can't load, which
breaks every downstream application.

They'll be rewritten when Phase 4 ports the coding agent into
``examples/coding_agent/``. Until then, import the working pieces via
their submodules (``minyoung_mah.resilience.policy``,
``minyoung_mah.resilience.progress_guard``) rather than from this
package root.
"""

from .policy import ResiliencePolicy, default_resilience
from .progress_guard import GuardVerdict, ProgressGuard

__all__ = [
    "GuardVerdict",
    "ProgressGuard",
    "ResiliencePolicy",
    "default_resilience",
]
