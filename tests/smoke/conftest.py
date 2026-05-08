"""Path setup + env bootstrap for smoke tests.

The backend package lives under app/, but smoke tests live at the repo root.
Inject app/ onto sys.path and pre-load app/.env so smoke tests pick up the
real REDIS_URL / DATABASE_URL the user's docker-compose is using.

Also exposes a session-scoped `smoke_tenancy` fixture used by the new
log-flow + stub-model harnesses. Sharing one fixture across both modules
avoids a second module trying to re-init the asyncpg pool (which lives
in a process-global) on a different event loop, which races teardown.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest_asyncio

_APP_DIR = Path(__file__).resolve().parents[2] / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# Load app/.env BEFORE backend.* imports so REDIS / DATABASE config is in env.
try:
    from dotenv import load_dotenv

    load_dotenv(_APP_DIR / ".env")
except ImportError:
    pass


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def smoke_tenancy():
    """Apply migrations, seed a business + a customer + a vendor contact.

    Skipped if Postgres is unreachable so the suite is friendly when run
    outside the smoke environment.

    Returns: dict with business_id / alice_id / bob_id / contact_id.
    Cleans up at session end.
    """
    import pytest

    try:
        from backend.db.connection import get_db, init_db
        from backend.db.populate import _run_migrations
    except Exception as exc:
        pytest.skip(f"app imports unavailable: {exc}")
    try:
        await init_db()
        pool = await get_db()
    except Exception as exc:
        pytest.skip(f"postgres not reachable: {exc}")
    try:
        await _run_migrations(pool)
    except Exception as exc:
        pytest.skip(f"migrations failed: {exc}")

    biz_id = uuid4()
    alice_id = uuid4()
    bob_id = uuid4()
    contact_id = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO businesses (id, name, business_type) VALUES ($1, 'Smoke Biz', 'fashion')",
            biz_id,
        )
        await conn.execute(
            "INSERT INTO users (id, full_name, phone_number) VALUES ($1, 'Alice', $2)",
            alice_id,
            f"+234{uuid4().hex[:10]}",
        )
        await conn.execute(
            "INSERT INTO users (id, full_name, phone_number) VALUES ($1, 'Bob', $2)",
            bob_id,
            f"+234{uuid4().hex[:10]}",
        )
        await conn.execute(
            "INSERT INTO contacts (id, business_id, name, role, channel, channel_user_id) "
            "VALUES ($1, $2, 'Vendor X', 'vendor', 'console', $3)",
            contact_id,
            biz_id,
            f"vendor-{uuid4().hex[:6]}",
        )

    yield {
        "business_id": biz_id,
        "alice_id": alice_id,
        "bob_id": bob_id,
        "contact_id": contact_id,
    }

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM outbound_tasks WHERE business_id = $1", biz_id)
        await conn.execute("DELETE FROM contacts WHERE id = $1", contact_id)
        await conn.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", [alice_id, bob_id])
        await conn.execute("DELETE FROM businesses WHERE id = $1", biz_id)
