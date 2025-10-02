"""Run database schema migrations."""

import asyncio
import sys
from pathlib import Path

import asyncpg

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings


async def run_migration(conn: asyncpg.Connection, file_path: Path) -> None:
    """Run a single migration file."""
    sql = file_path.read_text()
    await conn.execute(sql)


async def run_all_migrations() -> None:
    """Run all migration files in order."""
    schema_dir = Path(__file__).parent
    migration_files = sorted(schema_dir.glob("*.sql"))

    if not migration_files:
        print("No migration files found.")
        return

    try:
        # Connect to database
        conn = await asyncpg.connect(dsn=settings.database_url)

        print("Running database migrations...")
        for file_path in migration_files:
            print(f"  Applying {file_path.name}...")
            await run_migration(conn, file_path)

        print("✓ All migrations completed successfully")

        # Close connection
        await conn.close()

    except Exception as e:
        print(f"✗ Migration failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all_migrations())
