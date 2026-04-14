"""Default :class:`MemoryStore` implementations.

Two backends ship with the library:

- :class:`SqliteMemoryStore` — opinionated default. SQLite + FTS5 full-text
  index, ``(tier, scope, key)`` unique constraint. Tier and scope are
  application-defined strings; the library enforces no semantics on them.
- :class:`NullMemoryStore` — drops every write. Required for apps that
  cannot persist memory (e.g. apt-legal's privacy constraint).

The schema was redesigned from the ax coding agent original: ``layer`` →
``tier``, ``project_id`` → ``scope``. Per decision D1 the old DB format
is intentionally incompatible — a fresh start is simpler than a migration
tool for the rare users who had real data in the old schema.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from ..core.types import MemoryEntry

log = structlog.get_logger(__name__)


_CREATE_MEMORIES = """\
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tier        TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT '',
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(tier, scope, key)
);
"""

_CREATE_TIER_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_memories_tier_scope ON memories(tier, scope);"
)

_CREATE_FTS = """\
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(value, key, content=memories, content_rowid=id);
"""

_TRIGGERS = [
    """\
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, value, key)
    VALUES (new.id, new.value, new.key);
END;
""",
    """\
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, value, key)
    VALUES ('delete', old.id, old.value, old.key);
END;
""",
    """\
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, value, key)
    VALUES ('delete', old.id, old.value, old.key);
    INSERT INTO memories_fts(rowid, value, key)
    VALUES (new.id, new.value, new.key);
END;
""",
]


# ---------------------------------------------------------------------------
# SqliteMemoryStore
# ---------------------------------------------------------------------------


class SqliteMemoryStore:
    """SQLite + FTS5 backed memory store with tier/scope partitioning.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file. Parent dirs are created.
        Use ``":memory:"`` for an ephemeral store (handy in tests).
    tiers:
        Optional declared tier names. When set, :meth:`list_tiers` returns
        this list instead of querying the table. Writes to undeclared tiers
        are still allowed — the list is informational.
    """

    def __init__(self, db_path: str, tiers: list[str] | None = None) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._declared_tiers = list(tiers) if tiers else None
        self._lock = asyncio.Lock()
        self._init_schema()
        log.info("memory_store.initialized", db_path=db_path)

    # -- schema --------------------------------------------------------

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_CREATE_MEMORIES)
        cur.execute(_CREATE_TIER_IDX)
        cur.execute(_CREATE_FTS)
        for trigger_sql in _TRIGGERS:
            cur.execute(trigger_sql)
        self._conn.commit()

    # -- MemoryStore protocol -----------------------------------------

    async def write(
        self,
        tier: str,
        key: str,
        value: str,
        scope: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        import json

        scope_s = scope or ""
        now = datetime.utcnow().isoformat()
        meta_s = json.dumps(metadata or {})
        async with self._lock:
            await asyncio.to_thread(
                self._write_sync, tier, scope_s, key, value, meta_s, now
            )

    def _write_sync(
        self,
        tier: str,
        scope: str,
        key: str,
        value: str,
        metadata_json: str,
        now: str,
    ) -> None:
        try:
            self._conn.execute(
                """\
                INSERT INTO memories (tier, scope, key, value, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tier, scope, key) DO UPDATE SET
                    value      = excluded.value,
                    metadata   = excluded.metadata,
                    updated_at = excluded.updated_at
                """,
                (tier, scope, key, value, metadata_json, now, now),
            )
            self._conn.commit()
        except sqlite3.Error:
            self._conn.rollback()
            log.exception("memory_store.write_failed", tier=tier, key=key)
            raise

    async def read(
        self,
        tier: str,
        key: str,
        scope: str | None = None,
    ) -> MemoryEntry | None:
        scope_s = scope or ""
        row = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT * FROM memories WHERE tier = ? AND scope = ? AND key = ?",
                (tier, scope_s, key),
            ).fetchone()
        )
        return _row_to_entry(row) if row else None

    async def search(
        self,
        tier: str,
        query: str,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        if not query or not query.strip():
            return []
        safe_query = query.replace('"', '""')
        sql = """\
            SELECT m.*
            FROM memories m
            JOIN memories_fts f ON m.id = f.rowid
            WHERE memories_fts MATCH ? AND m.tier = ?
        """
        params: list[Any] = [f'"{safe_query}"', tier]
        if scope is not None:
            sql += " AND m.scope = ?"
            params.append(scope)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = await asyncio.to_thread(
            lambda: self._conn.execute(sql, params).fetchall()
        )
        return [_row_to_entry(r) for r in rows]

    async def list_tiers(self) -> list[str]:
        if self._declared_tiers is not None:
            return list(self._declared_tiers)
        rows = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT DISTINCT tier FROM memories ORDER BY tier"
            ).fetchall()
        )
        return [r["tier"] for r in rows]

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# NullMemoryStore
# ---------------------------------------------------------------------------


class NullMemoryStore:
    """Drops every write and returns nothing on reads.

    Used when memory persistence is forbidden (privacy, compliance).
    """

    def __init__(self, tiers: list[str] | None = None) -> None:
        self._tiers = list(tiers or [])

    async def write(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    async def read(self, *args: Any, **kwargs: Any) -> MemoryEntry | None:  # noqa: ARG002
        return None

    async def search(self, *args: Any, **kwargs: Any) -> list[MemoryEntry]:  # noqa: ARG002
        return []

    async def list_tiers(self) -> list[str]:
        return list(self._tiers)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_entry(row: sqlite3.Row) -> MemoryEntry:
    import json

    metadata: dict[str, Any] = {}
    raw_meta = row["metadata"]
    if raw_meta:
        try:
            metadata = json.loads(raw_meta)
        except (ValueError, TypeError):
            metadata = {"_raw": raw_meta}
    return MemoryEntry(
        tier=row["tier"],
        scope=row["scope"] or None,
        key=row["key"],
        value=row["value"],
        metadata=metadata,
        created_at=_parse_iso(row["created_at"]),
        updated_at=_parse_iso(row["updated_at"]),
    )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
