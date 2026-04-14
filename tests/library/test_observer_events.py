"""Observer event vocabulary + CollectingObserver."""

from __future__ import annotations

from datetime import datetime

import pytest

from minyoung_mah import CollectingObserver, ObserverEvent
from minyoung_mah.observer.events import EVENT_NAMES, is_canonical


def test_canonical_event_names_cover_required_boundaries() -> None:
    required = {
        "orchestrator.run.start",
        "orchestrator.run.end",
        "orchestrator.role.invoke.start",
        "orchestrator.role.invoke.end",
        "orchestrator.tool.call.start",
        "orchestrator.tool.call.end",
    }
    assert required.issubset(EVENT_NAMES)


def test_is_canonical() -> None:
    assert is_canonical("orchestrator.tool.call.start")
    assert not is_canonical("orchestrator.nonsense")


@pytest.mark.asyncio
async def test_collecting_observer_records_events() -> None:
    obs = CollectingObserver()
    event = ObserverEvent(
        name="orchestrator.run.start",
        timestamp=datetime.utcnow(),
        metadata={"run_id": "abc"},
    )
    await obs.emit(event)
    assert obs.names() == ["orchestrator.run.start"]
    obs.clear()
    assert obs.events == []
