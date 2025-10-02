"""Product query functions."""

from decimal import Decimal
from uuid import UUID

from db.connection import get_db_connection
from db.models.product import Product


async def create_product(
    business_id: UUID,
    sku: str,
    name: str,
    price: Decimal,
    description: str | None = None,
    currency: str = "USD",
    category: str | None = None,
    inventory_count: int = 0,
    low_stock_threshold: int = 10,
    images: list | None = None,
    variants: dict | None = None,
    metadata: dict | None = None,
    status: str = "active",
) -> Product:
    """Create a new product."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO product (
                business_id, sku, name, description, price, currency, category,
                inventory_count, low_stock_threshold, images, variants, metadata, status
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING *
            """,
            business_id,
            sku,
            name,
            description,
            price,
            currency,
            category,
            inventory_count,
            low_stock_threshold,
            images or [],
            variants or {},
            metadata or {},
            status,
        )
        return Product(**dict(row))


async def get_product_by_id(product_id: UUID) -> Product | None:
    """Get a product by ID."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM product WHERE id = $1", product_id)
        return Product(**dict(row)) if row else None


async def get_product_by_sku(business_id: UUID, sku: str) -> Product | None:
    """Get a product by SKU within a business (uses indexed lookup)."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM product WHERE business_id = $1 AND sku = $2",
            business_id,
            sku,
        )
        return Product(**dict(row)) if row else None


async def get_business_products(
    business_id: UUID,
    category: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Product]:
    """Get all products for a business with optional filters."""
    async with get_db_connection() as conn:
        if category and status:
            rows = await conn.fetch(
                """
                SELECT * FROM product
                WHERE business_id = $1 AND category = $2 AND status = $3
                ORDER BY created_at DESC
                LIMIT $4 OFFSET $5
                """,
                business_id,
                category,
                status,
                limit,
                offset,
            )
        elif category:
            rows = await conn.fetch(
                """
                SELECT * FROM product
                WHERE business_id = $1 AND category = $2
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4
                """,
                business_id,
                category,
                limit,
                offset,
            )
        elif status:
            rows = await conn.fetch(
                """
                SELECT * FROM product
                WHERE business_id = $1 AND status = $2
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4
                """,
                business_id,
                status,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM product
                WHERE business_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                business_id,
                limit,
                offset,
            )
        return [Product(**dict(row)) for row in rows]


async def search_products(business_id: UUID, query: str, limit: int = 50) -> list[Product]:
    """Search products by name or description (text search)."""
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM product
            WHERE business_id = $1
              AND (name ILIKE $2 OR description ILIKE $2)
              AND status = 'active'
            ORDER BY name
            LIMIT $3
            """,
            business_id,
            f"%{query}%",
            limit,
        )
        return [Product(**dict(row)) for row in rows]


async def update_product(product_id: UUID, **updates) -> Product | None:
    """Update a product with arbitrary fields."""
    if not updates:
        return await get_product_by_id(product_id)

    # Build dynamic UPDATE query
    set_clauses = ", ".join([f"{key} = ${i + 2}" for i, key in enumerate(updates.keys())])
    values = [product_id] + list(updates.values())

    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE product
            SET {set_clauses}, updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            *values,
        )
        return Product(**dict(row)) if row else None


async def update_inventory(product_id: UUID, quantity_change: int) -> Product | None:
    """Update product inventory by incrementing/decrementing the count."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE product
            SET inventory_count = inventory_count + $2,
                updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            product_id,
            quantity_change,
        )
        return Product(**dict(row)) if row else None


async def check_low_stock(business_id: UUID) -> list[Product]:
    """Get all products below their low stock threshold."""
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM product
            WHERE business_id = $1
              AND inventory_count <= low_stock_threshold
              AND status = 'active'
            ORDER BY inventory_count ASC
            """,
            business_id,
        )
        return [Product(**dict(row)) for row in rows]


async def delete_product(product_id: UUID) -> bool:
    """Delete a product."""
    async with get_db_connection() as conn:
        result = await conn.execute("DELETE FROM product WHERE id = $1", product_id)
        return result == "DELETE 1"
