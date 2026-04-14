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
