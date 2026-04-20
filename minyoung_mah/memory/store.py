"""Default :class:`MemoryStore` implementations.
:class:`MemoryStore` 기본 구현체들.

Two backends ship with the library:

라이브러리에 두 가지 백엔드가 함께 제공된다:

- :class:`SqliteMemoryStore` — opinionated default. SQLite + FTS5 full-text
  index, ``(tier, scope, key)`` unique constraint. Tier and scope are
  application-defined strings; the library enforces no semantics on them.
- :class:`SqliteMemoryStore` — opinionated 기본값. SQLite + FTS5 full-text
  인덱스, ``(tier, scope, key)`` unique 제약. tier 와 scope 는 애플리케이션이
  정의하는 문자열이며, 라이브러리는 그 의미에 대해 어떤 강제도 하지 않는다.
- :class:`NullMemoryStore` — drops every write. Required for apps that
  cannot persist memory (e.g. apt-legal's privacy constraint).
- :class:`NullMemoryStore` — 모든 write 를 버린다. 메모리를 영속화할 수 없는
  앱(예: apt-legal 의 프라이버시 제약)에 필요.

The schema was redesigned from the ax coding agent original: ``layer`` →
``tier``, ``project_id`` → ``scope``. Per decision D1 the old DB format
is intentionally incompatible — a fresh start is simpler than a migration
tool for the rare users who had real data in the old schema.

스키마는 ax coding agent 원본에서 재설계되었다: ``layer`` → ``tier``,
``project_id`` → ``scope``. 결정 D1 에 따라 구 DB 포맷과 의도적으로 호환되지
않는다 — 구 스키마에 실제 데이터를 가진 드문 사용자를 위한 마이그레이션
도구보다 fresh start 가 단순하다.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
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
    SQLite + FTS5 백엔드의 메모리 스토어. tier/scope 파티셔닝 지원.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file. Parent dirs are created.
        Use ``":memory:"`` for an ephemeral store (handy in tests).
        SQLite 파일 경로. 상위 디렉토리는 자동 생성. ``":memory:"`` 를 주면
        ephemeral 스토어가 된다(테스트에 유용).
    tiers:
        Optional declared tier names. When set, :meth:`list_tiers` returns
        this list instead of querying the table. Writes to undeclared tiers
        are still allowed — the list is informational.
        선택적으로 선언된 tier 이름들. 지정하면 :meth:`list_tiers` 가 테이블
        조회 대신 이 리스트를 반환한다. 선언되지 않은 tier 에 대한 write 도
        여전히 허용된다 — 리스트는 정보성일 뿐.
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

    # -- schema -------------------------------------------------------- 스키마

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_CREATE_MEMORIES)
        cur.execute(_CREATE_TIER_IDX)
        cur.execute(_CREATE_FTS)
        for trigger_sql in _TRIGGERS:
            cur.execute(trigger_sql)
        self._conn.commit()

    # -- MemoryStore protocol ----------------------------------------- MemoryStore 프로토콜

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
        now = datetime.now(timezone.utc).isoformat()
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

    async def list_by_scope(
        self,
        tier: str,
        scope: str | None = None,
        limit: int = 10,
        order: str = "desc",
    ) -> list[MemoryEntry]:
        """Recent-first (or ascending) list of entries within ``(tier, scope)``.
        ``(tier, scope)`` 범위 항목을 최근순(또는 오름차순)으로 반환.

        Bypasses the FTS index entirely. ``id`` is used as a deterministic
        tie-breaker when ``created_at`` ties (back-to-back writes within the
        same ISO second).

        FTS 인덱스를 통하지 않는다. ``created_at`` 이 동률일 때(같은 ISO 초
        안의 연속 write) ``id`` 를 결정론적 tie-breaker 로 사용한다.
        """
        if order not in ("asc", "desc"):
            raise ValueError(f"order must be 'asc' or 'desc', got {order!r}")
        direction = order.upper()
        sql = "SELECT * FROM memories WHERE tier = ?"
        params: list[Any] = [tier]
        if scope is not None:
            sql += " AND scope = ?"
            params.append(scope)
        sql += f" ORDER BY created_at {direction}, id {direction} LIMIT ?"
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
    모든 write 를 버리고 read 에서는 아무 것도 반환하지 않는다.

    Used when memory persistence is forbidden (privacy, compliance).
    메모리 영속화가 금지된 경우(프라이버시, 컴플라이언스)에 사용한다.
    """

    def __init__(self, tiers: list[str] | None = None) -> None:
        self._tiers = list(tiers or [])

    async def write(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    async def read(self, *args: Any, **kwargs: Any) -> MemoryEntry | None:  # noqa: ARG002
        return None

    async def search(self, *args: Any, **kwargs: Any) -> list[MemoryEntry]:  # noqa: ARG002
        return []

    async def list_by_scope(self, *args: Any, **kwargs: Any) -> list[MemoryEntry]:  # noqa: ARG002
        return []

    async def list_tiers(self) -> list[str]:
        return list(self._tiers)


# ---------------------------------------------------------------------------
# Helpers — 헬퍼
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
