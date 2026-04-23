"""Idempotent seed for the smoke harness.

The smoke CLI uses deterministic UUIDs for the business and customer so a
session can be re-run cheaply. Without rows in `businesses` and `users`,
`channel_identities` and `outbound_tasks` inserts blow up with FK violations
on the very first turn — this module ensures the parents exist.

Safe to call on every CLI start: every INSERT uses ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

from uuid import UUID

from backend.db.connection import get_db


_BUSINESS_NAME = "Smoke Harness Co."
_CUSTOMER_PHONE_PREFIX = "smoke-"  # phone_number is UNIQUE NOT NULL on users


async def ensure_smoke_data(business_id: str, customer_id: str) -> None:
    """Insert the business + customer rows the smoke harness needs.

    Both are upserted by id with ON CONFLICT DO NOTHING — re-running with the
    same UUIDs is a no-op, and re-running with different UUIDs adds new rows
    without disturbing the old ones.
    """
    biz_uuid = UUID(business_id)
    cust_uuid = UUID(customer_id)
    # `users.phone_number` is UNIQUE NOT NULL; deriving from the UUID keeps
    # multiple smoke customers distinct without needing a real phone number.
    phone = f"{_CUSTOMER_PHONE_PREFIX}{customer_id[:8]}"

    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO businesses (id, name)
            VALUES ($1, $2)
            ON CONFLICT (id) DO NOTHING
            """,
            biz_uuid,
            _BUSINESS_NAME,
        )
        await conn.execute(
            """
            INSERT INTO users (id, phone_number, full_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO NOTHING
            """,
            cust_uuid,
            phone,
            "Smoke Customer",
        )
