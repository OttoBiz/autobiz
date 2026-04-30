"""Seed a single business profile bound to a real WhatsApp phone_number_id.

Reads from .env:
- WHATSAPP_PHONE_NUMBER_ID  (required) — Meta-assigned sender ID
- SEED_BUSINESS_NAME        (optional, default: "Test Shop")
- SEED_BUSINESS_PHONE       (optional, default: "+2347000000000")
- SEED_BUSINESS_ID          (optional, default: deterministic UUID derived
                             from phone_number_id; pass to override)
- SEED_PRODUCTS_CSV         (optional, default:
                             app/backend/dummy_data/donrey_fashion.csv)

Idempotent: re-running with the same phone_number_id updates the existing
row and replaces its products. Run after migrations are applied.

Usage:
    python scripts/seed_whatsapp_business.py
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from backend.db.connection import close_db, get_db, init_db  # noqa: E402

DEFAULT_CSV = ROOT / "app" / "backend" / "dummy_data" / "donrey_fashion.csv"
NAMESPACE = uuid.UUID("00000000-0000-0000-0003-000000000000")


def _derive_uuid(phone_number_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, phone_number_id))


def _parse_products(csv_path: Path) -> list[tuple[str, str, float, int, str]]:
    rows: list[tuple[str, str, float, int, str]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("Product") or "").strip()
            if not name:
                continue
            desc = (r.get("Description") or name).strip() or name
            try:
                price = float(r.get("Price", 0) or 0)
            except ValueError:
                price = 0.0
            try:
                stock = int(r.get("Available amount", 0) or 0)
            except ValueError:
                stock = 0
            category = (r.get("Product category") or "General").strip() or "General"
            rows.append((name, desc, price, stock, category))
    return rows


async def seed() -> None:
    load_dotenv()

    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not phone_number_id:
        raise SystemExit(
            "WHATSAPP_PHONE_NUMBER_ID is required in .env to seed a WhatsApp business"
        )

    business_name = os.getenv("SEED_BUSINESS_NAME", "Test Shop").strip()
    business_phone = os.getenv("SEED_BUSINESS_PHONE", "+2347000000000").strip()
    business_id = os.getenv("SEED_BUSINESS_ID", "").strip() or _derive_uuid(
        phone_number_id
    )

    csv_path = Path(os.getenv("SEED_PRODUCTS_CSV", str(DEFAULT_CSV)))
    if not csv_path.exists():
        raise SystemExit(f"products CSV not found: {csv_path}")

    products = _parse_products(csv_path)
    if not products:
        raise SystemExit(f"no products parsed from {csv_path}")

    await init_db()
    pool = await get_db()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO businesses (
                        id, name, business_type, phone_number,
                        whatsapp_phone_number_id
                    )
                    VALUES ($1, $2, 'vendor', $3, $4)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        phone_number = EXCLUDED.phone_number,
                        whatsapp_phone_number_id = EXCLUDED.whatsapp_phone_number_id,
                        updated_at = NOW()
                    """,
                    business_id,
                    business_name,
                    business_phone,
                    phone_number_id,
                )
                # Replace products for this business so re-runs don't duplicate.
                await conn.execute(
                    "DELETE FROM products WHERE business_id = $1", business_id
                )
                for name, desc, price, stock, category in products:
                    await conn.execute(
                        """
                        INSERT INTO products (
                            business_id, name, description, price,
                            stock_quantity, category
                        )
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        business_id,
                        name,
                        desc,
                        price,
                        stock,
                        category,
                    )

        print(f"✓ Seeded business {business_name} (id={business_id})")
        print(f"  phone_number={business_phone}")
        print(f"  whatsapp_phone_number_id={phone_number_id}")
        print(f"  products={len(products)} (from {csv_path.name})")
    finally:
        await close_db()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(seed())
