"""
Database population: run migrations and seed with dummy data.
Uses hardcoded UUIDs matching frontend predefined businesses.
"""
import csv
import json
import logging
from pathlib import Path

from backend.db.connection import get_db
from backend.db.seed_whatsapp import seed_whatsapp_business_from_env

# Hardcoded UUIDs matching frontend/app/page.tsx
FRONTEND_USER_IDS = {
    "John Doe": "00000000-0000-0000-0000-000000000001",
    "Sarah Johnson": "00000000-0000-0000-0000-000000000002",
    "Michael Chen": "00000000-0000-0000-0000-000000000003",
    "Emily Rodriguez": "00000000-0000-0000-0000-000000000004",
    "David Wilson": "00000000-0000-0000-0000-000000000005",
    "Lisa Thompson": "00000000-0000-0000-0000-000000000006",
}

FRONTEND_BUSINESS_IDS = {
    "Donrey Fashion": "00000000-0000-0000-0001-000000000001",
    "Junae Cosmetics": "00000000-0000-0000-0001-000000000002",
    "Manny Gadgets": "00000000-0000-0000-0001-000000000003",
    "Tesla Tech": "00000000-0000-0000-0001-000000000004",
    "Kemi Surprises": "00000000-0000-0000-0001-000000000005",
}

FRONTEND_LOGISTICS_IDS = {
    "Fast Delivery Co": "00000000-0000-0000-0002-000000000001",
    "Express Logistics": "00000000-0000-0000-0002-000000000002",
    "Quick Ship": "00000000-0000-0000-0002-000000000003",
}

# Map dummy data filenames to frontend business names
DUMMY_FILE_TO_BUSINESS = {
    "donrey_fashion": "Donrey Fashion",
    "junae_cosmetics": "Junae Cosmetics",
    "manny_gadgets": "Manny Gadgets",
    "tesla_tech": "Tesla Tech",
    "kemi_surprises": "Kemi Surprises",
}

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DUMMY_DATA_DIR = Path(__file__).resolve().parent.parent / "dummy_data"


def _or_default(val: str | None, default: str) -> str:
    """Return val if non-empty, else default."""
    return (val or "").strip() or default


def _dummy_business_fields(slug: str, seed: int = 0) -> dict:
    """Generate dummy values for missing business columns."""
    base = slug.lower().replace(" ", "_").replace("-", "_")
    n = abs(hash(base) + seed) % 1000000
    return {
        "phone_number": f"+234700{n:06d}",
        "email": f"{base}@example.com",
        "ig_page": f"{base}_ig",
        "facebook_page": f"facebook.com/{base}",
        "twitter_page": f"twitter.com/{base}",
        "tiktok": f"@{base}",
        "bank_name": "gtbank",
        "bank_account_number": f"{n:010d}",
        "bank_account_name": f"{slug} Ltd",
        "business_description": f"Business description for {slug}",
        "business_niche": "general",
    }


def _dummy_user_fields(name: str, idx: int) -> dict:
    """Generate dummy values for user columns."""
    return {
        "phone_number": f"+234700000{idx:04d}",
        "full_name": name,
        "delivery_address": f"123 {name.split()[0]} Street, Apt {idx}",
        "city": ["Lagos", "Abuja", "Port Harcourt", "Ibadan", "Kano", "Benin"][idx % 6],
        "state": ["Lagos", "FCT", "Rivers", "Oyo", "Kano", "Edo"][idx % 6],
    }


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


def _business_row(uuid: str, name: str, row: dict | None, dummy: dict, business_type: str) -> tuple:
    """Build a business row, filling missing columns with dummy values."""
    if row:
        return (
            uuid,
            name,
            "{}",
            business_type,
            _or_default(row.get("phone number"), dummy["phone_number"]),
            _or_default(row.get("email"), dummy["email"]),
            _or_default(row.get("ig page"), dummy["ig_page"]),
            _or_default(row.get("facebook page"), dummy["facebook_page"]),
            _or_default(row.get("twitter page"), dummy["twitter_page"]),
            _or_default(row.get("tiktok"), dummy["tiktok"]),
            _or_default(row.get("Bank name"), dummy["bank_name"]),
            _or_default(row.get("Bank account number"), dummy["bank_account_number"]),
            _or_default(row.get("Bank account name"), dummy["bank_account_name"]),
        )
    return (
        uuid, name, "{}", business_type,
        dummy["phone_number"], dummy["email"], dummy["ig_page"],
        dummy["facebook_page"], dummy["twitter_page"], dummy["tiktok"],
        dummy["bank_name"], dummy["bank_account_number"], dummy["bank_account_name"],
    )


async def _load_users(pool) -> None:
    """Insert users with hardcoded UUIDs matching frontend predefinedUsers."""
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE users CASCADE")
        for idx, (name, uuid) in enumerate(FRONTEND_USER_IDS.items(), start=1):
            fields = _dummy_user_fields(name, idx)
            await conn.execute(
                """
                INSERT INTO users (id, phone_number, full_name, delivery_address, city, state)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                uuid,
                fields["phone_number"],
                fields["full_name"],
                fields["delivery_address"],
                fields["city"],
                fields["state"],
            )


async def _load_businesses(pool) -> None:
    """Insert businesses (vendors + logistics) with hardcoded UUIDs."""
    business_csv = DUMMY_DATA_DIR / "Business_table.csv"
    table_by_key = {}
    if business_csv.exists():
        with open(business_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = row.get("business name", "").strip().lower().replace(" ", "_")
                table_by_key[key] = row

    rows_to_insert = []
    for idx, (name, uuid) in enumerate(FRONTEND_BUSINESS_IDS.items()):
        key = name.lower().replace(" ", "_")
        row = table_by_key.get(key)
        dummy = _dummy_business_fields(name, seed=idx + 10)
        rows_to_insert.append(_business_row(uuid, name, row, dummy, "vendor"))

    for idx, (name, uuid) in enumerate(FRONTEND_LOGISTICS_IDS.items()):
        dummy = _dummy_business_fields(name, seed=idx + 20)
        rows_to_insert.append(_business_row(uuid, name, None, dummy, "logistics"))

    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE businesses CASCADE")
        for r in rows_to_insert:
            await conn.execute(
                """
                INSERT INTO businesses (
                    id, name, product_schema, business_type, phone_number, email,
                    ig_page, facebook_page, twitter_page, tiktok,
                    bank_name, bank_account_number, bank_account_name
                ) VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                *r,
            )


def _parse_standard_products(csv_path: str, business_id: str) -> list[tuple]:
    """Parse manny_gadgets, donrey_fashion, junae_cosmetics format."""
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("Product") or "").strip()
            if not name:
                continue
            desc = _or_default(r.get("Description"), name)
            price = float(r.get("Price", 0) or 0)
            stock = int(r.get("Available amount", 0) or r.get("amount in stock", 0) or 0)
            category = _or_default(r.get("Product category") or r.get("category of product"), "General")
            rows.append((business_id, name, desc, price, stock, category, {}))
    return rows


def _parse_tesla_tech(csv_path: str, business_id: str) -> list[tuple]:
    """Parse tesla_tech.csv format."""
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("Product") or "").strip()
            if not name:
                continue
            price = float(r.get("price", 0) or 0)
            attrs = {k: v for k, v in r.items() if k not in ("id", "Product", "price") and v}
            attrs.pop("Date created", None)
            attrs.pop("Date modified", None)
            desc = f"{r.get('processor', '')} {r.get('ram', '')} {r.get('storage space', '')}".strip()
            rows.append((business_id, name, desc or name, price, 1, _or_default(r.get("type"), "Electronics"), attrs))
    return rows


def _parse_kemi_surprises(csv_path: str, business_id: str) -> list[tuple]:
    """Parse kemi_surprises.csv format."""
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("Product") or "").strip()
            if not name:
                continue
            desc = _or_default(r.get("Product details"), name)
            price = float(r.get("Price", 0) or 0)
            stock = int(r.get("amount in stock", 0) or 0)
            category = _or_default(r.get("category of product"), "General")
            attrs = {k: r[k] for k in ("size", "fragrance", "color") if r.get(k)}
            rows.append((business_id, name, desc, price, stock, category, attrs))
    return rows


async def _load_products(pool) -> None:
    """Load products from dummy CSVs for frontend businesses only."""
    parsers = {
        "donrey_fashion": _parse_standard_products,
        "junae_cosmetics": _parse_standard_products,
        "manny_gadgets": _parse_standard_products,
        "tesla_tech": _parse_tesla_tech,
        "kemi_surprises": _parse_kemi_surprises,
    }

    all_rows = []
    for filename, business_name in DUMMY_FILE_TO_BUSINESS.items():
        business_id = FRONTEND_BUSINESS_IDS[business_name]
        csv_path = DUMMY_DATA_DIR / f"{filename}.csv"
        if not csv_path.exists():
            logging.warning(f"Dummy data CSV not found, skipping products for '{business_name}': {csv_path}")
            print(f"⚠ Missing CSV: {csv_path}")
            continue
        parse_fn = parsers[filename]
        rows = parse_fn(str(csv_path), business_id)
        all_rows.extend(rows)

    async with pool.acquire() as conn:
        for r in all_rows:
            business_id, name, desc, price, stock, category, attrs = r
            await conn.execute(
                """
                INSERT INTO products (business_id, name, description, price, stock_quantity, category, attributes)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                """,
                business_id,
                name,
                desc,
                price,
                stock,
                category or None,
                json.dumps(attrs) if attrs else "{}",
            )


async def populate_db_on_startup() -> None:
    """Run migrations and seed database. Idempotent on re-run."""
    pool = await get_db()  # Let exception propagate — caller handles retries

    try:
        await _run_migrations(pool)
        # Truncate dependents first to avoid FK constraint conflicts:
        # users CASCADE → orders, transactions
        # businesses CASCADE → products, orders (already gone), transactions (already gone)
        await _load_users(pool)
        await _load_businesses(pool)
        await _load_products(pool)
        # Bind a tenant row to the deployed WhatsApp number when the
        # required env vars are present; no-op otherwise. Runs after the
        # frontend fixtures so this row coexists with the dummy ones.
        await seed_whatsapp_business_from_env(pool)
        logging.info("Database populated successfully")
    except Exception as e:
        logging.error(f"populate_db_on_startup failed: {e}")
        raise
