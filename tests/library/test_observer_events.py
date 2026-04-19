"""Observer event vocabulary + CollectingObserver."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from minyoung_mah import CollectingObserver, ObserverEvent
from minyoung_mah.observer.events import EVENT_NAMES, is_canonical


def test_canonical_event_names_cover_required_boundaries() -> None:
    required = {
        "orchestrator.run.start",
        "orchestrator.run.end",
        "orchestrator.role.invoke.start",
        "orchestrator.role.invoke.end",
        "role.tool.call.start",
        "role.tool.call.end",
    }
    assert required.issubset(EVENT_NAMES)


def test_is_canonical() -> None:
    assert is_canonical("role.tool.call.start")
    assert is_canonical("orchestrator.role.invoke.start")
    assert not is_canonical("orchestrator.nonsense")
    # Legacy name must not silently pass — callers migrating from 0.1.3 need
    # a loud failure, not a quiet one.
    assert not is_canonical("orchestrator.tool.call.start")


@pytest.mark.asyncio
async def test_collecting_observer_records_events() -> None:
    obs = CollectingObserver()
    event = ObserverEvent(
        name="orchestrator.run.start",
        timestamp=datetime.now(timezone.utc),
        metadata={"run_id": "abc"},
    )
    await obs.emit(event)
    assert obs.names() == ["orchestrator.run.start"]
    obs.clear()
    assert obs.events == []
