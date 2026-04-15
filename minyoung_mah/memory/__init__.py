"""Memory package — ``store`` is the working library surface.

The legacy ``extractor`` / ``middleware`` / ``schema`` modules are still
broken copies of the coding-agent originals (they import
``coding_agent.*``). Importing this package must NOT pull them in — the
top-level ``minyoung_mah`` package re-exports ``SqliteMemoryStore`` /
``NullMemoryStore`` from ``minyoung_mah.memory.store``.

Phase 4 will rewrite the legacy modules when the coding agent moves to
``examples/coding_agent/``.
"""

from .store import NullMemoryStore, SqliteMemoryStore

__all__ = ["NullMemoryStore", "SqliteMemoryStore"]
