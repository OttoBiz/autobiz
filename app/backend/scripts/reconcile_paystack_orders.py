"""
Heuristic reconciliation: Paystack webhook rows in Postgres with no order in the follow-up window.

Run from app root:
    python -m backend.scripts.reconcile_paystack_orders

See also: db_utils.list_paystack_webhooks_missing_recent_order
"""

import asyncio

from backend.db.connection import close_db, init_db
from backend.db.db_utils import list_paystack_webhooks_missing_recent_order


async def _main() -> None:
    await init_db()
    try:
        rows = await list_paystack_webhooks_missing_recent_order(7)
        for r in rows:
            print(dict(r))
        print(f"total={len(rows)}")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(_main())
