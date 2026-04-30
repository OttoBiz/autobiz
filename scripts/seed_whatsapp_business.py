"""Seed a single WhatsApp-bound business profile (CLI wrapper).

The same seed runs automatically at startup via `populate_db_on_startup`
when `WHATSAPP_PHONE_NUMBER_ID` is set; this script lets you trigger it
manually against an already-running database (e.g. after rotating the
phone_number_id, or re-importing products).

Reads from .env:
- WHATSAPP_PHONE_NUMBER_ID  (required) — Meta-assigned sender ID
- SEED_BUSINESS_NAME        (default: "Test Shop")
- SEED_BUSINESS_PHONE       (default: "+2347000000000")
- SEED_BUSINESS_ID          (default: deterministic UUID from phone_number_id)
- SEED_PRODUCTS_CSV         (default: app/backend/dummy_data/donrey_fashion.csv)

Usage:
    python scripts/seed_whatsapp_business.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from backend.db.connection import close_db, get_db, init_db  # noqa: E402
from backend.db.seed_whatsapp import seed_whatsapp_business_from_env  # noqa: E402


async def main() -> None:
    load_dotenv()
    await init_db()
    pool = await get_db()
    try:
        summary = await seed_whatsapp_business_from_env(pool)
        if summary is None:
            raise SystemExit(
                "WHATSAPP_PHONE_NUMBER_ID is required in .env to seed"
            )
        print(f"✓ Seeded business {summary['name']} (id={summary['business_id']})")
        print(f"  phone_number={summary['phone_number']}")
        print(f"  whatsapp_phone_number_id={summary['whatsapp_phone_number_id']}")
        print(
            f"  products={summary['products']} "
            f"(from {Path(summary['products_csv']).name})"
        )
    finally:
        await close_db()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())
