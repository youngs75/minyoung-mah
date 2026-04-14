"""Observer backends — standardized event schema + default adapters."""

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
