"""Tenant-scoped agent memory — file-system-shaped storage.

Backs the memory tool exposed to central + outbound agents. Mirrors the
contract of Anthropic's `memory_20250818`: the agent operates on paths
under `/memories/` and the harness translates each operation into rows
in `tenant_memory`.

Why file-shaped instead of a single text blob:
- The agent decides what to remember and how to organize it. Multiple
  files (`/memories/vendors/adamu.md`, `/memories/operations.md`) keep
  topics separate so the agent can read just what's relevant on a given
  turn. A single blob forces "load everything, every turn" and balloons
  the prompt.
- Mirrors the Claude memory-tool spec, which prescribes paths +
  view/create/str_replace/insert/delete/rename. Same shape lets us swap
  in Anthropic's first-party memory tool later if we ever migrate off
  pydantic_ai's tool layer.

Why per-tenant (`business_id` scoped):
- One agent ↔ one tenant business. Memory crosses partners and customers
  but never crosses tenants. The harness binds `business_id` from
  `RunContext.deps`; the agent never names it.

Path validation is strict: every operation rejects paths that don't
start with `/memories/`, contain `..`, or are URL-encoded escapes. The
DB layer is the last line of defense; the tool layer must validate too
because malformed paths reach storage as opaque strings otherwise.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from backend.db.connection import get_db


MEMORY_ROOT = "/memories"


class InvalidMemoryPath(ValueError):
    """Raised when a path is outside /memories or contains traversal patterns."""


class MemoryFile(BaseModel):
    business_id: UUID
    path: str
    content: str
    created_at: datetime
    updated_at: datetime


class MemoryListing(BaseModel):
    """One entry in a directory listing: either a file or a synthetic dir."""

    path: str
    is_directory: bool
    size_bytes: int = 0  # 0 for directories — we don't recurse to compute size


# ---------------------------------------------------------------------------
# Path validation. Strict by default — call this at the start of every
# public function. The tool layer is expected to validate too, but defense
# in depth is cheap when the consequence is reading another tenant's memory.
# ---------------------------------------------------------------------------


def _validate_path(path: str, *, allow_root: bool = False) -> str:
    """Normalize + validate a memory path. Returns the canonical form.

    - Must start with `/memories` (and `/memories/<something>` unless
      `allow_root=True`, which only the directory-list operation needs).
    - No `..` segments — even URL-encoded ones.
    - No leading/trailing whitespace; collapsed slashes.
    """
    if not isinstance(path, str) or not path:
        raise InvalidMemoryPath("path must be a non-empty string")

    # Reject URL-encoded traversal up front. We don't want to decode and
    # re-validate; just refuse anything that looks suspicious.
    lowered = path.lower()
    if "%2e%2e" in lowered or "%2f" in lowered or "%5c" in lowered:
        raise InvalidMemoryPath(f"url-encoded escape in path: {path!r}")

    # Strip any backslashes — Windows-style separators have no meaning here
    # and are a common traversal vector.
    if "\\" in path:
        raise InvalidMemoryPath(f"backslash in path: {path!r}")

    # Collapse double-slashes and reject `..` segments.
    parts = [p for p in path.split("/") if p != ""]
    if any(p == ".." for p in parts):
        raise InvalidMemoryPath(f"path traversal segment in: {path!r}")

    canonical = "/" + "/".join(parts)
    if canonical == "/memories":
        if not allow_root:
            raise InvalidMemoryPath(
                "cannot operate on /memories itself; use a child path"
            )
        return canonical
    if not canonical.startswith("/memories/"):
        raise InvalidMemoryPath(
            f"path must be under /memories/: {path!r} → {canonical!r}"
        )
    return canonical


# ---------------------------------------------------------------------------
# CRUD.
# ---------------------------------------------------------------------------


async def read_file(business_id: UUID, path: str) -> MemoryFile | None:
    canonical = _validate_path(path)
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT business_id, path, content, created_at, updated_at
            FROM tenant_memory
            WHERE business_id = $1 AND path = $2
            """,
            business_id,
            canonical,
        )
    return MemoryFile(**dict(row)) if row else None


async def list_directory(
    business_id: UUID, dir_path: str
) -> list[MemoryListing]:
    """List immediate children (files + synthetic directories) of `dir_path`.

    `dir_path` may be `/memories` (root) or any subdirectory like
    `/memories/vendors`. Only direct children — for a deep listing the
    agent issues another `list_directory` on a subdirectory.
    """
    canonical = _validate_path(dir_path, allow_root=True)
    prefix = canonical.rstrip("/") + "/"
    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT path, length(content) AS size_bytes
            FROM tenant_memory
            WHERE business_id = $1 AND path LIKE $2
            ORDER BY path
            """,
            business_id,
            prefix + "%",
        )

    seen_dirs: set[str] = set()
    listings: list[MemoryListing] = []
    for row in rows:
        rel = row["path"][len(prefix):]
        if "/" in rel:
            # Indirect descendant — synthesize a directory entry for the
            # immediate-child segment. Skip duplicates.
            child = rel.split("/", 1)[0]
            child_path = prefix + child
            if child_path not in seen_dirs:
                seen_dirs.add(child_path)
                listings.append(
                    MemoryListing(path=child_path, is_directory=True)
                )
        else:
            listings.append(
                MemoryListing(
                    path=row["path"],
                    is_directory=False,
                    size_bytes=row["size_bytes"],
                )
            )
    return listings


async def create_file(business_id: UUID, path: str, content: str) -> MemoryFile:
    """Insert a new file. Raises FileExistsError if the path already exists."""
    canonical = _validate_path(path)
    pool = await get_db()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO tenant_memory (business_id, path, content)
                VALUES ($1, $2, $3)
                RETURNING business_id, path, content, created_at, updated_at
                """,
                business_id,
                canonical,
                content,
            )
        except Exception as exc:
            # asyncpg raises UniqueViolationError on PK conflict; reflect
            # the higher-level intent.
            if "tenant_memory_pkey" in str(exc) or "duplicate key" in str(exc).lower():
                raise FileExistsError(
                    f"file already exists: {canonical}"
                ) from exc
            raise
    return MemoryFile(**dict(row))


async def update_file(business_id: UUID, path: str, content: str) -> MemoryFile:
    """Overwrite an existing file's content. Raises FileNotFoundError if missing."""
    canonical = _validate_path(path)
    pool = await get_db()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE tenant_memory
            SET content = $3, updated_at = NOW()
            WHERE business_id = $1 AND path = $2
            RETURNING business_id, path, content, created_at, updated_at
            """,
            business_id,
            canonical,
            content,
        )
    if row is None:
        raise FileNotFoundError(f"file does not exist: {canonical}")
    return MemoryFile(**dict(row))


async def delete_path(business_id: UUID, path: str) -> int:
    """Delete a file or every file under a directory prefix.

    Returns the number of rows removed. 0 means nothing matched (caller
    decides whether that's a 'not found' error or silent no-op).
    """
    canonical = _validate_path(path, allow_root=True)
    pool = await get_db()
    async with pool.acquire() as conn:
        # Single-file delete first; if the path matches no row we treat
        # `path` as a directory prefix and recurse.
        status = await conn.execute(
            "DELETE FROM tenant_memory WHERE business_id = $1 AND path = $2",
            business_id,
            canonical,
        )
        deleted = _rowcount(status)
        if deleted > 0:
            return deleted
        # Directory delete: remove everything under the prefix.
        prefix = canonical.rstrip("/") + "/"
        status = await conn.execute(
            """
            DELETE FROM tenant_memory
            WHERE business_id = $1 AND path LIKE $2
            """,
            business_id,
            prefix + "%",
        )
        return _rowcount(status)


async def rename(
    business_id: UUID, old_path: str, new_path: str
) -> MemoryFile:
    """Rename / move a single file. Raises if old missing or new exists."""
    canonical_old = _validate_path(old_path)
    canonical_new = _validate_path(new_path)
    if canonical_old == canonical_new:
        existing = await read_file(business_id, canonical_old)
        if existing is None:
            raise FileNotFoundError(f"file does not exist: {canonical_old}")
        return existing

    pool = await get_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT 1 FROM tenant_memory WHERE business_id = $1 AND path = $2",
                business_id,
                canonical_new,
            )
            if existing is not None:
                raise FileExistsError(
                    f"destination already exists: {canonical_new}"
                )
            row = await conn.fetchrow(
                """
                UPDATE tenant_memory
                SET path = $3, updated_at = NOW()
                WHERE business_id = $1 AND path = $2
                RETURNING business_id, path, content, created_at, updated_at
                """,
                business_id,
                canonical_old,
                canonical_new,
            )
    if row is None:
        raise FileNotFoundError(f"file does not exist: {canonical_old}")
    return MemoryFile(**dict(row))


def _rowcount(status: str) -> int:
    # asyncpg returns command tags like "DELETE 3".
    return int(status.rsplit(" ", 1)[-1])
