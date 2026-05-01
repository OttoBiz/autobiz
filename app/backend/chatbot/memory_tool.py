"""Memory-tool implementation for pydantic_ai agents.

Six commands matching the contract of Anthropic's `memory_20250818`:
- view (file or directory)
- create
- str_replace
- insert
- delete
- rename

Storage is `db.tenant_memory`, scoped by `business_id` read from
`RunContext.deps.business_id`. Path validation happens at this layer
(defense-in-depth) and again in the storage layer.

Return strings match the Anthropic spec where the agent has been trained
on specific shapes (line-numbered file content, sized directory listings,
exact error phrasings) so model intuition transfers without re-prompting.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from pydantic_ai import Agent, RunContext

from backend.db import tenant_memory
from backend.db.tenant_memory import (
    InvalidMemoryPath,
    MEMORY_ROOT,
)


class _HasBusinessId(Protocol):
    business_id: UUID


# ---------------------------------------------------------------------------
# Output formatters — match Anthropic's memory tool string shapes.
# ---------------------------------------------------------------------------


def _format_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f}M"
    if n >= 1024:
        return f"{n / 1024:.1f}K"
    return f"{n}B"


def _format_directory(path: str, listings: list) -> str:
    lines = [
        f"Here're the files and directories up to 2 levels deep in {path}, "
        "excluding hidden items and node_modules:"
    ]
    # Synthetic header for the queried directory itself.
    total_bytes = sum(l.size_bytes for l in listings if not l.is_directory)
    lines.append(f"{_format_size(total_bytes)}\t{path}")
    for entry in listings:
        if entry.is_directory:
            lines.append(f"4.0K\t{entry.path}")
        else:
            lines.append(f"{_format_size(entry.size_bytes)}\t{entry.path}")
    return "\n".join(lines)


def _format_file(path: str, content: str, view_range: list[int] | None) -> str:
    lines = content.split("\n")
    # Trailing newline produces an extra empty entry; drop it for display.
    if lines and lines[-1] == "":
        lines = lines[:-1]

    if view_range is not None:
        start, end = view_range
        if start < 1 or start > len(lines):
            return (
                f"Error: Invalid `view_range` parameter: {view_range}. "
                f"It should be within the range of lines of the file: [1, {len(lines)}]"
            )
        # Clamp end to the file length.
        end = min(end, len(lines))
        slice_start = start - 1
        slice_end = end
        offset = start
        sliced = lines[slice_start:slice_end]
    else:
        sliced = lines
        offset = 1

    formatted = [f"Here's the content of {path} with line numbers:"]
    for idx, line in enumerate(sliced):
        formatted.append(f"{offset + idx:>6}\t{line}")
    return "\n".join(formatted)


def _no_path_error(path: str) -> str:
    return f"Error: The path {path} does not exist. Please provide a valid path."


# ---------------------------------------------------------------------------
# The six commands. Each is a free function taking (business_id, **kwargs)
# so the unit tests can exercise behavior without spinning up an Agent.
# Tools register thin wrappers that pull business_id from RunContext.deps.
# ---------------------------------------------------------------------------


async def memory_view(
    business_id: UUID, path: str, view_range: list[int] | None = None
) -> str:
    """Show directory contents or file contents (with optional line range)."""
    try:
        # We don't pre-validate here because list_directory needs allow_root
        # for /memories itself; let the storage layer pick the right rule.
        # Try file read first.
        if path == MEMORY_ROOT or path.rstrip("/") == MEMORY_ROOT:
            listings = await tenant_memory.list_directory(business_id, path)
            return _format_directory(MEMORY_ROOT, listings)

        file = await tenant_memory.read_file(business_id, path)
        if file is not None:
            return _format_file(path, file.content, view_range)

        # Not a file — try treating as a directory.
        listings = await tenant_memory.list_directory(business_id, path)
        if listings:
            return _format_directory(path, listings)

        return _no_path_error(path)
    except InvalidMemoryPath as exc:
        return f"Error: {exc}"


async def memory_create(business_id: UUID, path: str, file_text: str) -> str:
    try:
        await tenant_memory.create_file(business_id, path, file_text)
        return f"File created successfully at: {path}"
    except FileExistsError:
        return f"Error: File {path} already exists"
    except InvalidMemoryPath as exc:
        return f"Error: {exc}"


async def memory_str_replace(
    business_id: UUID, path: str, old_str: str, new_str: str
) -> str:
    try:
        file = await tenant_memory.read_file(business_id, path)
    except InvalidMemoryPath as exc:
        return f"Error: {exc}"
    if file is None:
        return _no_path_error(path)
    occurrences = file.content.count(old_str)
    if occurrences == 0:
        return (
            f"No replacement was performed, old_str `{old_str}` did not appear "
            f"verbatim in {path}."
        )
    if occurrences > 1:
        # Find line numbers of each occurrence for the agent to disambiguate.
        line_numbers = []
        for idx, line in enumerate(file.content.split("\n"), 1):
            if old_str in line:
                line_numbers.append(str(idx))
        return (
            f"No replacement was performed. Multiple occurrences of old_str "
            f"`{old_str}` in lines: {','.join(line_numbers)}. Please ensure it is unique"
        )
    new_content = file.content.replace(old_str, new_str, 1)
    await tenant_memory.update_file(business_id, path, new_content)
    snippet = _format_file(path, new_content, None)
    return f"The memory file has been edited.\n\n{snippet}"


async def memory_insert(
    business_id: UUID, path: str, insert_line: int, insert_text: str
) -> str:
    try:
        file = await tenant_memory.read_file(business_id, path)
    except InvalidMemoryPath as exc:
        return f"Error: {exc}"
    if file is None:
        return f"Error: The path {path} does not exist"
    lines = file.content.split("\n")
    # Trim trailing blank from a final newline so insert_line numbering aligns
    # with the user-visible content. Reattach when serializing.
    had_trailing_newline = file.content.endswith("\n")
    if had_trailing_newline and lines and lines[-1] == "":
        lines = lines[:-1]
    n_lines = len(lines)
    if insert_line < 0 or insert_line > n_lines:
        return (
            f"Error: Invalid `insert_line` parameter: {insert_line}. "
            f"It should be within the range of lines of the file: [0, {n_lines}]"
        )
    # Spec: insert AFTER `insert_line`. insert_line=0 means prepend.
    insert_payload = insert_text.rstrip("\n").split("\n")
    new_lines = lines[:insert_line] + insert_payload + lines[insert_line:]
    new_content = "\n".join(new_lines)
    if had_trailing_newline or insert_text.endswith("\n"):
        new_content += "\n"
    await tenant_memory.update_file(business_id, path, new_content)
    return f"The file {path} has been edited."


async def memory_delete(business_id: UUID, path: str) -> str:
    try:
        deleted = await tenant_memory.delete_path(business_id, path)
    except InvalidMemoryPath as exc:
        return f"Error: {exc}"
    if deleted == 0:
        return f"Error: The path {path} does not exist"
    return f"Successfully deleted {path}"


async def memory_rename(
    business_id: UUID, old_path: str, new_path: str
) -> str:
    try:
        await tenant_memory.rename(business_id, old_path, new_path)
    except FileNotFoundError:
        return f"Error: The path {old_path} does not exist"
    except FileExistsError:
        return f"Error: The destination {new_path} already exists"
    except InvalidMemoryPath as exc:
        return f"Error: {exc}"
    return f"Successfully renamed {old_path} to {new_path}"


# ---------------------------------------------------------------------------
# Registration — call once per Agent.
# ---------------------------------------------------------------------------


def register_memory_tools(agent: Agent[Any, Any]) -> None:
    """Attach the six memory tools to `agent`.

    Agent's deps must have a `business_id: UUID` attribute. All paths are
    scoped to that tenant via the storage layer.
    """

    @agent.tool
    async def memory_view_tool(
        ctx: RunContext[_HasBusinessId],
        path: str,
        view_range: list[int] | None = None,
    ) -> str:
        """Show directory contents or file contents.

        Use to look at memory before doing work. `path` must be under
        /memories/. `view_range` is [start, end] inclusive (1-indexed) for
        file views; omit to read the whole file.
        """
        return await memory_view(ctx.deps.business_id, path, view_range)

    @agent.tool
    async def memory_create_tool(
        ctx: RunContext[_HasBusinessId], path: str, file_text: str
    ) -> str:
        """Create a new file in /memories/ with the given text.

        Errors if the path already exists — use str_replace or insert to
        modify an existing file.
        """
        return await memory_create(ctx.deps.business_id, path, file_text)

    @agent.tool
    async def memory_str_replace_tool(
        ctx: RunContext[_HasBusinessId],
        path: str,
        old_str: str,
        new_str: str,
    ) -> str:
        """Replace `old_str` with `new_str` in a memory file.

        `old_str` must match exactly once. If it appears multiple times,
        include surrounding context to make the match unique.
        """
        return await memory_str_replace(
            ctx.deps.business_id, path, old_str, new_str
        )

    @agent.tool
    async def memory_insert_tool(
        ctx: RunContext[_HasBusinessId],
        path: str,
        insert_line: int,
        insert_text: str,
    ) -> str:
        """Insert text AFTER the given line number (0 means prepend)."""
        return await memory_insert(
            ctx.deps.business_id, path, insert_line, insert_text
        )

    @agent.tool
    async def memory_delete_tool(
        ctx: RunContext[_HasBusinessId], path: str
    ) -> str:
        """Delete a file or every file under a directory prefix."""
        return await memory_delete(ctx.deps.business_id, path)

    @agent.tool
    async def memory_rename_tool(
        ctx: RunContext[_HasBusinessId], old_path: str, new_path: str
    ) -> str:
        """Rename or move a memory file. Errors if destination exists."""
        return await memory_rename(ctx.deps.business_id, old_path, new_path)
