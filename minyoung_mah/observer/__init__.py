"""Observer backends — standardized event schema + default adapters.
Observer 백엔드 — 표준화된 이벤트 스키마 + 기본 adapter 들."""

from .events import (
    EVENT_NAMES,
    CollectingObserver,
    CompositeObserver,
    NullObserver,
    StructlogObserver,
)

__all__ = [
    "EVENT_NAMES",
    "CollectingObserver",
    "CompositeObserver",
    "NullObserver",
    "StructlogObserver",
]
