"""SqliteMemoryStore — tier/scope schema, FTS search, NullMemoryStore fallback."""

from __future__ import annotations

import pytest

from minyoung_mah import NullMemoryStore, SqliteMemoryStore


@pytest.mark.asyncio
async def test_write_read_roundtrip_in_memory() -> None:
    store = SqliteMemoryStore(":memory:", tiers=["user", "project"])
    await store.write(
        "user",
        "name",
        "Youngsuk",
        scope=None,
        metadata={"source": "test"},
    )
    entry = await store.read("user", "name")
    assert entry is not None
    assert entry.value == "Youngsuk"
    assert entry.metadata["source"] == "test"
    store.close()


@pytest.mark.asyncio
async def test_scope_partitions_same_key() -> None:
    store = SqliteMemoryStore(":memory:")
    await store.write("project", "owner", "Alice", scope="proj-a")
    await store.write("project", "owner", "Bob", scope="proj-b")
    assert (await store.read("project", "owner", scope="proj-a")).value == "Alice"
    assert (await store.read("project", "owner", scope="proj-b")).value == "Bob"
    store.close()


@pytest.mark.asyncio
async def test_search_full_text_within_tier() -> None:
    store = SqliteMemoryStore(":memory:")
    await store.write("notes", "k1", "FastAPI deployment checklist")
    await store.write("notes", "k2", "Database migration strategy")
    await store.write("other", "k3", "FastAPI unrelated")

    results = await store.search("notes", "FastAPI")
    assert len(results) == 1
    assert results[0].key == "k1"
    store.close()


@pytest.mark.asyncio
async def test_search_scope_none_matches_all_scopes() -> None:
    store = SqliteMemoryStore(":memory:")
    await store.write("notes", "a", "shared terminology", scope="s1")
    await store.write("notes", "b", "shared terminology", scope="s2")

    scoped = await store.search("notes", "terminology", scope="s1")
    assert len(scoped) == 1

    all_results = await store.search("notes", "terminology", scope=None)
    assert len(all_results) == 2
    store.close()


@pytest.mark.asyncio
async def test_null_memory_store_drops_writes() -> None:
    store = NullMemoryStore(tiers=["user"])
    await store.write("user", "name", "Youngsuk")
    assert await store.read("user", "name") is None
    assert await store.list_tiers() == ["user"]
    assert await store.list_by_scope("user", scope="any", limit=5) == []


@pytest.mark.asyncio
async def test_list_by_scope_recent_first() -> None:
    """Default desc order returns newest entries first; id tie-breaks equal ts.
    기본 desc 정렬은 최신 항목을 먼저 반환; 동일 ts 는 id 로 tie-break."""
    store = SqliteMemoryStore(":memory:")
    await store.write("short_term", "k1", "first", scope="s1")
    await store.write("short_term", "k2", "second", scope="s1")
    await store.write("short_term", "k3", "third", scope="s1")

    rows = await store.list_by_scope("short_term", scope="s1", limit=2)
    assert [r.value for r in rows] == ["third", "second"]
    store.close()


@pytest.mark.asyncio
async def test_list_by_scope_filters_scope() -> None:
    """scope argument partitions results within the same tier.
    scope 인자는 같은 tier 안에서 결과를 분할한다."""
    store = SqliteMemoryStore(":memory:")
    await store.write("short_term", "k", "s1-value", scope="s1")
    await store.write("short_term", "k", "s2-value", scope="s2")

    rows = await store.list_by_scope("short_term", scope="s1")
    assert len(rows) == 1
    assert rows[0].value == "s1-value"
    assert rows[0].scope == "s1"
    store.close()


@pytest.mark.asyncio
async def test_list_by_scope_none_returns_all_scopes() -> None:
    """scope=None yields every scope in the tier.
    scope=None 은 tier 내 모든 scope 를 반환한다."""
    store = SqliteMemoryStore(":memory:")
    await store.write("short_term", "k1", "a", scope="s1")
    await store.write("short_term", "k2", "b", scope="s2")
    rows = await store.list_by_scope("short_term", scope=None, limit=10)
    assert {r.value for r in rows} == {"a", "b"}
    store.close()


@pytest.mark.asyncio
async def test_list_by_scope_asc_order() -> None:
    """order='asc' returns oldest first.
    order='asc' 는 가장 오래된 항목부터 반환."""
    store = SqliteMemoryStore(":memory:")
    await store.write("short_term", "k1", "first", scope="s1")
    await store.write("short_term", "k2", "second", scope="s1")
    rows = await store.list_by_scope("short_term", scope="s1", order="asc", limit=10)
    assert [r.value for r in rows] == ["first", "second"]
    store.close()


@pytest.mark.asyncio
async def test_list_by_scope_rejects_invalid_order() -> None:
    """Invalid order values raise ValueError before touching the DB.
    잘못된 order 값은 DB 에 닿기 전에 ValueError 로 거부한다."""
    store = SqliteMemoryStore(":memory:")
    with pytest.raises(ValueError, match="order must be"):
        await store.list_by_scope("short_term", scope="s", order="sideways")
    store.close()
