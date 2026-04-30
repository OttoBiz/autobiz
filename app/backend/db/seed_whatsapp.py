"""Idempotent seeding for a WhatsApp-bound tenant.

Runs at deploy time (from `populate_db_on_startup`) and from the CLI
(`scripts/seed_whatsapp_business.py`). The shared `seed_whatsapp_business`
upserts a `businesses` row keyed by a deterministic UUID (derived from the
Meta `phone_number_id`) and replaces its product rows from a CSV.

Re-running with the same `phone_number_id` is safe: the business row is
updated in place; products for that business are deleted and reinserted.
"""

from __future__ import annotations

import csv
import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Repo layout: this file is at app/backend/db/seed_whatsapp.py.
# Default product CSV lives under app/backend/dummy_data/.
DEFAULT_CSV = (
    Path(__file__).resolve().parent.parent / "dummy_data" / "donrey_fashion.csv"
)

# UUID v5 namespace for WA-bound businesses. Stable so re-deploys land on
# the same row without collision with the frontend fixture UUID space.
_NAMESPACE = uuid.UUID("00000000-0000-0000-0003-000000000000")


def derive_business_id(phone_number_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, phone_number_id))


def parse_products(csv_path: Path) -> list[tuple[str, str, float, int, str]]:
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


async def seed_whatsapp_business(
    pool,
    *,
    phone_number_id: str,
    business_name: str,
    business_phone: str,
    products_csv: Path,
    business_id: str | None = None,
) -> dict:
    """Upsert one WhatsApp-bound business + its products. Returns a summary."""
    if not phone_number_id:
        raise ValueError("phone_number_id is required")
    if not products_csv.exists():
        raise FileNotFoundError(f"products CSV not found: {products_csv}")

    products = parse_products(products_csv)
    if not products:
        raise ValueError(f"no products parsed from {products_csv}")

    bid = business_id or derive_business_id(phone_number_id)

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
                bid,
                business_name,
                business_phone,
                phone_number_id,
            )
            await conn.execute(
                "DELETE FROM products WHERE business_id = $1", bid
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
                    bid,
                    name,
                    desc,
                    price,
                    stock,
                    category,
                )

    return {
        "business_id": bid,
        "name": business_name,
        "phone_number": business_phone,
        "whatsapp_phone_number_id": phone_number_id,
        "products": len(products),
        "products_csv": str(products_csv),
    }


async def seed_whatsapp_business_from_env(pool) -> dict | None:
    """Seed if `WHATSAPP_PHONE_NUMBER_ID` is set, otherwise no-op.

    Reads:
    - WHATSAPP_PHONE_NUMBER_ID  (required to seed)
    - SEED_BUSINESS_NAME        (default: "Test Shop")
    - SEED_BUSINESS_PHONE       (default: "+2347000000000")
    - SEED_BUSINESS_ID          (default: derived from phone_number_id)
    - SEED_PRODUCTS_CSV         (default: donrey_fashion.csv)

    Returns the seed summary on success, None when skipped.
    """
    phone_number_id = (os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    if not phone_number_id:
        logger.info("WHATSAPP_PHONE_NUMBER_ID not set; skipping WhatsApp seed")
        return None

    summary = await seed_whatsapp_business(
        pool,
        phone_number_id=phone_number_id,
        business_name=(os.getenv("SEED_BUSINESS_NAME") or "Test Shop").strip(),
        business_phone=(
            os.getenv("SEED_BUSINESS_PHONE") or "+2347000000000"
        ).strip(),
        products_csv=Path(os.getenv("SEED_PRODUCTS_CSV") or str(DEFAULT_CSV)),
        business_id=(os.getenv("SEED_BUSINESS_ID") or "").strip() or None,
    )
    logger.info(
        "Seeded WhatsApp business id=%s name=%s products=%d",
        summary["business_id"],
        summary["name"],
        summary["products"],
    )
    return summary
