import asyncpg
import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from config.settings import settings

# Global connection pool
_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Initialize connection with custom type codecs for JSONB."""
    # Set JSONB codec to automatically parse JSON to Python objects
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_db_pool() -> None:
    """Initialize the database connection pool."""
    global _pool

    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        max_queries=settings.db_pool_max_queries,
        max_inactive_connection_lifetime=settings.db_pool_max_inactive_connection_lifetime,
        command_timeout=settings.db_command_timeout,
        init=_init_connection,
    )


async def close_db_pool() -> None:
    """Close the database connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Get the database connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool


# Alias for compatibility
async def get_db_pool() -> asyncpg.Pool:
    """Get the database connection pool (async alias).

    Note: This is an async version for consistency with initialization pattern.
    If pool is not initialized, it will initialize it first.
    """
    global _pool
    if _pool is None:
        await init_db_pool()
    return _pool


@asynccontextmanager
async def get_db_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Context manager to acquire a connection from the pool."""
    pool = get_pool()
    async with pool.acquire() as connection:
        yield connection


@asynccontextmanager
async def get_db_transaction() -> AsyncGenerator[asyncpg.Connection, None]:
    """Context manager for a database transaction."""
    pool = get_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            yield connection
