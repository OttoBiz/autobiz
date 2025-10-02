"""Unit tests for db/schema/run_migrations.py"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import asyncpg

from db.schema.run_migrations import run_migration, run_all_migrations


@pytest.mark.asyncio
async def test_run_migration_executes_sql():
    """Test that run_migration reads and executes SQL from file."""
    mock_conn = AsyncMock(spec=asyncpg.Connection)
    mock_file = Path("/fake/path/001_test.sql")
    sql_content = "CREATE TABLE test (id INTEGER);"

    with patch.object(Path, "read_text", return_value=sql_content):
        await run_migration(mock_conn, mock_file)

    mock_conn.execute.assert_called_once_with(sql_content)


@pytest.mark.asyncio
async def test_run_all_migrations_with_no_files(capsys):
    """Test that run_all_migrations handles empty directory gracefully."""
    with patch("db.schema.run_migrations.Path") as mock_path_class:
        mock_schema_dir = MagicMock()
        mock_schema_dir.glob.return_value = []
        mock_path_class.return_value.parent = mock_schema_dir

        await run_all_migrations()

    captured = capsys.readouterr()
    assert "No migration files found." in captured.out


@pytest.mark.asyncio
async def test_run_all_migrations_executes_files_in_order():
    """Test that run_all_migrations runs SQL files in sorted order."""
    mock_conn = AsyncMock(spec=asyncpg.Connection)

    # Create mock file paths with proper comparison support
    file1 = MagicMock(spec=Path)
    file1.name = "000_init.sql"
    file1.read_text.return_value = "CREATE TABLE schema_versions;"
    file1.__lt__ = lambda self, other: self.name < other.name
    file1.__gt__ = lambda self, other: self.name > other.name

    file2 = MagicMock(spec=Path)
    file2.name = "001_users.sql"
    file2.read_text.return_value = "CREATE TABLE users;"
    file2.__lt__ = lambda self, other: self.name < other.name
    file2.__gt__ = lambda self, other: self.name > other.name

    file3 = MagicMock(spec=Path)
    file3.name = "002_businesses.sql"
    file3.read_text.return_value = "CREATE TABLE businesses;"
    file3.__lt__ = lambda self, other: self.name < other.name
    file3.__gt__ = lambda self, other: self.name > other.name

    # Provide files in unsorted order to test sorting
    migration_files = [file2, file3, file1]

    with (
        patch("db.schema.run_migrations.Path") as mock_path_class,
        patch("db.schema.run_migrations.asyncpg.connect", new_callable=AsyncMock) as mock_connect,
        patch("db.schema.run_migrations.settings") as mock_settings,
    ):
        mock_settings.database_url = "postgresql://test"
        mock_connect.return_value = mock_conn
        mock_conn.close = AsyncMock()

        # Mock the schema directory and glob
        mock_schema_dir = MagicMock()
        mock_schema_dir.glob.return_value = migration_files
        mock_path_instance = MagicMock()
        mock_path_instance.parent = mock_schema_dir
        mock_path_class.return_value = mock_path_instance

        await run_all_migrations()

    # Verify connection was established
    mock_connect.assert_called_once_with(dsn="postgresql://test")

    # Verify all migrations were executed in order
    assert mock_conn.execute.call_count == 3
    calls = mock_conn.execute.call_args_list
    assert calls[0][0][0] == "CREATE TABLE schema_versions;"
    assert calls[1][0][0] == "CREATE TABLE users;"
    assert calls[2][0][0] == "CREATE TABLE businesses;"

    # Verify connection was closed
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_run_all_migrations_handles_connection_error(capsys):
    """Test that run_all_migrations handles connection errors gracefully."""
    with (
        patch("db.schema.run_migrations.asyncpg.connect", new_callable=AsyncMock) as mock_connect,
        patch("db.schema.run_migrations.settings") as mock_settings,
        pytest.raises(SystemExit) as exc_info,
    ):
        mock_settings.database_url = "postgresql://test"
        mock_connect.side_effect = asyncpg.PostgresConnectionError("Connection failed")

        await run_all_migrations()

    # Verify exit code is 1
    assert exc_info.value.code == 1

    # Verify error message was printed
    captured = capsys.readouterr()
    assert "Migration failed" in captured.err
    assert "Connection failed" in captured.err


@pytest.mark.asyncio
async def test_run_all_migrations_handles_execution_error(capsys):
    """Test that run_all_migrations handles SQL execution errors."""
    mock_conn = AsyncMock(spec=asyncpg.Connection)
    mock_conn.execute.side_effect = asyncpg.PostgresSyntaxError("Syntax error")

    file1 = MagicMock(spec=Path)
    file1.name = "001_bad.sql"
    file1.read_text.return_value = "INVALID SQL;"

    with (
        patch("db.schema.run_migrations.Path") as mock_path_class,
        patch("db.schema.run_migrations.asyncpg.connect", new_callable=AsyncMock) as mock_connect,
        patch("db.schema.run_migrations.settings") as mock_settings,
        pytest.raises(SystemExit) as exc_info,
    ):
        mock_settings.database_url = "postgresql://test"
        mock_connect.return_value = mock_conn

        mock_schema_dir = MagicMock()
        mock_schema_dir.glob.return_value = [file1]
        mock_path_instance = MagicMock()
        mock_path_instance.parent = mock_schema_dir
        mock_path_class.return_value = mock_path_instance

        await run_all_migrations()

    # Verify exit code is 1
    assert exc_info.value.code == 1

    # Verify error message was printed
    captured = capsys.readouterr()
    assert "Migration failed" in captured.err
    assert "Syntax error" in captured.err


@pytest.mark.asyncio
async def test_run_all_migrations_prints_progress(capsys):
    """Test that run_all_migrations prints progress messages."""
    mock_conn = AsyncMock(spec=asyncpg.Connection)

    file1 = MagicMock(spec=Path)
    file1.name = "000_init.sql"
    file1.read_text.return_value = "CREATE TABLE test;"

    with (
        patch("db.schema.run_migrations.Path") as mock_path_class,
        patch("db.schema.run_migrations.asyncpg.connect", new_callable=AsyncMock) as mock_connect,
        patch("db.schema.run_migrations.settings") as mock_settings,
    ):
        mock_settings.database_url = "postgresql://test"
        mock_connect.return_value = mock_conn
        mock_conn.close = AsyncMock()

        mock_schema_dir = MagicMock()
        mock_schema_dir.glob.return_value = [file1]
        mock_path_instance = MagicMock()
        mock_path_instance.parent = mock_schema_dir
        mock_path_class.return_value = mock_path_instance

        await run_all_migrations()

    captured = capsys.readouterr()
    assert "Running database migrations..." in captured.out
    assert "Applying 000_init.sql..." in captured.out
    assert "✓ All migrations completed successfully" in captured.out
