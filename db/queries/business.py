"""Business query functions."""

from uuid import UUID

from db.connection import get_db_connection
from db.models.business import Business


async def create_business(
    name: str,
    slug: str,
    owner_user_id: UUID,
    subscription_plan_id: UUID,
    description: str | None = None,
    industry: str | None = None,
    contact_email: str | None = None,
    logo_url: str | None = None,
    primary_color: str | None = None,
    timezone: str = "UTC",
    currency: str = "USD",
) -> Business:
    """Create a new business."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO businesses (
                name, slug, owner_user_id, subscription_plan_id,
                description, industry, contact_email,
                logo_url, primary_color, timezone, currency
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
            """,
            name,
            slug,
            owner_user_id,
            subscription_plan_id,
            description,
            industry,
            contact_email,
            logo_url,
            primary_color,
            timezone,
            currency,
        )
        return Business(**dict(row))


async def get_business_by_id(business_id: UUID) -> Business | None:
    """Get a business by ID."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM businesses WHERE id = $1", business_id)
        return Business(**dict(row)) if row else None


async def get_business_by_slug(slug: str) -> Business | None:
    """Get a business by slug."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM businesses WHERE slug = $1", slug)
        return Business(**dict(row)) if row else None


async def get_businesses_by_owner(owner_user_id: UUID) -> list[Business]:
    """Get all businesses owned by a user."""
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            "SELECT * FROM businesses WHERE owner_user_id = $1 ORDER BY created_at DESC",
            owner_user_id,
        )
        return [Business(**dict(row)) for row in rows]


async def update_business(business_id: UUID, **updates) -> Business | None:
    """Update a business with arbitrary fields."""
    if not updates:
        return await get_business_by_id(business_id)

    # Build dynamic UPDATE query
    set_clauses = ", ".join([f"{key} = ${i + 2}" for i, key in enumerate(updates.keys())])
    values = [business_id] + list(updates.values())

    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE businesses
            SET {set_clauses}, updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            *values,
        )
        return Business(**dict(row)) if row else None


async def delete_business(business_id: UUID) -> bool:
    """Delete a business."""
    async with get_db_connection() as conn:
        result = await conn.execute("DELETE FROM businesses WHERE id = $1", business_id)
        return result == "DELETE 1"
