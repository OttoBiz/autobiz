"""
Database prepopulation script for Ottobiz.

Generates realistic test data using Faker and inserts it into PostgreSQL.
Safe to run multiple times (idempotent via ON CONFLICT / delete-then-reinsert).

Run:
    cd app && python -m backend.scripts.prepopulate_db
"""

import asyncio
import json
import random
import uuid
from datetime import datetime, timedelta

from backend.db.connection import close_db, get_db, init_db
from backend.logging_config import get_logger, setup_logging
from faker import Faker

setup_logging()
logger = get_logger(__name__)

fake = Faker()

NIGERIAN_STATES = [
    ("Lagos", ["Ikeja", "Lekki", "Victoria Island", "Surulere", "Yaba"]),
    ("Abuja", ["Garki", "Wuse", "Maitama", "Asokoro", "Gwarinpa"]),
    ("Rivers", ["Port Harcourt", "Obio-Akpor", "Eleme"]),
    ("Oyo", ["Ibadan", "Ogbomoso", "Oyo"]),
    ("Kano", ["Kano Municipal", "Nassarawa", "Tarauni"]),
]

PAYMENT_METHODS = ["bank_transfer", "paystack", "cash"]
ORDER_STATUSES = ["pending", "payment_verified", "shipped", "delivered", "cancelled"]
TRANSACTION_STATUSES = ["pending", "verified", "failed"]

# Aligns with `backend.db.populate.SEEDED_VENDOR_BANK` for manual prepopulate runs.
VENDOR_BANK_SEED = {
    "Donrey Fashion": ("Guarantee Trust Bank", "0116042270", "jeffrey otoibhi"),
    "Manny Gadgets": ("Providus Bank", "6506842487", "jeffrey otoibhi"),
    "Junae Cosmetics": ("Providus Bank", "6506842487", "jeffrey otoibhi"),
    "Tesla Tech": ("Ecobank", "4251015814", "jeffrey otoibhi"),
}


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------


def _nigerian_phone():
    """Generate a realistic Nigerian phone number."""
    prefix = random.choice(
        [
            "0801",
            "0802",
            "0803",
            "0805",
            "0806",
            "0807",
            "0808",
            "0809",
            "0810",
            "0811",
            "0812",
            "0813",
            "0814",
            "0815",
            "0816",
            "0817",
            "0818",
            "0819",
            "0901",
            "0902",
            "0903",
            "0904",
            "0905",
            "0906",
            "0907",
            "0908",
            "0909",
            "0912",
            "0913",
            "0916",
        ]
    )
    return prefix + "".join([str(random.randint(0, 9)) for _ in range(7)])


def generate_businesses(count=8):
    """
    Generate 8 businesses: 5 vendors (2 free, 2 gold, 1 platinum) + 3 logistics.
    Returns list of dicts matching the businesses table schema.
    Uses deterministic UUIDs (uuid5 from name) so reruns are idempotent.
    """
    vendor_configs = [
        ("Donrey Fashion", "vendor", "free"),
        ("Junae Cosmetics", "vendor", "free"),
        ("Manny Gadgets", "vendor", "gold"),
        ("Tesla Tech", "vendor", "gold"),
        ("Kemi Surprises", "vendor", "platinum"),
    ]
    logistics_configs = [
        ("SwiftMove Logistics", "logistics", "free"),
        ("GoShip Express", "logistics", "gold"),
        ("PrimeDeliver", "logistics", "platinum"),
    ]

    # Fixed namespace for deterministic uuid5
    NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")

    businesses = []
    for name, btype, tier in vendor_configs + logistics_configs:
        rec = {
            "id": str(uuid.uuid5(NS, name)),
            "name": name,
            "business_type": btype,
            "tier": tier,
            "phone_number": _nigerian_phone(),
            "email": f"{name.lower().replace(' ', '')}@example.com",
            "ig_page": f"@{name.lower().replace(' ', '_')}",
            "facebook_page": name,
            "bank_name": random.choice(
                ["GTBank", "Access Bank", "Zenith Bank", "UBA", "First Bank"]
            ),
            "bank_account_number": "".join(
                [str(random.randint(0, 9)) for _ in range(10)]
            ),
            "bank_account_name": name,
            "product_schema": json.dumps({}),
            "currency": "NGN",
        }
        if name in VENDOR_BANK_SEED:
            bn, accn, accname = VENDOR_BANK_SEED[name]
            rec["bank_name"] = bn
            rec["bank_account_number"] = accn
            rec["bank_account_name"] = accname
        businesses.append(rec)

    return businesses


def generate_products(vendors, per_vendor=10):
    """
    Generate ~50 products (per_vendor products for each vendor business).
    Products have realistic names, prices, and JSONB attributes matched to
    each vendor's specialty category.
    """
    # Map vendor names to their primary category
    VENDOR_CATEGORY = {
        "Donrey Fashion": "Fashion",
        "Junae Cosmetics": "Cosmetics",
        "Manny Gadgets": "Electronics",
        "Tesla Tech": "Electronics",
        "Kemi Surprises": "Home & Living",
    }

    # Product templates per category: (name, description_template, price_range, attr_fn)
    CATALOG = {
        "Fashion": [
            ("Ankara Maxi Dress", "Vibrant ankara print maxi dress, perfect for events"),
            ("Slim Fit Chinos", "Comfortable slim fit chinos for everyday wear"),
            ("Agbada Set", "Traditional agbada set with cap, premium fabric"),
            ("Denim Jacket", "Classic denim jacket, stonewash finish"),
            ("Silk Camisole", "Lightweight silk camisole, adjustable straps"),
            ("Leather Belt", "Genuine leather belt with brushed metal buckle"),
            ("Adire T-Shirt", "Hand-dyed adire print cotton t-shirt"),
            ("Pleated Skirt", "Midi-length pleated skirt, elastic waist"),
            ("Polo Shirt", "Breathable cotton polo shirt with embroidered logo"),
            ("Sneakers", "Casual canvas sneakers, rubber sole"),
        ],
        "Electronics": [
            ("Wireless Earbuds", "Bluetooth 5.3 earbuds with noise cancellation"),
            ("Smart Watch", "Fitness tracker smartwatch with heart rate monitor"),
            ("Power Bank 20000mAh", "Fast-charging power bank, dual USB-C output"),
            ("Bluetooth Speaker", "Portable waterproof bluetooth speaker, 12hr battery"),
            ("USB-C Hub 7-in-1", "Multiport adapter: HDMI, USB-A, SD card, ethernet"),
            ("Webcam 1080p", "Full HD webcam with auto-focus and ring light"),
            ("Mechanical Keyboard", "RGB mechanical keyboard, hot-swappable switches"),
            ("Wireless Mouse", "Ergonomic wireless mouse, 3 DPI settings"),
            ("Phone Stand", "Adjustable aluminium phone/tablet stand"),
            ("LED Desk Lamp", "Dimmable LED desk lamp with USB charging port"),
        ],
        "Cosmetics": [
            ("Shea Butter Moisturizer", "100% organic shea butter for deep hydration"),
            ("Vitamin C Serum", "Brightening vitamin C serum for glowing skin"),
            ("Matte Lipstick Set", "Long-lasting matte lipstick, 6-shade collection"),
            ("Charcoal Face Mask", "Activated charcoal peel-off mask, pore cleansing"),
            ("Hair Growth Oil", "Natural hair growth oil with castor and coconut"),
            ("Setting Spray", "Long-wear makeup setting spray, 16hr hold"),
            ("Exfoliating Scrub", "Gentle exfoliating face scrub with oat extract"),
            ("Eyebrow Pencil", "Micro-tip eyebrow pencil, waterproof formula"),
            ("Body Lotion SPF30", "Daily body lotion with sun protection"),
            ("Perfume Oil Roll-On", "Long-lasting fragrance oil, floral notes"),
        ],
        "Home & Living": [
            ("Throw Pillow Set", "Decorative throw pillows, set of 4, ankara prints"),
            ("Scented Candle", "Soy wax scented candle, vanilla and cinnamon"),
            ("Wall Art Canvas", "Abstract wall art canvas print, 60x40cm"),
            ("Ceramic Vase", "Handmade ceramic vase, matte black finish"),
            ("Woven Basket", "Handwoven storage basket, natural palm leaf"),
            ("Table Runner", "Embroidered table runner, 180cm length"),
            ("Photo Frame Set", "Wooden photo frame set of 3, assorted sizes"),
            ("Desk Organizer", "Bamboo desk organizer with compartments"),
            ("Door Mat", "Coir door mat with welcome pattern, 60x40cm"),
            ("Bedside Lamp", "Minimalist bedside lamp, warm white LED"),
        ],
    }

    def _fashion_attrs():
        return {
            "size": random.choice(["XS", "S", "M", "L", "XL", "XXL"]),
            "color": random.choice(["Black", "White", "Blue", "Red", "Green", "Brown", "Multicolor"]),
            "material": random.choice(["Cotton", "Polyester", "Silk", "Denim", "Linen", "Ankara"]),
        }

    def _electronics_attrs():
        return {
            "brand": random.choice(["Samsung", "Oraimo", "Anker", "JBL", "Baseus", "Logitech"]),
            "warranty": random.choice(["6 months", "1 year", "2 years"]),
            "color": random.choice(["Black", "White", "Silver", "Blue"]),
        }

    def _cosmetics_attrs():
        return {
            "skin_type": random.choice(["all", "oily", "dry", "sensitive", "combination"]),
            "volume_ml": random.choice([30, 50, 100, 200, 250]),
            "organic": random.choice([True, False]),
        }

    def _home_attrs():
        return {
            "material": random.choice(["Wood", "Bamboo", "Ceramic", "Fabric", "Glass", "Palm Leaf"]),
            "color": random.choice(["Brown", "Black", "White", "Natural", "Multicolor"]),
            "dimensions": random.choice(["20x20cm", "30x40cm", "40x60cm", "60x40cm"]),
        }

    ATTR_FNS = {
        "Fashion": _fashion_attrs,
        "Electronics": _electronics_attrs,
        "Cosmetics": _cosmetics_attrs,
        "Home & Living": _home_attrs,
    }

    products = []
    sku_counter = 0

    for vendor in vendors:
        category = VENDOR_CATEGORY.get(vendor["name"], "Home & Living")
        templates = CATALOG[category]

        for i, (name, description) in enumerate(templates[:per_vendor]):
            sku_counter += 1
            # 1-2 out-of-stock items per vendor (indices 7 and 9)
            out_of_stock = i in (7, 9)
            # One inactive product per vendor (index 9)
            inactive = i == 9

            products.append(
                {
                    "id": str(uuid.uuid4()),
                    "business_id": vendor["id"],
                    "name": name,
                    "description": description,
                    "price": round(random.uniform(5, 1000), 2),
                    "stock_quantity": 0 if out_of_stock else random.randint(5, 200),
                    "sku": f"SKU-{category[:3].upper()}-{sku_counter:03d}",
                    "category": category,
                    "attributes": ATTR_FNS[category](),
                    "is_active": not inactive,
                    "currency": "NGN",
                }
            )

    return products


def generate_users(count=15):
    """Generate 15 users with Nigerian phone numbers, cities, and states."""
    users = []
    for i in range(count):
        state_name, cities = random.choice(NIGERIAN_STATES)
        city = random.choice(cities)
        users.append(
            {
                "id": str(uuid.uuid4()),
                "phone_number": _nigerian_phone(),
                "full_name": fake.name(),
                "delivery_address": f"{random.randint(1, 200)} {fake.street_name()}, {city}",
                "city": city,
                "state": state_name,
            }
        )
    return users


def generate_orders(users, vendors, logistics, count=30):
    """Generate 30 orders linked to users, vendors, and logistics."""
    orders = []
    for i in range(count):
        user = random.choice(users)
        vendor = random.choice(vendors)
        logistic = random.choice(logistics) if random.random() > 0.3 else None
        status = random.choice(ORDER_STATUSES)
        created = datetime.now() - timedelta(days=random.randint(1, 90))

        orders.append(
            {
                "id": str(uuid.uuid4()),
                "order_number": f"ORD-{created.strftime('%Y%m%d')}-{random.randint(1000, 9999)}",
                "user_id": user["id"],
                "business_id": vendor["id"],
                "logistic_id": logistic["id"] if logistic else None,
                "status": status,
                # Order totals in NGN; keep plausible vs catalog cap ₦1000/item × few lines
                "total_amount": round(random.uniform(25, 8000), 2),
                "delivery_address": user["delivery_address"],
                "delivery_city": user["city"],
                "delivery_state": user["state"],
                "tracking_number": f"TRK-{random.randint(100000, 999999)}"
                if status in ("shipped", "delivered")
                else None,
                "product_name": f"{fake.word().title()} {fake.word().title()}",
                "product_attributes": {
                    "size": random.choice(["S", "M", "L", "XL"]),
                    "color": random.choice(["Red", "Blue", "Black", "Green"]),
                    "line_items": random.randint(1, 5),
                },
                "metadata": json.dumps({"items": random.randint(1, 5)}),
                "created_at": created.isoformat(),
            }
        )
    return orders


def generate_transactions(orders, count=25):
    """Generate 25 transactions linked to orders."""
    transactions = []
    sampled_orders = random.sample(orders, min(count, len(orders)))

    for order in sampled_orders:
        status = (
            "verified"
            if order["status"] in ("payment_verified", "shipped", "delivered")
            else random.choice(TRANSACTION_STATUSES)
        )
        transactions.append(
            {
                "id": str(uuid.uuid4()),
                "order_id": order["id"],
                "user_id": order["user_id"],
                "business_id": order["business_id"],
                "amount": order["total_amount"],
                "payment_method": random.choice(PAYMENT_METHODS),
                "transaction_reference": f"TXN-{random.randint(100000, 999999)}",
                "bank_name": random.choice(
                    ["GTBank", "Access Bank", "Zenith Bank", "UBA"]
                ),
                "account_number": "".join(
                    [str(random.randint(0, 9)) for _ in range(10)]
                ),
                "status": status,
                "metadata": json.dumps({}),
            }
        )
    return transactions


# ---------------------------------------------------------------------------
# Insert functions (idempotent)
# ---------------------------------------------------------------------------


async def insert_businesses(pool, data):
    """Insert businesses — ON CONFLICT (id) DO UPDATE to allow reruns."""
    query = """
        INSERT INTO businesses (
            id, name, business_type, tier, phone_number, email,
            ig_page, facebook_page,
            bank_name, bank_account_number, bank_account_name,
            product_schema, currency
        ) VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            business_type = EXCLUDED.business_type,
            tier = EXCLUDED.tier,
            phone_number = EXCLUDED.phone_number,
            email = EXCLUDED.email,
            ig_page = EXCLUDED.ig_page,
            facebook_page = EXCLUDED.facebook_page,
            bank_name = EXCLUDED.bank_name,
            bank_account_number = EXCLUDED.bank_account_number,
            bank_account_name = EXCLUDED.bank_account_name,
            product_schema = EXCLUDED.product_schema,
            currency = EXCLUDED.currency,
            updated_at = NOW()
    """
    async with pool.acquire() as conn:
        for b in data:
            await conn.execute(
                query,
                b["id"],
                b["name"],
                b["business_type"],
                b["tier"],
                b["phone_number"],
                b["email"],
                b["ig_page"],
                b["facebook_page"],
                b["bank_name"],
                b["bank_account_number"],
                b["bank_account_name"],
                b["product_schema"],
                b.get("currency") or "NGN",
            )
    logger.info("Inserted %d businesses", len(data))


async def insert_products(pool, data):
    """Delete existing products for each business, then insert fresh."""
    business_ids = {p["business_id"] for p in data}

    async with pool.acquire() as conn:
        for bid in business_ids:
            await conn.execute("DELETE FROM products WHERE business_id = $1::uuid", bid)

        query = """
            INSERT INTO products (
                id, business_id, name, description, price, stock_quantity,
                sku, category, attributes, is_active, currency
            ) VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
        """
        for p in data:
            await conn.execute(
                query,
                p["id"],
                p["business_id"],
                p["name"],
                p["description"],
                p["price"],
                p["stock_quantity"],
                p["sku"],
                p["category"],
                json.dumps(p["attributes"]),
                p["is_active"],
                p.get("currency") or "NGN",
            )
    logger.info("Inserted %d products", len(data))


async def insert_users(pool, data):
    """Upsert users — ON CONFLICT (phone_number) DO UPDATE."""
    query = """
        INSERT INTO users (id, phone_number, full_name, delivery_address, city, state)
        VALUES ($1::uuid, $2, $3, $4, $5, $6)
        ON CONFLICT (phone_number) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            delivery_address = EXCLUDED.delivery_address,
            city = EXCLUDED.city,
            state = EXCLUDED.state,
            updated_at = NOW()
    """
    async with pool.acquire() as conn:
        for u in data:
            await conn.execute(
                query,
                u["id"],
                u["phone_number"],
                u["full_name"],
                u["delivery_address"],
                u["city"],
                u["state"],
            )
    logger.info("Inserted %d users", len(data))


async def insert_orders(pool, data):
    """Insert orders — ON CONFLICT (order_number) DO NOTHING."""
    query = """
        INSERT INTO orders (
            id, order_number, user_id, business_id, logistic_id,
            status, total_amount, delivery_address, delivery_city,
            delivery_state, tracking_number, product_name, product_attributes, metadata
        ) VALUES (
            $1::uuid, $2, $3::uuid, $4::uuid, $5::uuid,
            $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14::jsonb
        )
        ON CONFLICT (order_number) DO NOTHING
    """
    async with pool.acquire() as conn:
        for o in data:
            await conn.execute(
                query,
                o["id"],
                o["order_number"],
                o["user_id"],
                o["business_id"],
                o["logistic_id"],
                o["status"],
                o["total_amount"],
                o["delivery_address"],
                o["delivery_city"],
                o["delivery_state"],
                o["tracking_number"],
                o["product_name"],
                o["product_attributes"],
                o["metadata"],
            )
    logger.info("Inserted %d orders", len(data))


async def insert_transactions(pool, data):
    """Insert transactions — skip if id already exists."""
    query = """
        INSERT INTO transactions (
            id, order_id, user_id, business_id, amount,
            payment_method, transaction_reference, bank_name,
            account_number, status, metadata
        ) VALUES (
            $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5,
            $6, $7, $8, $9, $10, $11::jsonb
        )
        ON CONFLICT (id) DO NOTHING
    """
    async with pool.acquire() as conn:
        for t in data:
            await conn.execute(
                query,
                t["id"],
                t["order_id"],
                t["user_id"],
                t["business_id"],
                t["amount"],
                t["payment_method"],
                t["transaction_reference"],
                t["bank_name"],
                t["account_number"],
                t["status"],
                t["metadata"],
            )
    logger.info("Inserted %d transactions", len(data))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    # Seed for reproducible data across runs
    random.seed(42)
    fake.seed_instance(42)

    await init_db()
    pool = await get_db()

    # Generate data
    businesses = generate_businesses()
    vendors = [b for b in businesses if b["business_type"] == "vendor"]
    logistics = [b for b in businesses if b["business_type"] == "logistics"]

    products = generate_products(vendors, per_vendor=10)
    users = generate_users(count=15)
    orders = generate_orders(users, vendors, logistics, count=30)
    transactions = generate_transactions(orders, count=25)

    # Insert in FK order
    await insert_businesses(pool, businesses)
    await insert_products(pool, products)
    await insert_users(pool, users)
    await insert_orders(pool, orders)
    await insert_transactions(pool, transactions)

    # Summary
    print("\n--- Prepopulation Summary ---")
    print(
        f"  Businesses:   {len(businesses)} (vendors={len(vendors)}, logistics={len(logistics)})"
    )
    print(f"  Products:     {len(products)}")
    print(f"  Users:        {len(users)}")
    print(f"  Orders:       {len(orders)}")
    print(f"  Transactions: {len(transactions)}")
    print("-----------------------------\n")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
