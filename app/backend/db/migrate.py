"""
Database migration runner with versioning support.

Usage:
    uv run app/backend/db/migrate.py          # Run all pending migrations
    uv run app/backend/db/migrate.py --rollback <version>  # Rollback to specific version
    uv run app/backend/db/migrate.py --status  # Show migration status
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import List, Tuple

import asyncpg


class MigrationRunner:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.migrations_dir = Path(__file__).parent / "migrations"
        self.conn: asyncpg.Connection | None = None

    async def connect(self):
        """Establish database connection."""
        self.conn = await asyncpg.connect(dsn=self.dsn)

    async def close(self):
        """Close database connection."""
        if self.conn:
            await self.conn.close()

    async def ensure_migrations_table(self):
        """Create schema_migrations table if it doesn't exist."""
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

    async def get_applied_migrations(self) -> List[int]:
        """Get list of applied migration versions."""
        rows = await self.conn.fetch(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        return [row["version"] for row in rows]

    def get_available_migrations(self) -> List[Tuple[int, str, Path]]:
        """
        Get list of available migration files.
        Returns: List of (version, name, filepath) tuples
        """
        migrations = []
        for filepath in sorted(self.migrations_dir.glob("*.sql")):
            # Parse filename: 001_initial_schema.sql -> (1, "initial_schema")
            filename = filepath.stem
            try:
                version_str, name = filename.split("_", 1)
                version = int(version_str)
                migrations.append((version, name, filepath))
            except ValueError:
                print(f"⚠️  Skipping invalid migration filename: {filepath.name}")
                continue

        return sorted(migrations, key=lambda x: x[0])

    async def apply_migration(self, version: int, name: str, filepath: Path):
        """Apply a single migration."""
        print(f"📦 Applying migration {version}: {name}")

        # Read migration SQL
        sql = filepath.read_text()

        async with self.conn.transaction():
            # Execute migration
            await self.conn.execute(sql)

            # Record migration (skip if it's creating the migrations table itself)
            if "schema_migrations" not in sql or version > 0:
                await self.conn.execute(
                    """
                    INSERT INTO schema_migrations (version, name)
                    VALUES ($1, $2)
                    ON CONFLICT (version) DO NOTHING
                    """,
                    version,
                    name,
                )

        print(f"✓ Migration {version} applied successfully")

    async def run_migrations(self):
        """Run all pending migrations."""
        await self.ensure_migrations_table()

        applied = await self.get_applied_migrations()
        available = self.get_available_migrations()

        if not available:
            print("⚠️  No migration files found in", self.migrations_dir)
            return

        pending = [(v, n, p) for v, n, p in available if v not in applied]

        if not pending:
            print("✓ All migrations are up to date")
            return

        print(f"\n📋 Found {len(pending)} pending migration(s):\n")
        for version, name, _ in pending:
            print(f"   • {version:03d}_{name}")
        print()

        for version, name, filepath in pending:
            try:
                await self.apply_migration(version, name, filepath)
            except Exception as e:
                print(f"\n✗ Migration {version} failed: {e}")
                raise

        print("\n✓ All migrations completed successfully")

    async def show_status(self):
        """Show migration status."""
        await self.ensure_migrations_table()

        applied = await self.get_applied_migrations()
        available = self.get_available_migrations()

        print("\n" + "=" * 60)
        print("MIGRATION STATUS")
        print("=" * 60 + "\n")

        if not available:
            print("⚠️  No migration files found")
            return

        for version, name, _ in available:
            status = "✓ Applied" if version in applied else "○ Pending"
            applied_at = ""

            if version in applied:
                result = await self.conn.fetchrow(
                    "SELECT applied_at FROM schema_migrations WHERE version = $1",
                    version,
                )
                if result:
                    applied_at = (
                        f" ({result['applied_at'].strftime('%Y-%m-%d %H:%M:%S')})"
                    )

            print(f"{status:12} {version:03d}_{name}{applied_at}")

        print()

    async def rollback(self, target_version: int):
        """
        Rollback migrations to a specific version.
        Note: This requires corresponding _down.sql files.
        """
        await self.ensure_migrations_table()

        applied = await self.get_applied_migrations()
        to_rollback = [v for v in applied if v > target_version]

        if not to_rollback:
            print(f"✓ Already at version {target_version}")
            return

        print(f"\n⚠️  WARNING: Rolling back {len(to_rollback)} migration(s)")
        print("This will execute DOWN migrations if available.\n")

        for version in sorted(to_rollback, reverse=True):
            down_file = self.migrations_dir / f"{version:03d}_*_down.sql"
            down_files = list(self.migrations_dir.glob(f"{version:03d}_*_down.sql"))

            if not down_files:
                print(f"✗ No rollback file found for migration {version}")
                print(f"  Expected: {version:03d}_<name>_down.sql")
                return

            down_path = down_files[0]
            print(f"⏪ Rolling back migration {version}")

            sql = down_path.read_text()

            async with self.conn.transaction():
                await self.conn.execute(sql)
                await self.conn.execute(
                    "DELETE FROM schema_migrations WHERE version = $1", version
                )

            print(f"✓ Migration {version} rolled back")

        print(f"\n✓ Rollback to version {target_version} completed")


async def main():
    """Main entry point."""
    # Get DATABASE_URL from environment
    from dotenv import load_dotenv

    load_dotenv()
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("✗ DATABASE_URL environment variable not set")
        sys.exit(1)

    runner = MigrationRunner(dsn)

    try:
        await runner.connect()

        # Parse command line arguments
        if len(sys.argv) > 1:
            if sys.argv[1] == "--status":
                await runner.show_status()
            elif sys.argv[1] == "--rollback" and len(sys.argv) > 2:
                target = int(sys.argv[2])
                await runner.rollback(target)
            else:
                print(__doc__)
        else:
            # Default: run migrations
            await runner.run_migrations()

    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
