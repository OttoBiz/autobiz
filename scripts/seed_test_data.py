"""Seed the database with synthetic test data for agent testing.

This script creates:
- A test business
- Sample products in different categories
- Test customers with various profiles
- A conversation thread

Run with:
    make seed-db
    # or directly:
    uv run python scripts/seed_test_data.py
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from db.connection import get_pool, init_db_pool


async def seed_business(conn) -> UUID:
    """Create a test business."""
    business_id = uuid4()

    await conn.execute(
        """
        INSERT INTO business (
            id, name, email, phone, address, business_type,
            website, logo_url, timezone, currency, status,
            created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
        )
        ON CONFLICT (id) DO NOTHING
        """,
        business_id,
        "Tech Store Demo",
        "demo@techstore.example.com",
        "+1-555-0100",
        "123 Tech Street, San Francisco, CA 94102",
        "e-commerce",
        "https://techstore.example.com",
        "https://via.placeholder.com/150",
        "America/Los_Angeles",
        "USD",
        "active",
        datetime.now(),
        datetime.now(),
    )

    print(f"✅ Created business: Tech Store Demo ({business_id})")
    return business_id


async def seed_products(conn, business_id: UUID) -> list[dict]:
    """Create sample products."""
    products = [
        {
            "id": uuid4(),
            "sku": "LAPTOP-001",
            "name": "MacBook Pro 16-inch",
            "description": "Powerful laptop with M3 Max chip, 36GB RAM, 1TB SSD. Perfect for developers and creators.",
            "price": Decimal("2499.00"),
            "category": "Laptops",
            "inventory_count": 15,
            "low_stock_threshold": 5,
        },
        {
            "id": uuid4(),
            "sku": "LAPTOP-002",
            "name": "Dell XPS 15",
            "description": "High-performance laptop with Intel i9, 32GB RAM, 1TB SSD. Great for business professionals.",
            "price": Decimal("1899.00"),
            "category": "Laptops",
            "inventory_count": 8,
            "low_stock_threshold": 5,
        },
        {
            "id": uuid4(),
            "sku": "LAPTOP-003",
            "name": "ThinkPad X1 Carbon",
            "description": "Ultra-portable business laptop with Intel i7, 16GB RAM, 512GB SSD.",
            "price": Decimal("1499.00"),
            "category": "Laptops",
            "inventory_count": 3,  # Low stock
            "low_stock_threshold": 5,
        },
        {
            "id": uuid4(),
            "sku": "MONITOR-001",
            "name": "LG UltraWide 34-inch",
            "description": "34-inch curved monitor with 3440x1440 resolution. Perfect for multitasking.",
            "price": Decimal("699.00"),
            "category": "Monitors",
            "inventory_count": 25,
            "low_stock_threshold": 10,
        },
        {
            "id": uuid4(),
            "sku": "KEYBOARD-001",
            "name": "Mechanical Keyboard RGB",
            "description": "Cherry MX switches, RGB backlight, aluminum frame. Great for typing and gaming.",
            "price": Decimal("149.00"),
            "category": "Accessories",
            "inventory_count": 50,
            "low_stock_threshold": 20,
        },
        {
            "id": uuid4(),
            "sku": "MOUSE-001",
            "name": "Wireless Gaming Mouse",
            "description": "High-precision wireless mouse with 16,000 DPI sensor. 70-hour battery life.",
            "price": Decimal("79.00"),
            "category": "Accessories",
            "inventory_count": 0,  # Out of stock
            "low_stock_threshold": 15,
        },
        {
            "id": uuid4(),
            "sku": "HEADPHONE-001",
            "name": "Noise-Cancelling Headphones",
            "description": "Premium wireless headphones with active noise cancellation. 30-hour battery.",
            "price": Decimal("299.00"),
            "category": "Audio",
            "inventory_count": 40,
            "low_stock_threshold": 15,
        },
    ]

    for product in products:
        await conn.execute(
            """
            INSERT INTO product (
                id, business_id, sku, name, description, price, currency,
                category, inventory_count, low_stock_threshold, status,
                created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
            )
            ON CONFLICT (id) DO NOTHING
            """,
            product["id"],
            business_id,
            product["sku"],
            product["name"],
            product["description"],
            product["price"],
            "USD",
            product["category"],
            product["inventory_count"],
            product["low_stock_threshold"],
            "active",
            datetime.now(),
            datetime.now(),
        )

    print(f"✅ Created {len(products)} products")
    return products


async def seed_customers(conn, business_id: UUID) -> list[dict]:
    """Create sample customers."""
    customers = [
        {
            "id": uuid4(),
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+1-555-0101",
            "tags": ["vip", "returning"],
            "segments": ["high-value"],
            "lifecycle_stage": "active",
            "customer_value_score": 85,
            "notes": "Great customer, always polite. Prefers premium products.",
        },
        {
            "id": uuid4(),
            "name": "Jane Smith",
            "email": "jane.smith@example.com",
            "phone": "+1-555-0102",
            "tags": ["new-customer"],
            "segments": ["potential"],
            "lifecycle_stage": "new",
            "customer_value_score": 50,
            "notes": "First-time buyer, interested in laptops.",
        },
        {
            "id": uuid4(),
            "name": "Bob Wilson",
            "email": "bob.wilson@techcorp.com",
            "phone": "+1-555-0103",
            "tags": ["enterprise", "vip"],
            "segments": ["enterprise", "high-value"],
            "lifecycle_stage": "active",
            "customer_value_score": 95,
            "notes": "IT Manager at TechCorp. Bulk orders for office equipment.",
        },
        {
            "id": uuid4(),
            "name": "Alice Johnson",
            "email": "alice.j@example.com",
            "phone": None,
            "tags": ["support-needed"],
            "segments": [],
            "lifecycle_stage": "at-risk",
            "customer_value_score": 30,
            "notes": "Had issues with previous order. Needs follow-up.",
        },
    ]

    for customer in customers:
        await conn.execute(
            """
            INSERT INTO customer (
                id, business_id, name, email, phone, tags, segments,
                lifecycle_stage, customer_value_score, notes,
                created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (id) DO NOTHING
            """,
            customer["id"],
            business_id,
            customer["name"],
            customer["email"],
            customer["phone"],
            customer["tags"],
            customer["segments"],
            customer["lifecycle_stage"],
            customer["customer_value_score"],
            customer["notes"],
            datetime.now(),
            datetime.now(),
        )

    print(f"✅ Created {len(customers)} customers")
    return customers


async def seed_conversation(conn, business_id: UUID, customer_id: UUID) -> UUID:
    """Create a sample conversation."""
    conversation_id = uuid4()

    await conn.execute(
        """
        INSERT INTO conversation (
            id, customer_id, business_id, channel, status,
            created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (id) DO NOTHING
        """,
        conversation_id,
        customer_id,
        business_id,
        "web_chat",
        "active",
        datetime.now(),
        datetime.now(),
    )

    # Add a couple of messages
    messages = [
        {
            "content": "Hi! I'm looking for a good laptop for software development.",
            "sender_type": "customer",
            "is_internal": False,
        },
        {
            "content": "[Agent searched for laptops and found 3 options]",
            "sender_type": "agent",
            "is_internal": True,
        },
    ]

    for msg in messages:
        await conn.execute(
            """
            INSERT INTO message (
                id, conversation_id, sender_type, content, is_internal,
                created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            uuid4(),
            conversation_id,
            msg["sender_type"],
            msg["content"],
            msg["is_internal"],
            datetime.now(),
        )

    print(f"✅ Created conversation with messages ({conversation_id})")
    return conversation_id


async def main():
    """Seed the database with test data."""
    print("🌱 Seeding test data...")
    print("=" * 60)
    print()

    try:
        # Initialize database pool
        await init_db_pool()
        pool = get_pool()

        async with pool.acquire() as conn:
            # Seed in order of dependencies
            business_id = await seed_business(conn)
            products = await seed_products(conn, business_id)
            customers = await seed_customers(conn, business_id)

            # Create a conversation for the first customer
            if customers:
                conversation_id = await seed_conversation(conn, business_id, customers[0]["id"])

        print()
        print("=" * 60)
        print("✅ Database seeded successfully!")
        print()
        print("📊 Summary:")
        print(f"   • Business ID: {business_id}")
        print(f"   • Products: {len(products)} (including out-of-stock and low-stock items)")
        print(f"   • Customers: {len(customers)} (with various profiles)")
        print(f"   • Sample conversation created")
        print()
        print("🎯 Try the examples:")
        print("   uv run python -m examples.simple_agent")
        print()
        print("🔍 Test queries:")
        print('   • "What laptops do you have?"')
        print('   • "Is LAPTOP-003 in stock?"')
        print('   • "Look up customer john@example.com"')
        print('   • "Check inventory for MOUSE-001"')

    except Exception as e:
        print(f"❌ Error seeding database: {e}")
        print()
        print("💡 Make sure:")
        print("   1. Database is running")
        print("   2. DATABASE_URL is set in .env")
        print("   3. Schema is set up: make db-setup")
        print()
        raise


if __name__ == "__main__":
    asyncio.run(main())
