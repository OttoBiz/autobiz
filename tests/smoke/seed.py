"""Idempotent seed for the smoke harness.

The smoke CLI uses deterministic UUIDs for the business and customer so a
session can be re-run cheaply. Without rows in `businesses` and `users`,
`channel_identities` and `outbound_tasks` inserts blow up with FK violations
on the very first turn — this module ensures the parents exist. It also
pre-populates a small product catalog and bank details so the product agent
has something concrete to answer with.

Safe to call on every CLI start: every INSERT uses ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from backend.db.cache_utils import redis_conn
from backend.db.connection import get_db


_BUSINESS_NAME = "Smoke Harness Co."
_CUSTOMER_PHONE_PREFIX = "smoke-"  # phone_number is UNIQUE NOT NULL on users

# Demo bank details so get_business_payment_info returns configured=True.
_BANK_NAME = "Smoke Bank"
_BANK_ACCOUNT_NUMBER = "0123456789"
_BANK_ACCOUNT_NAME = "Smoke Harness Co. Ltd"

# A handful of products covering common smoke flows: in-stock, low-stock,
# distinct categories. SKUs are stable so re-seeding is a no-op via the
# (business_id, sku) idempotency key below.
_DEMO_PRODUCTS = [
    {
        "name": "BMX Bicycle",
        "description": "20-inch freestyle BMX with reinforced frame.",
        "price": Decimal("85000.00"),
        "stock_quantity": 7,
        "sku": "BMX-001",
        "category": "bicycles",
    },
    {
        "name": "Mountain Bike",
        "description": "26-inch hardtail mountain bike, 21-speed.",
        "price": Decimal("145000.00"),
        "stock_quantity": 3,
        "sku": "MTB-001",
        "category": "bicycles",
    },
    {
        "name": "Bike Helmet",
        "description": "Adjustable helmet with vented shell.",
        "price": Decimal("12500.00"),
        "stock_quantity": 25,
        "sku": "ACC-001",
        "category": "accessories",
    },
]


async def reset_smoke_state(business_id: str, customer_id: str) -> None:
    """Wipe per-customer state so a fresh CLI launch feels fresh.

    Clears every store keyed on (business_id, customer_id) for the smoke
    pair: postgres-side outbound tasks, channel identities, orders and
    transactions; redis-side chat history, inbox, lock, cursor, outbound
    chat history. Idempotent — safe even when nothing exists yet.

    Does NOT touch the business or customer rows themselves; that's
    `ensure_smoke_data`'s job.
    """
    biz_uuid = UUID(business_id)
    cust_uuid = UUID(customer_id)

    pool = await get_db()
    async with pool.acquire() as conn:
        # Outbound chat histories live in Redis keyed by task_key, so grab
        # the keys before deleting the ledger rows.
        task_keys = [
            row["task_key"]
            for row in await conn.fetch(
                "SELECT task_key FROM outbound_tasks WHERE business_id=$1 AND customer_id=$2",
                biz_uuid,
                cust_uuid,
            )
        ]
        await conn.execute(
            "DELETE FROM outbound_tasks WHERE business_id=$1 AND customer_id=$2",
            biz_uuid,
            cust_uuid,
        )
        await conn.execute(
            "DELETE FROM transactions WHERE business_id=$1 AND user_id=$2",
            biz_uuid,
            cust_uuid,
        )
        await conn.execute(
            "DELETE FROM orders WHERE business_id=$1 AND user_id=$2",
            biz_uuid,
            cust_uuid,
        )
        await conn.execute(
            "DELETE FROM channel_identities WHERE business_id=$1 AND customer_id=$2",
            biz_uuid,
            cust_uuid,
        )

    client = redis_conn._client
    keys = [
        f"chat:{business_id}:{customer_id}",
        f"inbox:{business_id}:{customer_id}",
        f"lock:inbox:{business_id}:{customer_id}",
        f"central_agent_cursor:{business_id}:{customer_id}",
        f"{customer_id}:{business_id}",  # legacy user_state cache key
    ]
    keys.extend(f"outbound_chat:{tk}" for tk in task_keys)
    if keys:
        client.delete(*keys)


async def ensure_smoke_data(business_id: str, customer_id: str) -> None:
    """Insert the business + customer + demo product rows the smoke harness needs.

    Re-running with the same UUIDs is a no-op (every INSERT is guarded by
    ON CONFLICT DO NOTHING).
    """
    biz_uuid = UUID(business_id)
    cust_uuid = UUID(customer_id)
    phone = f"{_CUSTOMER_PHONE_PREFIX}{customer_id[:8]}"

    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO businesses (
                id, name, bank_name, bank_account_number, bank_account_name
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO NOTHING
            """,
            biz_uuid,
            _BUSINESS_NAME,
            _BANK_NAME,
            _BANK_ACCOUNT_NUMBER,
            _BANK_ACCOUNT_NAME,
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
        # `products` has no UNIQUE constraint we can target with ON CONFLICT,
        # so guard each row with a NOT EXISTS check on (business_id, sku).
        for product in _DEMO_PRODUCTS:
            await conn.execute(
                """
                INSERT INTO products (
                    business_id, name, description, price,
                    stock_quantity, sku, category
                )
                SELECT $1, $2, $3, $4, $5, $6, $7
                WHERE NOT EXISTS (
                    SELECT 1 FROM products
                    WHERE business_id = $1 AND sku = $6
                )
                """,
                biz_uuid,
                product["name"],
                product["description"],
                product["price"],
                product["stock_quantity"],
                product["sku"],
                product["category"],
            )
