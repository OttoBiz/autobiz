"""Customer query functions."""

from uuid import UUID

from db.connection import get_db_connection
from db.models.customer import Customer


async def create_customer(
    business_id: UUID,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    tags: list[str] | None = None,
    segments: list[str] | None = None,
    lifecycle_stage: str | None = None,
    custom_fields: dict | None = None,
    preferences: dict | None = None,
) -> Customer:
    """Create a new customer."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO customer (
                business_id, name, email, phone, tags, segments,
                lifecycle_stage, custom_fields, preferences
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            business_id,
            name,
            email,
            phone,
            tags or [],
            segments or [],
            lifecycle_stage,
            custom_fields or {},
            preferences or {},
        )
        return Customer(**dict(row))


async def get_customer_by_id(customer_id: UUID) -> Customer | None:
    """Get a customer by ID."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM customer WHERE id = $1", customer_id)
        return Customer(**dict(row)) if row else None


async def find_customer_by_contact(
    business_id: UUID, email: str | None = None, phone: str | None = None
) -> Customer | None:
    """Find a customer by email or phone within a business (uses indexed lookup)."""
    if not email and not phone:
        return None

    async with get_db_connection() as conn:
        if email:
            row = await conn.fetchrow(
                "SELECT * FROM customer WHERE business_id = $1 AND email = $2",
                business_id,
                email,
            )
            if row:
                return Customer(**dict(row))

        if phone:
            row = await conn.fetchrow(
                "SELECT * FROM customer WHERE business_id = $1 AND phone = $2",
                business_id,
                phone,
            )
            if row:
                return Customer(**dict(row))

    return None


async def get_business_customers(
    business_id: UUID, limit: int = 100, offset: int = 0
) -> list[Customer]:
    """Get all customers for a business with pagination."""
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM customer
            WHERE business_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            business_id,
            limit,
            offset,
        )
        return [Customer(**dict(row)) for row in rows]


async def update_customer(customer_id: UUID, **updates) -> Customer | None:
    """Update a customer with arbitrary fields."""
    if not updates:
        return await get_customer_by_id(customer_id)

    # Build dynamic UPDATE query
    set_clauses = ", ".join([f"{key} = ${i + 2}" for i, key in enumerate(updates.keys())])
    values = [customer_id] + list(updates.values())

    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE customer
            SET {set_clauses}, updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            *values,
        )
        return Customer(**dict(row)) if row else None


async def add_customer_tags(customer_id: UUID, new_tags: list[str]) -> Customer | None:
    """Add tags to a customer (appends to existing tags)."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE customer
            SET tags = array(SELECT DISTINCT unnest(tags || $2)),
                updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            customer_id,
            new_tags,
        )
        return Customer(**dict(row)) if row else None


async def delete_customer(customer_id: UUID) -> bool:
    """Delete a customer."""
    async with get_db_connection() as conn:
        result = await conn.execute("DELETE FROM customer WHERE id = $1", customer_id)
        return result == "DELETE 1"
