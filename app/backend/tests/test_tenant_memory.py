"""Tests for the tenant memory storage layer.

Path validation is exercised directly. CRUD paths use the same
FakePool/FakeConn pattern other DB-accessor tests use; we mock the
asyncpg pool and assert SQL shape + parameter ordering plus
return-value/exception mapping.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.db import tenant_memory
from backend.db.tenant_memory import (
    InvalidMemoryPath,
    MemoryFile,
    MemoryListing,
)


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


def _file_row(business_id, path="/memories/foo.md", content="hello"):
    now = datetime.now(timezone.utc)
    return {
        "business_id": business_id,
        "path": path,
        "content": content,
        "created_at": now,
        "updated_at": now,
    }


class _FakeTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeConn:
    def __init__(self) -> None:
        self.fetchrow = AsyncMock(return_value=None)
        self.fetch = AsyncMock(return_value=[])
        self.execute = AsyncMock(return_value="DELETE 0")

    def transaction(self):
        return _FakeTxn()


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> Any:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=self._conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm


@pytest.fixture
def conn() -> _FakeConn:
    return _FakeConn()


@pytest.fixture(autouse=True)
def patch_pool(monkeypatch, conn):
    pool = _FakePool(conn)

    async def fake_get_db() -> _FakePool:
        return pool

    monkeypatch.setattr(tenant_memory, "get_db", fake_get_db)
    return pool


# ---------------------------------------------------------------------------
# Path validation. No DB needed.
# ---------------------------------------------------------------------------


class TestValidatePath:
    def test_path_must_start_with_memories_prefix(self):
        assert tenant_memory._validate_path("/memories/foo.md") == "/memories/foo.md"
        for bad in ["/somewhere/else.md", "foo.md", ""]:
            with pytest.raises(InvalidMemoryPath):
                tenant_memory._validate_path(bad)

    def test_path_rejects_dot_dot_traversal(self):
        for bad in ["/memories/../etc/passwd", "/memories/foo/../../etc"]:
            with pytest.raises(InvalidMemoryPath):
                tenant_memory._validate_path(bad)

    def test_path_rejects_url_encoded_escapes(self):
        bad_paths = [
            "/memories/%2e%2e/foo",
            "/memories/%2E%2E/foo",
            "/memories/foo%2fbar",
            "/memories/foo%2Fbar",
            "/memories/foo%5cbar",
            "/memories/foo%5Cbar",
        ]
        for bad in bad_paths:
            with pytest.raises(InvalidMemoryPath):
                tenant_memory._validate_path(bad)

    def test_path_rejects_backslash(self):
        for bad in ["/memories\\foo.md", "/memories/foo\\bar"]:
            with pytest.raises(InvalidMemoryPath):
                tenant_memory._validate_path(bad)

    def test_path_collapses_double_slashes(self):
        assert (
            tenant_memory._validate_path("/memories//foo.md") == "/memories/foo.md"
        )

    def test_path_root_requires_allow_root(self):
        with pytest.raises(InvalidMemoryPath):
            tenant_memory._validate_path("/memories")
        assert (
            tenant_memory._validate_path("/memories", allow_root=True)
            == "/memories"
        )

    def test_path_canonical_form_strips_trailing_slash(self):
        assert (
            tenant_memory._validate_path("/memories/foo/") == "/memories/foo"
        )


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_returns_file_when_present(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = _file_row(business_id, content="data")

    result = await tenant_memory.read_file(business_id, "/memories/foo.md")

    assert isinstance(result, MemoryFile)
    assert result.business_id == business_id
    assert result.path == "/memories/foo.md"
    assert result.content == "data"


@pytest.mark.asyncio
async def test_read_file_returns_none_when_missing(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = None

    result = await tenant_memory.read_file(business_id, "/memories/missing.md")

    assert result is None
    sql, *params = conn.fetchrow.call_args.args
    norm = _normalize(sql)
    assert "FROM tenant_memory" in norm
    assert "business_id = $1 AND path = $2" in norm
    assert params == [business_id, "/memories/missing.md"]


@pytest.mark.asyncio
async def test_read_file_validates_path(conn):
    with pytest.raises(InvalidMemoryPath):
        await tenant_memory.read_file(uuid4(), "/etc/passwd")
    conn.fetchrow.assert_not_called()


# ---------------------------------------------------------------------------
# create_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_file_inserts_and_returns_row(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = _file_row(business_id, content="hi")

    result = await tenant_memory.create_file(
        business_id, "/memories/foo.md", "hi"
    )

    assert isinstance(result, MemoryFile)
    assert result.content == "hi"
    sql, *params = conn.fetchrow.call_args.args
    norm = _normalize(sql)
    assert "INSERT INTO tenant_memory" in norm
    assert "(business_id, path, content)" in norm
    assert "ON CONFLICT" not in norm
    assert "RETURNING business_id, path, content, created_at, updated_at" in norm
    assert params == [business_id, "/memories/foo.md", "hi"]


@pytest.mark.asyncio
async def test_create_file_raises_FileExistsError_on_unique_violation(conn):
    conn.fetchrow.side_effect = Exception(
        'duplicate key value violates unique constraint "tenant_memory_pkey"'
    )

    with pytest.raises(FileExistsError):
        await tenant_memory.create_file(uuid4(), "/memories/foo.md", "hi")


@pytest.mark.asyncio
async def test_create_file_raises_FileExistsError_on_duplicate_key_message(conn):
    conn.fetchrow.side_effect = Exception("duplicate key")

    with pytest.raises(FileExistsError):
        await tenant_memory.create_file(uuid4(), "/memories/foo.md", "hi")


@pytest.mark.asyncio
async def test_create_file_reraises_unrelated_db_errors(conn):
    conn.fetchrow.side_effect = Exception("connection lost")

    with pytest.raises(Exception) as excinfo:
        await tenant_memory.create_file(uuid4(), "/memories/foo.md", "hi")
    assert not isinstance(excinfo.value, FileExistsError)


# ---------------------------------------------------------------------------
# update_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_file_modifies_content(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = _file_row(business_id, content="new")

    result = await tenant_memory.update_file(
        business_id, "/memories/foo.md", "new"
    )

    assert result.content == "new"
    sql, *params = conn.fetchrow.call_args.args
    norm = _normalize(sql)
    assert "UPDATE tenant_memory" in norm
    assert "WHERE business_id = $1 AND path = $2" in norm
    assert "RETURNING business_id, path, content, created_at, updated_at" in norm
    assert params == [business_id, "/memories/foo.md", "new"]


@pytest.mark.asyncio
async def test_update_file_raises_FileNotFoundError_when_missing(conn):
    conn.fetchrow.return_value = None

    with pytest.raises(FileNotFoundError):
        await tenant_memory.update_file(uuid4(), "/memories/foo.md", "new")


# ---------------------------------------------------------------------------
# delete_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_path_returns_count_for_single_file(conn):
    conn.execute.return_value = "DELETE 1"

    result = await tenant_memory.delete_path(uuid4(), "/memories/foo.md")

    assert result == 1
    # Only the single-file delete should have run.
    assert conn.execute.call_count == 1


@pytest.mark.asyncio
async def test_delete_path_falls_back_to_directory_prefix_when_single_match_misses(conn):
    business_id = uuid4()
    conn.execute.side_effect = ["DELETE 0", "DELETE 3"]

    result = await tenant_memory.delete_path(business_id, "/memories/vendors")

    assert result == 3
    assert conn.execute.call_count == 2
    second_sql, *second_params = conn.execute.call_args_list[1].args
    norm = _normalize(second_sql)
    assert "DELETE FROM tenant_memory" in norm
    assert "path LIKE $2" in norm
    assert second_params == [business_id, "/memories/vendors/%"]


@pytest.mark.asyncio
async def test_delete_path_returns_zero_when_nothing_matches(conn):
    conn.execute.side_effect = ["DELETE 0", "DELETE 0"]

    assert await tenant_memory.delete_path(uuid4(), "/memories/nope") == 0


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_moves_single_file(conn):
    business_id = uuid4()
    new_row = _file_row(business_id, path="/memories/new.md", content="data")
    # First fetchrow: existence check (None — destination free).
    # Second fetchrow: UPDATE returning new row.
    conn.fetchrow.side_effect = [None, new_row]

    result = await tenant_memory.rename(
        business_id, "/memories/old.md", "/memories/new.md"
    )

    assert isinstance(result, MemoryFile)
    assert result.path == "/memories/new.md"
    assert conn.fetchrow.call_count == 2
    update_sql, *update_params = conn.fetchrow.call_args_list[1].args
    norm = _normalize(update_sql)
    assert "UPDATE tenant_memory" in norm
    assert "SET path = $3" in norm
    assert "WHERE business_id = $1 AND path = $2" in norm
    assert update_params == [
        business_id,
        "/memories/old.md",
        "/memories/new.md",
    ]


@pytest.mark.asyncio
async def test_rename_raises_FileExistsError_when_destination_exists(conn):
    conn.fetchrow.side_effect = [{"?column?": 1}]

    with pytest.raises(FileExistsError):
        await tenant_memory.rename(
            uuid4(), "/memories/old.md", "/memories/new.md"
        )
    # UPDATE never executed.
    assert conn.fetchrow.call_count == 1


@pytest.mark.asyncio
async def test_rename_raises_FileNotFoundError_when_source_missing(conn):
    conn.fetchrow.side_effect = [None, None]

    with pytest.raises(FileNotFoundError):
        await tenant_memory.rename(
            uuid4(), "/memories/old.md", "/memories/new.md"
        )


@pytest.mark.asyncio
async def test_rename_to_same_path_returns_existing_file_without_modification(conn):
    business_id = uuid4()
    conn.fetchrow.return_value = _file_row(business_id, path="/memories/foo.md")

    result = await tenant_memory.rename(
        business_id, "/memories/foo.md", "/memories/foo.md"
    )

    assert isinstance(result, MemoryFile)
    assert result.path == "/memories/foo.md"
    # Only the read_file fetchrow ran — no UPDATE.
    assert conn.fetchrow.call_count == 1
    sql = conn.fetchrow.call_args.args[0]
    assert "SELECT" in _normalize(sql)
    assert "UPDATE" not in _normalize(sql)


@pytest.mark.asyncio
async def test_rename_to_same_path_when_missing_raises(conn):
    conn.fetchrow.return_value = None
    with pytest.raises(FileNotFoundError):
        await tenant_memory.rename(
            uuid4(), "/memories/foo.md", "/memories/foo.md"
        )


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_directory_returns_files_at_top_level(conn):
    business_id = uuid4()
    conn.fetch.return_value = [
        {"path": "/memories/a.md", "size_bytes": 10},
        {"path": "/memories/b.md", "size_bytes": 20},
    ]

    result = await tenant_memory.list_directory(business_id, "/memories")

    assert len(result) == 2
    assert all(isinstance(r, MemoryListing) for r in result)
    assert [r.path for r in result] == ["/memories/a.md", "/memories/b.md"]
    assert all(not r.is_directory for r in result)
    assert result[0].size_bytes == 10
    assert result[1].size_bytes == 20


@pytest.mark.asyncio
async def test_list_directory_synthesizes_directories_from_path_prefixes(conn):
    business_id = uuid4()
    conn.fetch.return_value = [
        {"path": "/memories/a.md", "size_bytes": 10},
        {"path": "/memories/vendors/adamu.md", "size_bytes": 30},
        {"path": "/memories/vendors/dhl.md", "size_bytes": 40},
    ]

    result = await tenant_memory.list_directory(business_id, "/memories")

    assert len(result) == 2
    file_entries = [r for r in result if not r.is_directory]
    dir_entries = [r for r in result if r.is_directory]
    assert len(file_entries) == 1
    assert file_entries[0].path == "/memories/a.md"
    assert len(dir_entries) == 1
    assert dir_entries[0].path == "/memories/vendors"


@pytest.mark.asyncio
async def test_list_directory_dir_path_can_be_root(conn):
    conn.fetch.return_value = []
    # Should not raise.
    result = await tenant_memory.list_directory(uuid4(), "/memories")
    assert result == []


@pytest.mark.asyncio
async def test_list_directory_dir_path_must_be_under_memories(conn):
    with pytest.raises(InvalidMemoryPath):
        await tenant_memory.list_directory(uuid4(), "/etc")
    conn.fetch.assert_not_called()
