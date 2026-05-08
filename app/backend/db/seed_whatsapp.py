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
    contacts_csv: Path | None = None,
    seed_self_vendor: bool = False,
    self_vendor_name: str = "Self",
    self_vendor_role: str = "vendor",
    self_vendor_notes: str | None = None,
    bank_name: str | None = None,
    bank_account_number: str | None = None,
    bank_account_name: str | None = None,
) -> dict:
    """Upsert one WhatsApp-bound business + its products. Returns a summary.

    `business_phone` is stored in `businesses.phone_number` and is the
    operator's wa_id (no leading `+`). The inbound resolver matches the
    sender's wa_id against this column to detect operator self-messages,
    so the format must be plain digits — a leading `+` is stripped here.
    """
    if not phone_number_id:
        raise ValueError("phone_number_id is required")
    if not products_csv.exists():
        raise FileNotFoundError(f"products CSV not found: {products_csv}")

    products = parse_products(products_csv)
    if not products:
        raise ValueError(f"no products parsed from {products_csv}")

    bid = business_id or derive_business_id(phone_number_id)

    # Normalize to wa_id format (digits only). The resolver does an exact
    # equality match against inbound `wa_id`, which Meta delivers without
    # a `+`, so anything stored here must follow the same convention.
    normalized_phone = business_phone.lstrip("+").strip()

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO businesses (
                    id, name, business_type, phone_number,
                    whatsapp_phone_number_id,
                    bank_name, bank_account_number, bank_account_name
                )
                VALUES ($1, $2, 'vendor', $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    phone_number = EXCLUDED.phone_number,
                    whatsapp_phone_number_id = EXCLUDED.whatsapp_phone_number_id,
                    bank_name = COALESCE(EXCLUDED.bank_name, businesses.bank_name),
                    bank_account_number = COALESCE(EXCLUDED.bank_account_number, businesses.bank_account_number),
                    bank_account_name = COALESCE(EXCLUDED.bank_account_name, businesses.bank_account_name),
                    updated_at = NOW()
                """,
                bid,
                business_name,
                normalized_phone,
                phone_number_id,
                bank_name,
                bank_account_number,
                bank_account_name,
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

    contacts_count = 0
    if contacts_csv is not None and contacts_csv.exists():
        # Lazy import to avoid import cycles at module load time and to
        # keep the seeder usable without the contacts module if unused.
        from backend.db import contacts as contacts_db
        from uuid import UUID

        bid_uuid = UUID(bid)
        with open(contacts_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                name = (r.get("name") or "").strip()
                if not name:
                    continue
                role = (r.get("role") or "").strip()
                channel = (r.get("channel") or "").strip() or "whatsapp"
                channel_user_id = (r.get("channel_user_id") or "").strip()
                if channel_user_id.startswith("+"):
                    channel_user_id = channel_user_id[1:]
                if not channel_user_id:
                    logger.warning(
                        "skipping contact %r: empty channel_user_id", name
                    )
                    continue
                notes_raw = (r.get("notes") or "").strip()
                notes = notes_raw or None
                await contacts_db.upsert(
                    business_id=bid_uuid,
                    name=name,
                    role=role,
                    channel=channel,
                    channel_user_id=channel_user_id,
                    channel_business_id=None,
                    notes=notes,
                )
                contacts_count += 1

    # Single-person tenants: the operator IS the vendor. Register their own
    # phone as a contact so inbound messages from that number route through
    # the outbound flow instead of being dropped as owner self-messages by
    # the inbound resolver.
    if seed_self_vendor:
        from backend.db import contacts as contacts_db
        from uuid import UUID

        await contacts_db.upsert(
            business_id=UUID(bid),
            name=self_vendor_name,
            role=self_vendor_role,
            channel="whatsapp",
            channel_user_id=normalized_phone,
            channel_business_id=None,
            notes=self_vendor_notes,
        )
        contacts_count += 1

    return {
        "business_id": bid,
        "name": business_name,
        "phone_number": normalized_phone,
        "whatsapp_phone_number_id": phone_number_id,
        "products": len(products),
        "products_csv": str(products_csv),
        "contacts": contacts_count,
    }


async def seed_whatsapp_business_from_env(pool) -> dict | None:
    """Seed if `WHATSAPP_PHONE_NUMBER_ID` is set, otherwise no-op.

    Reads:
    - WHATSAPP_PHONE_NUMBER_ID  (required to seed)
    - SEED_BUSINESS_NAME        (default: "Test Shop")
    - SEED_BUSINESS_PHONE       (default: "2347000000000") — operator's wa_id;
                                 stored on `businesses.phone_number` and used
                                 by the inbound resolver to detect owner
                                 self-messages. Strip a leading `+` if your
                                 value has one — it's normalized either way.
    - SEED_BUSINESS_ID          (default: derived from phone_number_id)
    - SEED_PRODUCTS_CSV         (default: donrey_fashion.csv)
    - SEED_CONTACTS_CSV         (default: contacts.example.csv if present;
                                 otherwise contact seeding is skipped)
    - SEED_SELF_VENDOR          ("1"/"true"/"yes" to register the operator's
                                 own phone as a vendor contact — single-person
                                 tenants where the owner IS the vendor)
    - SEED_SELF_VENDOR_NAME     (default: "Self")
    - SEED_SELF_VENDOR_ROLE     (default: "vendor")
    - SEED_SELF_VENDOR_NOTES    (default: empty)
    - SEED_BANK_NAME            (default: "Stanbic IBTC")
    - SEED_BANK_ACCOUNT_NUMBER  (default: "0032642727")
    - SEED_BANK_ACCOUNT_NAME    (default: "David Okpare")

    Returns the seed summary on success, None when skipped.
    """
    phone_number_id = (os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    if not phone_number_id:
        logger.info("WHATSAPP_PHONE_NUMBER_ID not set; skipping WhatsApp seed")
        return None

    contacts_csv_env = (os.getenv("SEED_CONTACTS_CSV") or "").strip()
    if contacts_csv_env:
        contacts_csv: Path | None = Path(contacts_csv_env)
    else:
        default_contacts = (
            Path(__file__).resolve().parent.parent
            / "dummy_data"
            / "contacts.example.csv"
        )
        contacts_csv = default_contacts if default_contacts.exists() else None

    raw_self_vendor = os.getenv("SEED_SELF_VENDOR")
    self_vendor_flag = (raw_self_vendor or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    logger.info(
        "SEED_SELF_VENDOR raw=%r resolved=%s", raw_self_vendor, self_vendor_flag
    )

    summary = await seed_whatsapp_business(
        pool,
        phone_number_id=phone_number_id,
        business_name=(os.getenv("SEED_BUSINESS_NAME") or "Test Shop").strip(),
        business_phone=(
            os.getenv("SEED_BUSINESS_PHONE") or "2347000000000"
        ).strip(),
        products_csv=Path(os.getenv("SEED_PRODUCTS_CSV") or str(DEFAULT_CSV)),
        business_id=(os.getenv("SEED_BUSINESS_ID") or "").strip() or None,
        contacts_csv=contacts_csv,
        seed_self_vendor=self_vendor_flag,
        self_vendor_name=(os.getenv("SEED_SELF_VENDOR_NAME") or "Self").strip(),
        self_vendor_role=(os.getenv("SEED_SELF_VENDOR_ROLE") or "vendor").strip(),
        self_vendor_notes=(os.getenv("SEED_SELF_VENDOR_NOTES") or "").strip() or None,
        bank_name=(os.getenv("SEED_BANK_NAME") or "Stanbic IBTC").strip() or None,
        bank_account_number=(os.getenv("SEED_BANK_ACCOUNT_NUMBER") or "0032642727").strip() or None,
        bank_account_name=(os.getenv("SEED_BANK_ACCOUNT_NAME") or "David Okpare").strip() or None,
    )
    logger.info(
        "Seeded WhatsApp business id=%s name=%s products=%d phone=%s contacts=%d",
        summary["business_id"],
        summary["name"],
        summary["products"],
        summary["phone_number"],
        summary["contacts"],
    )
    return summary
