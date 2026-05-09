"""Database startup population: run migrations, then seed the
WhatsApp-bound tenant from env if configured.

The frontend-fixture seeding (predefined users / businesses / products)
that lived here previously was tied to the now-retired frontend and has
been removed. Real tenants come in through `seed_whatsapp_business_from_env`.
"""

import logging
from pathlib import Path

from backend.db.connection import get_db
from backend.db.seed_whatsapp import seed_whatsapp_business_from_env

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


async def _run_migrations(pool) -> None:
    """Execute migration files in order, skipping already-applied ones."""
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    async with pool.acquire() as conn:
        # Bootstrap the tracking table before we can check it
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        for path in migration_files:
            version = int(path.stem.split("_")[0])
            already_applied = await conn.fetchval(
                "SELECT 1 FROM schema_migrations WHERE version = $1", version
            )
            if already_applied:
                logging.info(f"Skipping already-applied migration: {path.name}")
                continue
            sql = path.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
                    version, path.name,
                )
            logging.info(f"Applied migration: {path.name}")


async def populate_db_on_startup() -> None:
    """Run migrations and seed the WhatsApp tenant. Idempotent on re-run."""
    pool = await get_db()  # Let exception propagate — caller handles retries
    try:
        await _run_migrations(pool)
        await seed_whatsapp_business_from_env(pool)
        logging.info("Database populated successfully")
    except Exception as e:
        logging.error(f"populate_db_on_startup failed: {e}")
        raise
