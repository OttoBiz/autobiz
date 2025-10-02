"""Unit tests for db/connection.py using pytest-asyncio"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncpg

from db.connection import (
    init_db_pool,
    close_db_pool,
    get_pool,
    get_db_connection,
    get_db_transaction,
)


@pytest.fixture
def mock_asyncpg_pool():
    """Fixture that returns a properly configured mock pool."""
    pool = MagicMock(spec=asyncpg.Pool)
    pool.close = AsyncMock()

    # Mock the acquire context manager
    mock_conn = AsyncMock(spec=asyncpg.Connection)
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = mock_acquire

    return pool


@pytest.fixture
def reset_pool():
    """Fixture to reset the global pool state before and after each test."""
    import db.connection

    original_pool = db.connection._pool
    db.connection._pool = None
    yield
    db.connection._pool = original_pool


@pytest.mark.asyncio
async def test_init_db_pool_creates_pool(reset_pool):
    """Test that init_db_pool creates a connection pool."""
    with patch("db.connection.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
        mock_pool = MagicMock(spec=asyncpg.Pool)
        mock_create.return_value = mock_pool

        await init_db_pool()

        # Verify create_pool was called
        mock_create.assert_called_once()

        # Verify pool is set
        pool = get_pool()
        assert pool is mock_pool


@pytest.mark.asyncio
async def test_init_db_pool_uses_settings(reset_pool):
    """Test that init_db_pool passes correct settings to create_pool."""
    with patch("db.connection.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
        mock_pool = MagicMock(spec=asyncpg.Pool)
        mock_create.return_value = mock_pool

        await init_db_pool()

        # Check that settings were passed correctly
        call_kwargs = mock_create.call_args.kwargs
        assert "dsn" in call_kwargs
        assert call_kwargs["min_size"] == 10
        assert call_kwargs["max_size"] == 20
        assert call_kwargs["max_queries"] == 50000
        assert call_kwargs["command_timeout"] == 60.0


@pytest.mark.asyncio
async def test_close_db_pool_closes_successfully(reset_pool):
    """Test that close_db_pool closes the pool and sets it to None."""
    import db.connection

    mock_pool = MagicMock(spec=asyncpg.Pool)
    mock_pool.close = AsyncMock()
    db.connection._pool = mock_pool

    await close_db_pool()

    # Verify close was called
    mock_pool.close.assert_called_once()

    # Verify pool is None
    assert db.connection._pool is None


@pytest.mark.asyncio
async def test_close_db_pool_when_not_initialized(reset_pool):
    """Test that close_db_pool handles None pool gracefully."""
    import db.connection

    db.connection._pool = None

    # Should not raise an error
    await close_db_pool()

    assert db.connection._pool is None


def test_get_pool_raises_when_not_initialized(reset_pool):
    """Test that get_pool raises RuntimeError when pool is not initialized."""
    with pytest.raises(RuntimeError, match="Database pool not initialized"):
        get_pool()


@pytest.mark.asyncio
async def test_get_pool_returns_initialized_pool(reset_pool):
    """Test that get_pool returns the initialized pool."""
    import db.connection

    mock_pool = MagicMock(spec=asyncpg.Pool)
    db.connection._pool = mock_pool

    pool = get_pool()
    assert pool is mock_pool


@pytest.mark.asyncio
async def test_get_db_connection_acquires_and_yields_connection(reset_pool, mock_asyncpg_pool):
    """Test that get_db_connection acquires a connection from the pool."""
    import db.connection

    db.connection._pool = mock_asyncpg_pool

    async with get_db_connection() as conn:
        assert conn is not None
        assert isinstance(conn, AsyncMock)

    # Verify acquire was called
    mock_asyncpg_pool.acquire.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_connection_releases_on_exit(reset_pool, mock_asyncpg_pool):
    """Test that connection is properly released back to the pool."""
    import db.connection

    db.connection._pool = mock_asyncpg_pool

    async with get_db_connection() as conn:
        pass

    # Verify __aexit__ was called (connection released)
    mock_acquire = mock_asyncpg_pool.acquire.return_value
    mock_acquire.__aexit__.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_connection_raises_when_pool_not_initialized(reset_pool):
    """Test that get_db_connection raises error when pool not initialized."""
    with pytest.raises(RuntimeError, match="Database pool not initialized"):
        async with get_db_connection():
            pass


@pytest.mark.asyncio
async def test_get_db_transaction_starts_transaction(reset_pool, mock_asyncpg_pool):
    """Test that get_db_transaction starts a transaction."""
    import db.connection

    db.connection._pool = mock_asyncpg_pool

    # Get the mock connection from the pool
    mock_conn = await mock_asyncpg_pool.acquire().__aenter__()

    # Setup transaction mock
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=None)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction.return_value = mock_transaction

    async with get_db_transaction() as conn:
        assert conn is mock_conn

    # Verify transaction was started
    mock_conn.transaction.assert_called_once()
    mock_transaction.__aenter__.assert_called_once()
    mock_transaction.__aexit__.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_transaction_raises_when_pool_not_initialized(reset_pool):
    """Test that get_db_transaction raises error when pool not initialized."""
    with pytest.raises(RuntimeError, match="Database pool not initialized"):
        async with get_db_transaction():
            pass


@pytest.mark.asyncio
async def test_connection_context_manager_cleanup_on_error(reset_pool, mock_asyncpg_pool):
    """Test that connection is released even when an error occurs."""
    import db.connection

    db.connection._pool = mock_asyncpg_pool

    with pytest.raises(ValueError):
        async with get_db_connection() as conn:
            raise ValueError("Test error")

    # Verify connection was still released
    mock_acquire = mock_asyncpg_pool.acquire.return_value
    mock_acquire.__aexit__.assert_called_once()


@pytest.mark.asyncio
async def test_transaction_context_manager_cleanup_on_error(reset_pool, mock_asyncpg_pool):
    """Test that transaction is properly handled even when an error occurs."""
    import db.connection

    db.connection._pool = mock_asyncpg_pool

    # Get the mock connection from the pool
    mock_conn = await mock_asyncpg_pool.acquire().__aenter__()

    # Setup transaction mock
    mock_transaction = MagicMock()
    mock_transaction.__aenter__ = AsyncMock(return_value=None)
    mock_transaction.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction.return_value = mock_transaction

    with pytest.raises(ValueError):
        async with get_db_transaction() as conn:
            raise ValueError("Test error")

    # Verify transaction cleanup was called (rollback)
    mock_transaction.__aexit__.assert_called_once()


@pytest.mark.asyncio
async def test_multiple_sequential_connections(reset_pool, mock_asyncpg_pool):
    """Test that multiple connections can be acquired sequentially."""
    import db.connection

    db.connection._pool = mock_asyncpg_pool

    # First connection
    async with get_db_connection() as conn1:
        assert conn1 is not None

    # Second connection
    async with get_db_connection() as conn2:
        assert conn2 is not None

    # Verify acquire was called twice
    assert mock_asyncpg_pool.acquire.call_count == 2


@pytest.mark.asyncio
async def test_pool_lifecycle(reset_pool):
    """Test full lifecycle: init -> use -> close -> reinit."""
    with patch("db.connection.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
        # First initialization
        mock_pool1 = MagicMock(spec=asyncpg.Pool)
        mock_pool1.close = AsyncMock()
        mock_create.return_value = mock_pool1

        await init_db_pool()
        pool = get_pool()
        assert pool is mock_pool1

        await close_db_pool()

        # Should raise after close
        with pytest.raises(RuntimeError):
            get_pool()

        # Re-initialize
        mock_pool2 = MagicMock(spec=asyncpg.Pool)
        mock_pool2.close = AsyncMock()
        mock_create.return_value = mock_pool2

        await init_db_pool()
        pool = get_pool()
        assert pool is mock_pool2

        await close_db_pool()

        # Verify both pools were closed
        mock_pool1.close.assert_called_once()
        mock_pool2.close.assert_called_once()
