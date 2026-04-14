"""ProgressGuard — injectable key_extractor instead of hardcoded TASK-NN regex."""

from __future__ import annotations

import re

from minyoung_mah.resilience.progress_guard import GuardVerdict, ProgressGuard


def test_disabled_guard_never_stops() -> None:
    guard = ProgressGuard.disabled()
    for i in range(1000):
        guard.record_action("any_tool", {"x": i})
        assert guard.check(i) is GuardVerdict.OK


def test_max_iterations_stops() -> None:
    guard = ProgressGuard(max_iterations=5)
    assert guard.check(4) is GuardVerdict.OK
    assert guard.check(5) is GuardVerdict.STOP


def test_key_extractor_injected_for_task_id_cycle() -> None:
    """Coding-agent-style TASK-NN tracking via injected extractor."""

    pattern = re.compile(r"\bTASK-\d{2,}\b", re.IGNORECASE)

    def task_id_extractor(tool_name: str, args: dict) -> str | None:
        if tool_name != "task":
            return None
        desc = args.get("description", "")
        m = pattern.search(desc) if isinstance(desc, str) else None
        return m.group(0).upper() if m else None

    guard = ProgressGuard(
        secondary_window_size=12,
        secondary_repeat_threshold=6,
        key_extractor=task_id_extractor,
    )

    for i in range(6):
        guard.record_action("task", {"description": f"TASK-04 iteration {i}"})

    first = guard.check(10)
    assert first in {GuardVerdict.WARN, GuardVerdict.STOP}

    for i in range(6):
        guard.record_action("task", {"description": f"TASK-04 more {i}"})
    second = guard.check(11)
    assert second is GuardVerdict.STOP


def test_no_extractor_ignores_secondary_tracking() -> None:
    """Without an extractor the secondary path stays empty."""
    guard = ProgressGuard(secondary_repeat_threshold=2)
    guard.record_action("task", {"description": "TASK-04"})
    guard.record_action("task", {"description": "TASK-04"})
    guard.record_action("task", {"description": "TASK-04"})
    assert guard._secondary_history == guard._secondary_history.__class__(maxlen=12)
    assert len(guard._secondary_history) == 0
