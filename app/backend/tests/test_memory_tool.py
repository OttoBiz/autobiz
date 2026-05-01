"""Tests for the memory_tool command layer.

The storage layer (`tenant_memory`) is monkeypatched on a per-test basis.
The point of these tests is to lock in the OUTPUT STRING shapes the
agent has been trained on (Anthropic memory_20250818 spec).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from backend.chatbot import memory_tool
from backend.db.tenant_memory import (
    InvalidMemoryPath,
    MemoryFile,
    MemoryListing,
)


def _file(path="/memories/foo.md", content="hello"):
    now = datetime.now(timezone.utc)
    return MemoryFile(
        business_id=uuid4(),
        path=path,
        content=content,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# memory_view
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_view_directory_emits_anthropic_listing_format(monkeypatch):
    listings = [
        MemoryListing(
            path="/memories/foo.md", is_directory=False, size_bytes=1500
        ),
        MemoryListing(path="/memories/vendors", is_directory=True),
    ]
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "list_directory",
        AsyncMock(return_value=listings),
    )

    output = await memory_tool.memory_view(uuid4(), "/memories")

    assert (
        "Here're the files and directories up to 2 levels deep in /memories"
        in output
    )
    assert "1.5K\t/memories/foo.md" in output
    assert "4.0K\t/memories/vendors" in output


@pytest.mark.asyncio
async def test_view_file_emits_line_numbered_content(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "read_file",
        AsyncMock(return_value=_file(content="line one\nline two\nline three")),
    )

    output = await memory_tool.memory_view(uuid4(), "/memories/foo.md")

    assert "Here's the content of /memories/foo.md with line numbers:" in output
    assert "     1\tline one" in output
    assert "     2\tline two" in output
    assert "     3\tline three" in output


@pytest.mark.asyncio
async def test_view_file_with_view_range_subsets_lines(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "read_file",
        AsyncMock(return_value=_file(content="line one\nline two\nline three")),
    )

    output = await memory_tool.memory_view(
        uuid4(), "/memories/foo.md", view_range=[2, 3]
    )

    assert "     2\tline two" in output
    assert "     3\tline three" in output
    assert "line one" not in output


@pytest.mark.asyncio
async def test_view_file_with_invalid_view_range_returns_error_string(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "read_file",
        AsyncMock(return_value=_file(content="a\nb\nc")),
    )

    output = await memory_tool.memory_view(
        uuid4(), "/memories/foo.md", view_range=[10, 20]
    )

    assert output.startswith("Error: Invalid `view_range` parameter")


@pytest.mark.asyncio
async def test_view_returns_no_path_error_when_missing(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory, "read_file", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        memory_tool.tenant_memory, "list_directory", AsyncMock(return_value=[])
    )

    output = await memory_tool.memory_view(uuid4(), "/memories/missing.md")

    assert (
        output
        == "Error: The path /memories/missing.md does not exist. Please provide a valid path."
    )


@pytest.mark.asyncio
async def test_view_falls_back_to_directory_listing_when_path_isnt_a_file(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory, "read_file", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "list_directory",
        AsyncMock(
            return_value=[
                MemoryListing(
                    path="/memories/vendors/adamu.md",
                    is_directory=False,
                    size_bytes=200,
                )
            ]
        ),
    )

    output = await memory_tool.memory_view(uuid4(), "/memories/vendors")

    assert (
        "Here're the files and directories up to 2 levels deep in /memories/vendors"
        in output
    )
    assert "/memories/vendors/adamu.md" in output


@pytest.mark.asyncio
async def test_view_returns_error_string_for_invalid_path(monkeypatch):
    async def boom(*a, **k):
        raise InvalidMemoryPath("path must be under /memories/")

    monkeypatch.setattr(memory_tool.tenant_memory, "read_file", boom)
    monkeypatch.setattr(memory_tool.tenant_memory, "list_directory", boom)

    output = await memory_tool.memory_view(uuid4(), "/etc/passwd")

    assert output.startswith("Error:")


# ---------------------------------------------------------------------------
# memory_create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_returns_success_string(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "create_file",
        AsyncMock(return_value=_file()),
    )

    output = await memory_tool.memory_create(
        uuid4(), "/memories/foo.md", "hi"
    )

    assert output == "File created successfully at: /memories/foo.md"


@pytest.mark.asyncio
async def test_create_returns_already_exists_error_on_FileExistsError(monkeypatch):
    async def raises(*a, **k):
        raise FileExistsError("dup")

    monkeypatch.setattr(memory_tool.tenant_memory, "create_file", raises)

    output = await memory_tool.memory_create(
        uuid4(), "/memories/foo.md", "hi"
    )

    assert output == "Error: File /memories/foo.md already exists"


@pytest.mark.asyncio
async def test_create_returns_validation_error_string_on_invalid_path(monkeypatch):
    async def raises(*a, **k):
        raise InvalidMemoryPath("must start with /memories/")

    monkeypatch.setattr(memory_tool.tenant_memory, "create_file", raises)

    output = await memory_tool.memory_create(uuid4(), "/etc/passwd", "x")

    assert output.startswith("Error:")
    assert "must start with /memories/" in output


# ---------------------------------------------------------------------------
# memory_str_replace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_str_replace_success_emits_edit_message_and_snippet(monkeypatch):
    file = _file(content="hello world")
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "read_file",
        AsyncMock(return_value=file),
    )
    update_mock = AsyncMock(return_value=file)
    monkeypatch.setattr(memory_tool.tenant_memory, "update_file", update_mock)

    output = await memory_tool.memory_str_replace(
        uuid4(), "/memories/foo.md", "world", "there"
    )

    assert output.startswith("The memory file has been edited.")
    assert "Here's the content of /memories/foo.md with line numbers:" in output
    assert "     1\thello there" in output
    update_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_str_replace_returns_no_path_error_when_file_missing(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory, "read_file", AsyncMock(return_value=None)
    )

    output = await memory_tool.memory_str_replace(
        uuid4(), "/memories/missing.md", "x", "y"
    )

    assert (
        output
        == "Error: The path /memories/missing.md does not exist. Please provide a valid path."
    )


@pytest.mark.asyncio
async def test_str_replace_returns_not_found_when_old_str_not_in_content(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "read_file",
        AsyncMock(return_value=_file(content="hello world")),
    )

    output = await memory_tool.memory_str_replace(
        uuid4(), "/memories/foo.md", "goodbye", "y"
    )

    assert output == (
        "No replacement was performed, old_str `goodbye` did not appear "
        "verbatim in /memories/foo.md."
    )


@pytest.mark.asyncio
async def test_str_replace_returns_duplicate_error_with_line_numbers_when_multiple(
    monkeypatch,
):
    content = "alpha\nfoo\nbeta\ngamma\nfoo\n"
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "read_file",
        AsyncMock(return_value=_file(content=content)),
    )

    output = await memory_tool.memory_str_replace(
        uuid4(), "/memories/foo.md", "foo", "bar"
    )

    assert output == (
        "No replacement was performed. Multiple occurrences of old_str "
        "`foo` in lines: 2,5. Please ensure it is unique"
    )


# ---------------------------------------------------------------------------
# memory_insert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_appends_after_given_line(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "read_file",
        AsyncMock(return_value=_file(content="a\nb\nc\n")),
    )
    update_mock = AsyncMock(return_value=_file())
    monkeypatch.setattr(memory_tool.tenant_memory, "update_file", update_mock)

    output = await memory_tool.memory_insert(
        uuid4(), "/memories/foo.md", 2, "x"
    )

    assert output == "The file /memories/foo.md has been edited."
    args = update_mock.await_args.args
    # signature: (business_id, path, content)
    assert args[1] == "/memories/foo.md"
    assert args[2] == "a\nb\nx\nc\n"


@pytest.mark.asyncio
async def test_insert_at_zero_prepends(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "read_file",
        AsyncMock(return_value=_file(content="a\nb\nc\n")),
    )
    update_mock = AsyncMock(return_value=_file())
    monkeypatch.setattr(memory_tool.tenant_memory, "update_file", update_mock)

    await memory_tool.memory_insert(uuid4(), "/memories/foo.md", 0, "x")

    args = update_mock.await_args.args
    assert args[2] == "x\na\nb\nc\n"


@pytest.mark.asyncio
async def test_insert_with_invalid_line_returns_error_string(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory,
        "read_file",
        AsyncMock(return_value=_file(content="a\nb\nc\n")),
    )

    output = await memory_tool.memory_insert(
        uuid4(), "/memories/foo.md", 99, "x"
    )

    assert output.startswith(
        "Error: Invalid `insert_line` parameter: 99."
    )
    assert "[0, 3]" in output


@pytest.mark.asyncio
async def test_insert_returns_path_error_when_file_missing(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory, "read_file", AsyncMock(return_value=None)
    )

    output = await memory_tool.memory_insert(
        uuid4(), "/memories/missing.md", 0, "x"
    )

    assert output == "Error: The path /memories/missing.md does not exist"


# ---------------------------------------------------------------------------
# memory_delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_returns_success_when_rowcount_positive(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory, "delete_path", AsyncMock(return_value=3)
    )

    output = await memory_tool.memory_delete(uuid4(), "/memories/vendors")

    assert output == "Successfully deleted /memories/vendors"


@pytest.mark.asyncio
async def test_delete_returns_path_error_when_rowcount_zero(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory, "delete_path", AsyncMock(return_value=0)
    )

    output = await memory_tool.memory_delete(uuid4(), "/memories/missing")

    assert output == "Error: The path /memories/missing does not exist"


# ---------------------------------------------------------------------------
# memory_rename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_returns_success_string(monkeypatch):
    monkeypatch.setattr(
        memory_tool.tenant_memory, "rename", AsyncMock(return_value=_file())
    )

    output = await memory_tool.memory_rename(
        uuid4(), "/memories/old.md", "/memories/new.md"
    )

    assert output == "Successfully renamed /memories/old.md to /memories/new.md"


@pytest.mark.asyncio
async def test_rename_returns_source_missing_error(monkeypatch):
    async def raises(*a, **k):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(memory_tool.tenant_memory, "rename", raises)

    output = await memory_tool.memory_rename(
        uuid4(), "/memories/old.md", "/memories/new.md"
    )

    assert output == "Error: The path /memories/old.md does not exist"


@pytest.mark.asyncio
async def test_rename_returns_destination_exists_error(monkeypatch):
    async def raises(*a, **k):
        raise FileExistsError("dup")

    monkeypatch.setattr(memory_tool.tenant_memory, "rename", raises)

    output = await memory_tool.memory_rename(
        uuid4(), "/memories/old.md", "/memories/new.md"
    )

    assert output == "Error: The destination /memories/new.md already exists"


# ---------------------------------------------------------------------------
# register_memory_tools
# ---------------------------------------------------------------------------


@dataclass
class _Deps:
    business_id: UUID


def test_register_memory_tools_adds_six_tools():
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    agent = Agent(model=TestModel(), deps_type=_Deps)
    memory_tool.register_memory_tools(agent)

    tool_names = set(agent._function_toolset.tools.keys())
    expected = {
        "memory_view_tool",
        "memory_create_tool",
        "memory_str_replace_tool",
        "memory_insert_tool",
        "memory_delete_tool",
        "memory_rename_tool",
    }
    assert expected.issubset(tool_names)
