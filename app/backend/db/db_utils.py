"""
Database utility functions using asyncpg for async PostgreSQL operations.

Migrated from SQLAlchemy to asyncpg for better async performance and simpler queries.
"""

from typing import Any, Dict, List, Optional

from backend.db.connection import get_db
from backend.logging_config import get_logger

logger = get_logger(__name__)


## PRODUCT FUNCTIONS


async def get_products(
    business_id: str = None,
    name: str = None,
    category: str = None,
    min_price: float = None,
    max_price: float = None,
    exclude_business_id: str = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Search products with optional filters.

    Args:
        business_id: Filter by business ID
        name: Search in product name, description, or tags (case-insensitive)
        category: Filter by category
        min_price: Minimum price filter
        max_price: Maximum price filter
        exclude_business_id: Exclude products from this business (for cross-sell)
        limit: Max results

    Returns:
        List of product dictionaries
    """
    pool = await get_db()

    query = """
        SELECT id, business_id, name, description, price, stock_quantity,
               sku, category, attributes, is_active, is_negotiable,
               floor_price, created_at, updated_at
        FROM products
        WHERE is_active = true
    """
    params = []
    param_count = 1

    if business_id:
        query += f" AND business_id = ${param_count}::uuid"
        params.append(business_id)
        param_count += 1

    if exclude_business_id:
        query += f" AND business_id != ${param_count}::uuid"
        params.append(exclude_business_id)
        param_count += 1

    if name:
        query += f" AND (name ILIKE ${param_count} OR description ILIKE ${param_count} OR category ILIKE ${param_count})"
        params.append(f"%{name}%")
        param_count += 1

    if category:
        query += f" AND category ILIKE ${param_count}"
        params.append(f"%{category}%")
        param_count += 1

    if min_price is not None:
        query += f" AND price >= ${param_count}"
        params.append(min_price)
        param_count += 1

    if max_price is not None:
        query += f" AND price <= ${param_count}"
        params.append(max_price)
        param_count += 1

    query += f" ORDER BY created_at DESC LIMIT ${param_count}"
    params.append(limit)

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
    except Exception:
        logger.error(
            "get_products_failed | business_id=%s name=%s",
            business_id,
            name,
            exc_info=True,
        )
        return []


async def search_products(
    query: str, business_id: str = None, limit: int = 10, offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Search products by query string (case-insensitive pattern matching).

    Args:
        query: Search query string
        business_id: Optional business ID filter
        limit: Maximum results to return
        offset: Pagination offset

    Returns:
        List of product dictionaries ranked by relevance
    """
    pool = await get_db()

    sql_query = """
        SELECT id, business_id, name, description, price, stock_quantity,
               sku, category, attributes, is_active, created_at, updated_at
        FROM products
        WHERE is_active = true
          AND (name ILIKE $1 OR description ILIKE $1 OR category ILIKE $1)
    """

    params = [f"%{query}%"]
    param_count = 2

    if business_id:
        sql_query += f" AND business_id = ${param_count}::uuid"
        params.append(business_id)
        param_count += 1

    sql_query += (
        f" ORDER BY created_at DESC LIMIT ${param_count} OFFSET ${param_count + 1}"
    )
    params.extend([limit, offset])

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql_query, *params)
            return [dict(row) for row in rows]
    except Exception:
        logger.error(
            "search_products_failed | query=%s business_id=%s",
            query,
            business_id,
            exc_info=True,
        )
        return []


async def get_product_by_id(product_id: str) -> Optional[Dict[str, Any]]:
    """Get a product by ID."""
    pool = await get_db()

    query = """
        SELECT id, business_id, name, description, price, stock_quantity,
               sku, category, attributes, is_active, created_at, updated_at
        FROM products
        WHERE id = $1::uuid
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, product_id)
        return dict(row) if row else None


## BUSINESS FUNCTIONS


async def get_business_info(business_id: str) -> Optional[Dict[str, Any]]:
    """
    Get business information by ID.

    Args:
        business_id: Business UUID or social media handle

    Returns:
        Business dictionary or None
    """
    pool = await get_db()

    query = """
        SELECT id, name, business_type, tier, phone_number, email,
               ig_page, facebook_page, twitter_page, tiktok,
               bank_name, bank_account_number, bank_account_name,
               paystack_public_key, paystack_secret_key,
               human_agent_phone, human_agent_email,
               product_schema, created_at, updated_at
        FROM businesses
        WHERE id = $1::uuid
           OR ig_page ILIKE $2
           OR facebook_page ILIKE $2
           OR twitter_page ILIKE $2
           OR tiktok ILIKE $2
           OR phone_number ILIKE $2
           OR email ILIKE $2
        LIMIT 1
    """

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, business_id, business_id)
            return dict(row) if row else None
    except Exception:
        logger.error(
            "get_business_info_failed | business_id=%s", business_id, exc_info=True
        )
        return None


async def get_business_by_handle(handle: str) -> Optional[Dict[str, Any]]:
    """
    Search for business by social media handle or contact info.

    Args:
        handle: Social media handle, phone, or email

    Returns:
        Business dictionary or None
    """
    pool = await get_db()

    query = """
        SELECT id, name, business_type, tier, phone_number, email,
               ig_page, facebook_page, twitter_page, tiktok,
               bank_name, bank_account_number, bank_account_name,
               paystack_public_key, paystack_secret_key,
               human_agent_phone, human_agent_email,
               product_schema, created_at, updated_at
        FROM businesses
        WHERE ig_page ILIKE $1
           OR facebook_page ILIKE $1
           OR twitter_page ILIKE $1
           OR tiktok ILIKE $1
           OR phone_number ILIKE $1
           OR email ILIKE $1
        LIMIT 1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, handle)
        return dict(row) if row else None


async def get_logistics_companies(limit: int = 10) -> List[Dict[str, Any]]:
    """Get logistics companies (business_type='logistics')."""
    pool = await get_db()
    query = """
        SELECT id, name, phone_number, email
        FROM businesses
        WHERE business_type = 'logistics'
        LIMIT $1
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit)
        return [dict(row) for row in rows]


## USER FUNCTIONS


async def get_user_by_phone(phone_number: str) -> Optional[Dict[str, Any]]:
    """Get user by phone number."""
    pool = await get_db()

    query = """
        SELECT id, phone_number, full_name, delivery_address, city, state,
               created_at, updated_at
        FROM users
        WHERE phone_number = $1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, phone_number)
        return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user by ID."""
    pool = await get_db()

    query = """
        SELECT id, phone_number, full_name, delivery_address, city, state,
               created_at, updated_at
        FROM users
        WHERE id = $1::uuid
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, user_id)
        return dict(row) if row else None


async def create_or_update_user(
    phone_number: str,
    full_name: str = None,
    delivery_address: str = None,
    city: str = None,
    state: str = None,
) -> Dict[str, Any] | None:
    """
    Create a new user or update existing user information.

    Args:
        phone_number: User's phone number (required, unique)
        full_name: User's full name
        delivery_address: Delivery address
        city: City
        state: State

    Returns:
        Created or updated user dictionary
    """
    pool = await get_db()

    query = """
        INSERT INTO users (phone_number, full_name, delivery_address, city, state)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (phone_number) DO UPDATE SET
            full_name = COALESCE(EXCLUDED.full_name, users.full_name),
            delivery_address = COALESCE(EXCLUDED.delivery_address, users.delivery_address),
            city = COALESCE(EXCLUDED.city, users.city),
            state = COALESCE(EXCLUDED.state, users.state),
            updated_at = NOW()
        RETURNING id, phone_number, full_name, delivery_address, city, state,
                  created_at, updated_at
    """

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query, phone_number, full_name, delivery_address, city, state
            )
            return dict(row)
    except Exception:
        logger.error(
            "create_or_update_user_failed | phone=%s", phone_number, exc_info=True
        )
        return None


## ORDER FUNCTIONS


async def create_order(
    user_id: str,
    business_id: str,
    total_amount: float,
    quantity: int = 1,
    delivery_address: str = None,
    delivery_city: str = None,
    delivery_state: str = None,
    metadata: dict = None,
) -> Dict[str, Any]:
    """
    Create a new order.

    Args:
        user_id: Customer UUID
        business_id: Vendor UUID
        total_amount: Order total
        quantity: Quantity ordered (default 1)
        delivery_address: Delivery address (optional)
        delivery_city: Delivery city
        delivery_state: Delivery state
        metadata: JSONB metadata (product_name, etc.)

    Returns:
        Created order dictionary
    """
    pool = await get_db()
    import random
    from datetime import datetime

    order_number = (
        f"ORD-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    )
    meta = metadata or {}
    meta.setdefault("quantity", quantity)

    query = """
        INSERT INTO orders (
            order_number, user_id, business_id, total_amount,
            delivery_address, delivery_city, delivery_state,
            status, metadata
        )
        VALUES ($1, $2::uuid, $3::uuid, $4, $5, $6, $7, 'pending', $8)
        RETURNING id, order_number, user_id, business_id, logistic_id,
                  status, total_amount, delivery_address, delivery_city,
                  delivery_state, tracking_number, metadata,
                  created_at, updated_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            query,
            order_number,
            user_id,
            business_id,
            total_amount,
            delivery_address,
            delivery_city,
            delivery_state,
            meta,
        )
        return dict(row)


async def update_order_status(
    order_id: str,
    status: str,
    tracking_number: str = "",
    logistic_id: str = "",
) -> Dict[str, Any] | None:
    """
    Update order status and optionally assign logistics.

    Args:
        order_id: Order UUID
        status: New status (pending, payment_verified, shipped, delivered, cancelled)
        tracking_number: Optional tracking number
        logistic_id: Optional logistics company UUID

    Returns:
        Updated order dictionary
    """
    pool = await get_db()

    query = """
        UPDATE orders
        SET status = $2,
            tracking_number = COALESCE($3, tracking_number),
            logistic_id = COALESCE($4::uuid, logistic_id),
            updated_at = NOW()
        WHERE id = $1::uuid
        RETURNING id, order_number, user_id, business_id, logistic_id,
                  status, total_amount, delivery_address, delivery_city,
                  delivery_state, tracking_number, metadata,
                  created_at, updated_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, order_id, status, tracking_number, logistic_id)
        return dict(row) if row else None


async def get_order_by_id(order_id: str) -> Optional[Dict[str, Any]]:
    """Get order by ID."""
    pool = await get_db()

    query = """
        SELECT id, order_number, user_id, business_id, logistic_id,
               status, total_amount, delivery_address, delivery_city,
               delivery_state, tracking_number, metadata,
               created_at, updated_at
        FROM orders
        WHERE id = $1::uuid
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, order_id)
        return dict(row) if row else None


async def get_order_by_number(order_number: str) -> Optional[Dict[str, Any]]:
    """Get order by order number."""
    pool = await get_db()

    query = """
        SELECT id, order_number, user_id, business_id, logistic_id,
               status, total_amount, delivery_address, delivery_city,
               delivery_state, tracking_number, metadata,
               created_at, updated_at
        FROM orders
        WHERE order_number = $1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, order_number)
        return dict(row) if row else None


async def get_orders_by_user(user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get orders for a user."""
    pool = await get_db()

    query = """
        SELECT id, order_number, user_id, business_id, logistic_id,
               status, total_amount, delivery_address, delivery_city,
               delivery_state, tracking_number, metadata,
               created_at, updated_at
        FROM orders
        WHERE user_id = $1::uuid
        ORDER BY created_at DESC
        LIMIT $2
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, user_id, limit)
        return [dict(row) for row in rows]


async def get_orders_by_business(
    business_id: str, status: str = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """Get orders for a business, optionally filtered by status."""
    pool = await get_db()

    query = """
        SELECT id, order_number, user_id, business_id, logistic_id,
               status, total_amount, delivery_address, delivery_city,
               delivery_state, tracking_number, metadata,
               created_at, updated_at
        FROM orders
        WHERE business_id = $1::uuid
    """

    params = [business_id]
    param_count = 2

    if status:
        query += f" AND status = ${param_count}"
        params.append(status)
        param_count += 1

    query += f" ORDER BY created_at DESC LIMIT ${param_count}"
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]


## TRANSACTION FUNCTIONS


async def create_transaction(
    user_id: str,
    business_id: str,
    amount: float,
    payment_method: str = None,
    order_id: str = None,
    receipt_image_url: str = None,
    transaction_reference: str = None,
    bank_name: str = None,
    account_number: str = None,
    metadata: dict = None,
) -> Dict[str, Any]:
    """
    Create a new transaction record.

    Args:
        user_id: Customer UUID
        business_id: Vendor UUID
        amount: Transaction amount
        payment_method: Payment method (bank_transfer, paystack, cash)
        order_id: Optional order UUID
        receipt_image_url: Optional receipt image URL
        transaction_reference: Optional transaction reference
        bank_name: Optional bank name
        account_number: Optional account number
        metadata: JSONB metadata

    Returns:
        Created transaction dictionary
    """
    pool = await get_db()

    query = """
        INSERT INTO transactions (
            user_id, business_id, amount, payment_method, order_id,
            receipt_image_url, transaction_reference, bank_name,
            account_number, status, metadata
        )
        VALUES (
            $1::uuid, $2::uuid, $3, $4, $5::uuid,
            $6, $7, $8, $9, 'pending', $10
        )
        RETURNING id, order_id, user_id, business_id, status, amount,
                  payment_method, receipt_image_url, transaction_reference,
                  bank_name, account_number, metadata,
                  created_at, verified_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            query,
            user_id,
            business_id,
            amount,
            payment_method,
            order_id,
            receipt_image_url,
            transaction_reference,
            bank_name,
            account_number,
            metadata or {},
        )
        return dict(row)


async def verify_transaction(transaction_id: str) -> Dict[str, Any]:
    """
    Mark a transaction as verified.

    Args:
        transaction_id: Transaction UUID

    Returns:
        Updated transaction dictionary
    """
    pool = await get_db()

    query = """
        UPDATE transactions
        SET status = 'verified',
            verified_at = NOW()
        WHERE id = $1::uuid
        RETURNING id, order_id, user_id, business_id, status, amount,
                  payment_method, receipt_image_url, transaction_reference,
                  bank_name, account_number, metadata,
                  created_at, verified_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, transaction_id)
        return dict(row) if row else None


async def get_pending_transactions(business_id: str) -> List[Dict[str, Any]]:
    """Get all pending transactions for a business."""
    pool = await get_db()

    query = """
        SELECT id, order_id, user_id, business_id, status, amount,
               payment_method, receipt_image_url, transaction_reference,
               bank_name, account_number, metadata,
               created_at, verified_at
        FROM transactions
        WHERE business_id = $1::uuid AND status = 'pending'
        ORDER BY created_at DESC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id)
        return [dict(row) for row in rows]


async def get_transaction_by_id(transaction_id: str) -> Optional[Dict[str, Any]]:
    """Get transaction by ID."""
    pool = await get_db()

    query = """
        SELECT id, order_id, user_id, business_id, status, amount,
               payment_method, receipt_image_url, transaction_reference,
               bank_name, account_number, metadata,
               created_at, verified_at
        FROM transactions
        WHERE id = $1::uuid
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, transaction_id)
        return dict(row) if row else None


async def get_transaction_by_reference(
    transaction_reference: str,
) -> Optional[Dict[str, Any]]:
    """Get transaction by reference number."""
    pool = await get_db()

    query = """
        SELECT id, order_id, user_id, business_id, status, amount,
               payment_method, receipt_image_url, transaction_reference,
               bank_name, account_number, metadata,
               created_at, verified_at
        FROM transactions
        WHERE transaction_reference = $1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, transaction_reference)
        return dict(row) if row else None


## BUSINESS ANALYTICS FUNCTIONS


async def get_business_analytics(
    business_id: str, start_date: str = None, end_date: str = None
) -> Dict[str, Any]:
    """
    Get business analytics including sales, orders, and revenue.

    Args:
        business_id: Business UUID
        start_date: Optional start date (ISO format)
        end_date: Optional end date (ISO format)

    Returns:
        Dictionary with analytics data
    """
    pool = await get_db()

    # Base query filters
    date_filter = ""
    params = [business_id]
    param_count = 2

    if start_date:
        date_filter += f" AND t.created_at >= ${param_count}::timestamp"
        params.append(start_date)
        param_count += 1

    if end_date:
        date_filter += f" AND t.created_at <= ${param_count}::timestamp"
        params.append(end_date)
        param_count += 1

    # Total sales and transactions
    sales_query = f"""
        SELECT
            COALESCE(SUM(t.amount), 0) as total_sales,
            COUNT(t.id) as total_transactions,
            COALESCE(AVG(t.amount), 0) as avg_transaction_value
        FROM transactions t
        WHERE t.business_id = $1::uuid
          AND t.status = 'verified'
          {date_filter}
    """

    # Order statistics
    orders_query = f"""
        SELECT
            COUNT(o.id) as total_orders,
            COALESCE(SUM(o.total_amount), 0) as total_revenue,
            COUNT(CASE WHEN o.status = 'delivered' THEN 1 END) as delivered_orders,
            COUNT(CASE WHEN o.status = 'pending' THEN 1 END) as pending_orders
        FROM orders o
        WHERE o.business_id = $1::uuid
          {date_filter.replace("t.created_at", "o.created_at")}
    """

    # Product performance
    products_query = f"""
        SELECT
            p.name,
            p.id,
            COUNT(DISTINCT o.id) as order_count,
            COALESCE(SUM(o.total_amount), 0) as revenue
        FROM products p
        LEFT JOIN orders o ON o.business_id = p.business_id
          AND o.metadata->>'product_id' = p.id::text
          {date_filter.replace("t.created_at", "o.created_at") if date_filter else ""}
        WHERE p.business_id = $1::uuid AND p.is_active = true
        GROUP BY p.id, p.name
        ORDER BY revenue DESC
        LIMIT 10
    """

    async with pool.acquire() as conn:
        sales_row = await conn.fetchrow(sales_query, *params)
        orders_row = await conn.fetchrow(orders_query, *params)
        products_rows = await conn.fetch(products_query, *params)

        return {
            "business_id": business_id,
            "sales": {
                "total_sales": float(sales_row["total_sales"]),
                "total_transactions": sales_row["total_transactions"],
                "average_transaction_value": float(sales_row["avg_transaction_value"]),
            },
            "orders": {
                "total_orders": orders_row["total_orders"],
                "total_revenue": float(orders_row["total_revenue"]),
                "delivered_orders": orders_row["delivered_orders"],
                "pending_orders": orders_row["pending_orders"],
            },
            "top_products": [dict(row) for row in products_rows],
        }


## INVENTORY FUNCTIONS


async def get_inventory(business_id: str) -> List[Dict[str, Any]]:
    """
    Get inventory information for a business.

    Args:
        business_id: Business UUID

    Returns:
        List of inventory items with stock levels
    """
    pool = await get_db()

    query = """
        SELECT
            id, name, description, price, stock_quantity,
            sku, category, is_active,
            CASE
                WHEN stock_quantity <= 0 THEN 'out_of_stock'
                WHEN stock_quantity <= 10 THEN 'low_stock'
                ELSE 'in_stock'
            END as stock_status
        FROM products
        WHERE business_id = $1::uuid AND is_active = true
        ORDER BY stock_quantity ASC, name ASC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id)
        return [dict(row) for row in rows]


async def update_product_stock(
    product_id: str, stock_quantity: int
) -> Optional[Dict[str, Any]]:
    """
    Update product stock quantity.

    Args:
        product_id: Product UUID
        stock_quantity: New stock quantity

    Returns:
        Updated product dictionary or None if not found
    """
    pool = await get_db()

    query = """
        UPDATE products
        SET stock_quantity = $2,
            updated_at = NOW()
        WHERE id = $1::uuid
        RETURNING id, name, stock_quantity, sku, category, updated_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, product_id, stock_quantity)
        return dict(row) if row else None


async def update_product_price(
    product_id: str, price: Any
) -> Optional[Dict[str, Any]]:
    """Update a product's unit price. `price` may be a Decimal, float, or str."""
    pool = await get_db()

    query = """
        UPDATE products
        SET price = $2,
            updated_at = NOW()
        WHERE id = $1::uuid
        RETURNING id, name, price, sku, updated_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, product_id, price)
        return dict(row) if row else None


async def update_vendor(vendor_id: Any, **fields: Any) -> bool:
    """Update a vendor's record in the `businesses` table.

    Accepted fields: `name`, `phone` (mapped to phone_number), `email`.
    Returns True if a row was updated.
    """
    column_map = {"name": "name", "phone": "phone_number", "email": "email"}
    updates = {column_map[k]: v for k, v in fields.items() if k in column_map}
    if not updates:
        return False

    pool = await get_db()
    set_clause = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(updates))
    query = f"""
        UPDATE businesses
        SET {set_clause},
            updated_at = NOW()
        WHERE id = $1::uuid
    """

    async with pool.acquire() as conn:
        status = await conn.execute(query, str(vendor_id), *updates.values())
    return int(status.rsplit(" ", 1)[-1]) > 0


async def get_low_stock_products(
    business_id: str, threshold: int = 10
) -> List[Dict[str, Any]]:
    """
    Get products with low stock levels.

    Args:
        business_id: Business UUID
        threshold: Stock threshold (default 10)

    Returns:
        List of products with stock below threshold
    """
    pool = await get_db()

    query = """
        SELECT id, name, stock_quantity, sku, category
        FROM products
        WHERE business_id = $1::uuid
          AND stock_quantity <= $2
          AND is_active = true
        ORDER BY stock_quantity ASC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, threshold)
        return [dict(row) for row in rows]


## PRODUCTS API HELPERS (HTTP)
#
# Helpers backing the operator-facing products HTTP API. All queries are
# tenant-scoped via the mandatory `business_id` parameter -- callers (route
# handlers) are expected to pass `ctx.business_id` from the auth context.
#
# Conventions:
# - JSONB columns are passed as JSON strings with `::jsonb` cast (matches
#   `populate.py`; no asyncpg codec is registered on the pool).
# - Cursors are opaque url-safe base64 of `f"{iso_timestamp}|{uuid}"`.
# - Status derivation rules live in `derive_status` so callers can re-derive
#   without round-tripping the DB.

import base64 as _b64
import json as _json
from datetime import datetime as _dt
from typing import Tuple as _Tuple
from uuid import uuid4 as _uuid4


# ---- Exceptions ------------------------------------------------------------


class ProductRepoError(Exception):
    """Base class for product-repo failures."""


class NotFound(ProductRepoError):
    """Product (or related row) not found in the caller's tenant."""


class SkuConflict(ProductRepoError):
    """A product with this SKU already exists for the business."""

    def __init__(self, sku):
        super().__init__(f"sku conflict: {sku}")
        self.sku = sku


class HasReferences(ProductRepoError):
    """Product cannot be deleted because other rows reference it."""

    def __init__(self, **counts):
        super().__init__(f"has references: {counts}")
        self.counts = counts


class InsufficientStock(ProductRepoError):
    """Stock adjustment would drive stock_quantity below zero."""


# ---- Cursor helpers --------------------------------------------------------


def _encode_cursor(ts, row_id) -> str:
    """Encode (timestamp, id) into an opaque url-safe base64 cursor."""
    if isinstance(ts, _dt):
        ts_iso = ts.isoformat()
    else:
        ts_iso = str(ts)
    raw = f"{ts_iso}|{row_id}".encode("utf-8")
    return _b64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(s: str) -> _Tuple[str, str]:
    """Decode opaque cursor back into (iso_timestamp, id). Raises ValueError on
    malformed input."""
    if not s:
        raise ValueError("empty cursor")
    padding = "=" * (-len(s) % 4)
    raw = _b64.urlsafe_b64decode(s + padding).decode("utf-8")
    ts_iso, _, row_id = raw.partition("|")
    if not ts_iso or not row_id:
        raise ValueError("malformed cursor")
    return ts_iso, row_id


# ---- Status derivation -----------------------------------------------------


def derive_status(is_active: bool, stock_quantity: int, reorder_point: int) -> str:
    """Derive a product's display status from its inventory fields.

    Rules (must match the SQL predicates in `list_products_for_api` and
    `get_product_status_totals`):
      - discontinued: NOT is_active
      - out_of_stock: is_active AND stock_quantity == 0
      - low_stock:    is_active AND stock_quantity > 0 AND reorder_point > 0
                      AND stock_quantity <= reorder_point
      - in_stock:     otherwise
    """
    if not is_active:
        return "discontinued"
    if stock_quantity is None or stock_quantity <= 0:
        return "out_of_stock"
    if reorder_point and reorder_point > 0 and stock_quantity <= reorder_point:
        return "low_stock"
    return "in_stock"


# ---- SQL fragments ---------------------------------------------------------

_PRODUCT_COLS = """
    p.id, p.business_id, p.name, p.description, p.price, p.stock_quantity,
    p.sku, p.category, p.attributes, p.is_active, p.is_negotiable,
    p.floor_price, p.reorder_point, p.image_url, p.created_at, p.updated_at
"""

_STATUS_PREDICATES = {
    "discontinued": "(p.is_active = false)",
    "out_of_stock": "(p.is_active = true AND p.stock_quantity = 0)",
    "low_stock": (
        "(p.is_active = true AND p.stock_quantity > 0 "
        "AND p.reorder_point > 0 AND p.stock_quantity <= p.reorder_point)"
    ),
    "in_stock": (
        "(p.is_active = true AND p.stock_quantity > 0 "
        "AND (p.reorder_point = 0 OR p.stock_quantity > p.reorder_point))"
    ),
}


# ---- List / get -----------------------------------------------------------


async def list_products_for_api(
    business_id: str,
    *,
    statuses: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
    search: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
) -> _Tuple[List[Dict[str, Any]], Optional[str]]:
    """List products for the operator dashboard, ordered by updated_at DESC.

    Returns (rows, next_cursor). `next_cursor` is None when there is no next
    page. Each row includes `last_restocked_at` (newest positive-delta
    movement timestamp) via a LATERAL join.
    """
    pool = await get_db()

    where = ["p.business_id = $1::uuid"]
    params: List[Any] = [business_id]
    n = 2

    if statuses:
        clauses = [_STATUS_PREDICATES[s] for s in statuses if s in _STATUS_PREDICATES]
        if clauses:
            where.append("(" + " OR ".join(clauses) + ")")

    if categories:
        where.append(f"p.category = ANY(${n}::text[])")
        params.append(list(categories))
        n += 1

    if search:
        where.append(f"(p.name ILIKE ${n} OR p.sku ILIKE ${n})")
        params.append(f"%{search}%")
        n += 1

    if cursor:
        ts_iso, row_id = _decode_cursor(cursor)
        where.append(
            f"(p.updated_at, p.id) < (${n}::timestamptz, ${n + 1}::uuid)"
        )
        params.append(ts_iso)
        params.append(row_id)
        n += 2

    where_sql = " AND ".join(where)
    fetch_limit = limit + 1
    params.append(fetch_limit)

    query = f"""
        SELECT {_PRODUCT_COLS},
               m.last_restocked_at
        FROM products p
        LEFT JOIN LATERAL (
            SELECT MAX(sm.created_at) AS last_restocked_at
            FROM stock_movements sm
            WHERE sm.product_id = p.id AND sm.delta > 0
        ) m ON true
        WHERE {where_sql}
        ORDER BY p.updated_at DESC, p.id DESC
        LIMIT ${n}
    """

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
    except Exception:
        logger.error(
            "list_products_for_api_failed | business_id=%s statuses=%s categories=%s search=%s",
            business_id,
            statuses,
            categories,
            search,
            exc_info=True,
        )
        raise

    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last["updated_at"], last["id"])
        rows = rows[:limit]
    return [dict(r) for r in rows], next_cursor


async def get_product_for_api(
    business_id: str, product_id: str
) -> Optional[Dict[str, Any]]:
    """Fetch a single product (tenant-scoped) plus its 10 most recent
    stock_movements rows under `recent_movements`. Returns None if missing or
    cross-tenant."""
    pool = await get_db()

    product_query = f"""
        SELECT {_PRODUCT_COLS},
               m.last_restocked_at
        FROM products p
        LEFT JOIN LATERAL (
            SELECT MAX(sm.created_at) AS last_restocked_at
            FROM stock_movements sm
            WHERE sm.product_id = p.id AND sm.delta > 0
        ) m ON true
        WHERE p.id = $1::uuid AND p.business_id = $2::uuid
    """
    movements_query = """
        SELECT id, product_id, business_id, delta, reason, note,
               actor_type, actor_id, created_at
        FROM stock_movements
        WHERE product_id = $1::uuid AND business_id = $2::uuid
        ORDER BY created_at DESC, id DESC
        LIMIT 10
    """

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(product_query, product_id, business_id)
            if not row:
                return None
            movements = await conn.fetch(movements_query, product_id, business_id)
    except Exception:
        logger.error(
            "get_product_for_api_failed | business_id=%s product_id=%s",
            business_id,
            product_id,
            exc_info=True,
        )
        raise

    out = dict(row)
    out["recent_movements"] = [dict(m) for m in movements]
    return out


async def list_stock_movements(
    business_id: str,
    product_id: str,
    *,
    cursor: Optional[str] = None,
    limit: int = 50,
    since=None,
    until=None,
) -> _Tuple[List[Dict[str, Any]], Optional[str]]:
    """Paginate stock_movements for a product. Caller is responsible for
    distinguishing 403 vs 404 -- this helper just filters by business_id."""
    pool = await get_db()

    where = ["product_id = $1::uuid", "business_id = $2::uuid"]
    params: List[Any] = [product_id, business_id]
    n = 3

    if since is not None:
        where.append(f"created_at >= ${n}::timestamptz")
        params.append(since)
        n += 1
    if until is not None:
        where.append(f"created_at <= ${n}::timestamptz")
        params.append(until)
        n += 1

    if cursor:
        ts_iso, row_id = _decode_cursor(cursor)
        where.append(f"(created_at, id) < (${n}::timestamptz, ${n + 1}::uuid)")
        params.append(ts_iso)
        params.append(row_id)
        n += 2

    fetch_limit = limit + 1
    params.append(fetch_limit)

    query = f"""
        SELECT id, product_id, business_id, delta, reason, note,
               actor_type, actor_id, created_at
        FROM stock_movements
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC, id DESC
        LIMIT ${n}
    """

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
    except Exception:
        logger.error(
            "list_stock_movements_failed | business_id=%s product_id=%s",
            business_id,
            product_id,
            exc_info=True,
        )
        raise

    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last["created_at"], last["id"])
        rows = rows[:limit]
    return [dict(r) for r in rows], next_cursor


async def list_categories(business_id: str) -> List[str]:
    """Distinct, non-null categories for a business, alphabetical."""
    pool = await get_db()
    query = """
        SELECT DISTINCT category
        FROM products
        WHERE business_id = $1::uuid AND category IS NOT NULL
        ORDER BY category
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, business_id)
            return [r["category"] for r in rows]
    except Exception:
        logger.error(
            "list_categories_failed | business_id=%s", business_id, exc_info=True
        )
        raise


async def get_product_status_totals(business_id: str) -> Dict[str, int]:
    """Per-status counts for the inventory summary card.

    Returns a dict with keys: in_stock, low_stock, out_of_stock, discontinued.
    """
    pool = await get_db()
    query = f"""
        SELECT
            SUM(CASE WHEN {_STATUS_PREDICATES['in_stock']}    THEN 1 ELSE 0 END) AS in_stock,
            SUM(CASE WHEN {_STATUS_PREDICATES['low_stock']}   THEN 1 ELSE 0 END) AS low_stock,
            SUM(CASE WHEN {_STATUS_PREDICATES['out_of_stock']} THEN 1 ELSE 0 END) AS out_of_stock,
            SUM(CASE WHEN {_STATUS_PREDICATES['discontinued']} THEN 1 ELSE 0 END) AS discontinued
        FROM products p
        WHERE p.business_id = $1::uuid
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, business_id)
    except Exception:
        logger.error(
            "get_product_status_totals_failed | business_id=%s",
            business_id,
            exc_info=True,
        )
        raise
    return {
        "in_stock": int(row["in_stock"] or 0),
        "low_stock": int(row["low_stock"] or 0),
        "out_of_stock": int(row["out_of_stock"] or 0),
        "discontinued": int(row["discontinued"] or 0),
    }


# ---- Mutations -------------------------------------------------------------


_PRODUCT_INSERT_COLS = (
    "name",
    "description",
    "price",
    "stock_quantity",
    "sku",
    "category",
    "attributes",
    "is_active",
    "is_negotiable",
    "floor_price",
    "reorder_point",
    "image_url",
)


async def create_product(
    business_id: str,
    payload: Dict[str, Any],
    *,
    actor_id: Optional[str],
    actor_type: str = "operator",
) -> Dict[str, Any]:
    """Create a product, enforcing per-business SKU uniqueness via
    SELECT-then-INSERT inside a transaction.

    Raises SkuConflict if (business_id, sku) already exists.
    Also writes an initial stock_movements row when stock_quantity > 0.
    """
    pool = await get_db()

    name = payload.get("name")
    description = payload.get("description")
    price = payload.get("price")
    stock_quantity = int(payload.get("stock_quantity") or 0)
    sku = payload.get("sku")
    category = payload.get("category")
    attributes = payload.get("attributes") or {}
    is_active = payload.get("is_active", True)
    is_negotiable = payload.get("is_negotiable", False)
    floor_price = payload.get("floor_price")
    reorder_point = int(payload.get("reorder_point") or 0)
    image_url = payload.get("image_url")

    insert_sql = f"""
        INSERT INTO products (
            business_id, name, description, price, stock_quantity,
            sku, category, attributes, is_active, is_negotiable,
            floor_price, reorder_point, image_url
        )
        VALUES (
            $1::uuid, $2, $3, $4, $5,
            $6, $7, $8::jsonb, $9, $10,
            $11, $12, $13
        )
        RETURNING {_PRODUCT_COLS.replace('p.', '')}
    """
    movement_sql = """
        INSERT INTO stock_movements (
            product_id, business_id, delta, reason, note, actor_type, actor_id
        )
        VALUES ($1::uuid, $2::uuid, $3, 'restock', $4, $5, $6)
        RETURNING created_at
    """

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                if sku:
                    existing = await conn.fetchval(
                        "SELECT 1 FROM products WHERE business_id = $1::uuid AND sku = $2",
                        business_id,
                        sku,
                    )
                    if existing:
                        raise SkuConflict(sku)

                row = await conn.fetchrow(
                    insert_sql,
                    business_id,
                    name,
                    description,
                    price,
                    stock_quantity,
                    sku,
                    category,
                    _json.dumps(attributes),
                    is_active,
                    is_negotiable,
                    floor_price,
                    reorder_point,
                    image_url,
                )

                last_restocked_at = None
                if stock_quantity > 0:
                    mv = await conn.fetchrow(
                        movement_sql,
                        row["id"],
                        business_id,
                        stock_quantity,
                        "initial stock on product creation",
                        actor_type,
                        actor_id,
                    )
                    last_restocked_at = mv["created_at"] if mv else None
    except SkuConflict:
        raise
    except Exception:
        logger.error(
            "create_product_failed | business_id=%s sku=%s",
            business_id,
            sku,
            exc_info=True,
        )
        raise

    out = dict(row)
    out["last_restocked_at"] = last_restocked_at
    return out


async def patch_product(
    business_id: str,
    product_id: str,
    payload: Dict[str, Any],
    *,
    actor_id: Optional[str],
) -> Dict[str, Any]:
    """Partial update. `payload` should be a `model_dump(exclude_unset=True)`
    dict from ProductPatch. If `stock_quantity` is present, a stock_movements
    row is written using the popped `stock_change_reason` value."""
    pool = await get_db()

    payload = dict(payload)  # don't mutate caller's dict
    stock_change_reason = payload.pop("stock_change_reason", None)

    updatable = {
        "name",
        "description",
        "price",
        "stock_quantity",
        "sku",
        "category",
        "attributes",
        "is_active",
        "is_negotiable",
        "floor_price",
        "reorder_point",
        "image_url",
    }
    fields = {k: v for k, v in payload.items() if k in updatable}

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    f"""
                    SELECT {_PRODUCT_COLS.replace('p.', '')}
                    FROM products p
                    WHERE p.id = $1::uuid AND p.business_id = $2::uuid
                    FOR UPDATE
                    """,
                    product_id,
                    business_id,
                )
                if not current:
                    raise NotFound(f"product {product_id} not found")

                # SKU conflict check when changing sku
                new_sku = fields.get("sku")
                if new_sku and new_sku != current["sku"]:
                    conflict = await conn.fetchval(
                        "SELECT 1 FROM products WHERE business_id=$1::uuid AND sku=$2 AND id<>$3::uuid",
                        business_id,
                        new_sku,
                        product_id,
                    )
                    if conflict:
                        raise SkuConflict(new_sku)

                stock_delta = 0
                wrote_movement_at = None
                if "stock_quantity" in fields:
                    new_q = int(fields["stock_quantity"])
                    stock_delta = new_q - int(current["stock_quantity"])

                set_parts = []
                params: List[Any] = []
                n = 1
                for k, v in fields.items():
                    if k == "attributes":
                        set_parts.append(f"{k} = ${n}::jsonb")
                        params.append(_json.dumps(v or {}))
                    else:
                        set_parts.append(f"{k} = ${n}")
                        params.append(v)
                    n += 1
                set_parts.append("updated_at = NOW()")

                if set_parts:
                    update_sql = f"""
                        UPDATE products
                        SET {', '.join(set_parts)}
                        WHERE id = ${n}::uuid AND business_id = ${n + 1}::uuid
                        RETURNING {_PRODUCT_COLS.replace('p.', '')}
                    """
                    params.append(product_id)
                    params.append(business_id)
                    updated = await conn.fetchrow(update_sql, *params)
                else:
                    updated = current

                if "stock_quantity" in fields and stock_delta != 0:
                    mv = await conn.fetchrow(
                        """
                        INSERT INTO stock_movements (
                            product_id, business_id, delta, reason, note,
                            actor_type, actor_id
                        )
                        VALUES ($1::uuid, $2::uuid, $3, $4, $5, 'operator', $6)
                        RETURNING created_at
                        """,
                        product_id,
                        business_id,
                        stock_delta,
                        stock_change_reason or "manual_set",
                        None,
                        actor_id,
                    )
                    wrote_movement_at = mv["created_at"] if mv else None
    except (NotFound, SkuConflict):
        raise
    except Exception:
        logger.error(
            "patch_product_failed | business_id=%s product_id=%s",
            business_id,
            product_id,
            exc_info=True,
        )
        raise

    out = dict(updated)
    # last_restocked_at: prefer freshly-written positive movement; else look up
    if wrote_movement_at and stock_delta > 0:
        out["last_restocked_at"] = wrote_movement_at
    else:
        pool2 = await get_db()
        async with pool2.acquire() as conn:
            ts = await conn.fetchval(
                "SELECT MAX(created_at) FROM stock_movements WHERE product_id=$1::uuid AND delta>0",
                product_id,
            )
        out["last_restocked_at"] = ts
    return out


async def delete_product(business_id: str, product_id: str) -> Dict[str, Any]:
    """Hard delete. Refuses if any orders or transactions reference the
    product (orders via `metadata->>'product_id'`, transactions via order_id
    -> orders.metadata).

    Note: there is no `order_items` table in this schema; products are
    referenced only loosely via orders.metadata JSON. We count those.
    """
    pool = await get_db()

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval(
                    "SELECT 1 FROM products WHERE id=$1::uuid AND business_id=$2::uuid",
                    product_id,
                    business_id,
                )
                if not exists:
                    raise NotFound(f"product {product_id} not found")

                orders_count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM orders
                    WHERE business_id = $2::uuid
                      AND metadata->>'product_id' = $1::text
                    """,
                    product_id,
                    business_id,
                )
                tx_count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM transactions t
                    JOIN orders o ON o.id = t.order_id
                    WHERE t.business_id = $2::uuid
                      AND o.metadata->>'product_id' = $1::text
                    """,
                    product_id,
                    business_id,
                )
                orders_count = int(orders_count or 0)
                tx_count = int(tx_count or 0)
                if orders_count or tx_count:
                    raise HasReferences(orders=orders_count, transactions=tx_count)

                # stock_movements has ON DELETE CASCADE per migration 013, so
                # the products DELETE will clean those up automatically.
                await conn.execute(
                    "DELETE FROM products WHERE id=$1::uuid AND business_id=$2::uuid",
                    product_id,
                    business_id,
                )
    except (NotFound, HasReferences):
        raise
    except Exception:
        logger.error(
            "delete_product_failed | business_id=%s product_id=%s",
            business_id,
            product_id,
            exc_info=True,
        )
        raise

    return {"deleted": True}


async def adjust_stock(
    business_id: str,
    product_id: str,
    delta: int,
    reason: str,
    note: Optional[str],
    *,
    actor_id: Optional[str],
    actor_type: str = "operator",
) -> _Tuple[Dict[str, Any], Dict[str, Any]]:
    """Atomically apply a stock delta and write a stock_movements row.

    Raises NotFound (product missing/cross-tenant) or InsufficientStock (the
    delta would drive stock_quantity negative).
    """
    pool = await get_db()

    update_sql = f"""
        UPDATE products
        SET stock_quantity = stock_quantity + $3,
            updated_at = NOW()
        WHERE id = $1::uuid AND business_id = $2::uuid
          AND stock_quantity + $3 >= 0
        RETURNING {_PRODUCT_COLS.replace('p.', '')}
    """
    movement_sql = """
        INSERT INTO stock_movements (
            product_id, business_id, delta, reason, note, actor_type, actor_id
        )
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7)
        RETURNING id, product_id, business_id, delta, reason, note,
                  actor_type, actor_id, created_at
    """

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    update_sql, product_id, business_id, delta
                )
                if not row:
                    # Distinguish NotFound vs InsufficientStock
                    exists = await conn.fetchval(
                        "SELECT 1 FROM products WHERE id=$1::uuid AND business_id=$2::uuid",
                        product_id,
                        business_id,
                    )
                    if not exists:
                        raise NotFound(f"product {product_id} not found")
                    raise InsufficientStock(
                        f"delta {delta} would drive stock below zero"
                    )

                mv = await conn.fetchrow(
                    movement_sql,
                    product_id,
                    business_id,
                    delta,
                    reason,
                    note,
                    actor_type,
                    actor_id,
                )
    except (NotFound, InsufficientStock):
        raise
    except Exception:
        logger.error(
            "adjust_stock_failed | business_id=%s product_id=%s delta=%s",
            business_id,
            product_id,
            delta,
            exc_info=True,
        )
        raise

    return dict(row), dict(mv)


async def get_open_order_count(business_id: str, product_id: str) -> int:
    """Count orders referencing this product whose status is not terminal.

    Used to log a warning when an operator discontinues a product that still
    has live orders. Status set is derived from observed values in the orders
    table; terminal statuses are 'delivered' and 'cancelled'.
    """
    pool = await get_db()
    query = """
        SELECT COUNT(*)
        FROM orders
        WHERE business_id = $1::uuid
          AND metadata->>'product_id' = $2::text
          AND status NOT IN ('delivered', 'cancelled')
    """
    try:
        async with pool.acquire() as conn:
            n = await conn.fetchval(query, business_id, product_id)
            return int(n or 0)
    except Exception:
        logger.error(
            "get_open_order_count_failed | business_id=%s product_id=%s",
            business_id,
            product_id,
            exc_info=True,
        )
        raise


# ---- Bulk import jobs ------------------------------------------------------


async def create_bulk_import_job(business_id: str) -> str:
    """Create a queued bulk_import_jobs row and return its `imp_<hex>` id."""
    pool = await get_db()
    job_id = "imp_" + _uuid4().hex
    query = """
        INSERT INTO bulk_import_jobs (id, business_id, status)
        VALUES ($1, $2::uuid, 'queued')
        RETURNING id
    """
    try:
        async with pool.acquire() as conn:
            await conn.fetchval(query, job_id, business_id)
    except Exception:
        logger.error(
            "create_bulk_import_job_failed | business_id=%s", business_id, exc_info=True
        )
        raise
    return job_id


async def update_bulk_import_job(
    job_id: str,
    business_id: str,
    *,
    status: Optional[str] = None,
    total_rows: Optional[int] = None,
    processed: Optional[int] = None,
    created: Optional[int] = None,
    updated: Optional[int] = None,
    errors: Optional[Any] = None,
) -> Dict[str, Any]:
    """Patch a bulk_import_jobs row (tenant-scoped). Touches updated_at."""
    pool = await get_db()

    set_parts: List[str] = []
    params: List[Any] = []
    n = 1
    if status is not None:
        set_parts.append(f"status = ${n}")
        params.append(status)
        n += 1
    if total_rows is not None:
        set_parts.append(f"total_rows = ${n}")
        params.append(total_rows)
        n += 1
    if processed is not None:
        set_parts.append(f"processed = ${n}")
        params.append(processed)
        n += 1
    if created is not None:
        set_parts.append(f"created = ${n}")
        params.append(created)
        n += 1
    if updated is not None:
        set_parts.append(f"updated = ${n}")
        params.append(updated)
        n += 1
    if errors is not None:
        set_parts.append(f"errors = ${n}::jsonb")
        params.append(_json.dumps(errors))
        n += 1
    set_parts.append("updated_at = NOW()")

    query = f"""
        UPDATE bulk_import_jobs
        SET {', '.join(set_parts)}
        WHERE id = ${n} AND business_id = ${n + 1}::uuid
        RETURNING id, business_id, status, total_rows, processed, created,
                  updated, errors, created_at, updated_at
    """
    params.append(job_id)
    params.append(business_id)

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
    except Exception:
        logger.error(
            "update_bulk_import_job_failed | business_id=%s job_id=%s",
            business_id,
            job_id,
            exc_info=True,
        )
        raise
    if not row:
        raise NotFound(f"bulk_import_job {job_id} not found")
    return dict(row)


async def get_bulk_import_job(
    business_id: str, job_id: str
) -> Optional[Dict[str, Any]]:
    """Fetch a bulk_import_jobs row, tenant-scoped. Returns None if missing."""
    pool = await get_db()
    query = """
        SELECT id, business_id, status, total_rows, processed, created,
               updated, errors, created_at, updated_at
        FROM bulk_import_jobs
        WHERE id = $1 AND business_id = $2::uuid
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, job_id, business_id)
            return dict(row) if row else None
    except Exception:
        logger.error(
            "get_bulk_import_job_failed | business_id=%s job_id=%s",
            business_id,
            job_id,
            exc_info=True,
        )
        raise


# ---- Bulk update -----------------------------------------------------------


async def bulk_update_products(
    business_id: str,
    filter_dict: Dict[str, Any],
    patch_dict: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Apply a bulk patch to products matching `filter_dict`.

    Defense in depth: stock_quantity must NEVER appear in patch_dict (route
    layer enforces this via the BulkUpdatePatch schema).

    Filter keys: category, is_active, sku_in (list).
    Patch keys: price_multiplier, price_delta (kobo), reorder_point,
    is_active, category.

    Returns {"matched_rows": N, "updated_rows": M}. When dry_run, updated_rows
    is always 0.
    """
    assert "stock_quantity" not in patch_dict, (
        "stock_quantity is not allowed in bulk_update_products"
    )

    pool = await get_db()

    where = ["business_id = $1::uuid"]
    params: List[Any] = [business_id]
    n = 2

    if "category" in filter_dict and filter_dict["category"] is not None:
        where.append(f"category = ${n}")
        params.append(filter_dict["category"])
        n += 1
    if "is_active" in filter_dict and filter_dict["is_active"] is not None:
        where.append(f"is_active = ${n}")
        params.append(bool(filter_dict["is_active"]))
        n += 1
    if "sku_in" in filter_dict and filter_dict["sku_in"]:
        where.append(f"sku = ANY(${n}::text[])")
        params.append(list(filter_dict["sku_in"]))
        n += 1

    where_sql = " AND ".join(where)

    try:
        async with pool.acquire() as conn:
            matched = await conn.fetchval(
                f"SELECT COUNT(*) FROM products WHERE {where_sql}", *params
            )
            matched = int(matched or 0)

            if dry_run or not patch_dict:
                return {"matched_rows": matched, "updated_rows": 0}

            set_parts: List[str] = []
            # price_multiplier and price_delta both modify price; spec allows
            # one or the other (route layer should enforce mutual exclusion).
            if "price_multiplier" in patch_dict and patch_dict["price_multiplier"] is not None:
                set_parts.append(f"price = ROUND(price * ${n}::numeric, 2)")
                params.append(patch_dict["price_multiplier"])
                n += 1
            if "price_delta" in patch_dict and patch_dict["price_delta"] is not None:
                # price_delta is in kobo -> divide by 100 to get naira
                set_parts.append(f"price = price + (${n}::numeric / 100)")
                params.append(patch_dict["price_delta"])
                n += 1
            if "reorder_point" in patch_dict and patch_dict["reorder_point"] is not None:
                set_parts.append(f"reorder_point = ${n}")
                params.append(int(patch_dict["reorder_point"]))
                n += 1
            if "is_active" in patch_dict and patch_dict["is_active"] is not None:
                set_parts.append(f"is_active = ${n}")
                params.append(bool(patch_dict["is_active"]))
                n += 1
            if "category" in patch_dict and patch_dict["category"] is not None:
                set_parts.append(f"category = ${n}")
                params.append(patch_dict["category"])
                n += 1

            if not set_parts:
                return {"matched_rows": matched, "updated_rows": 0}

            set_parts.append("updated_at = NOW()")

            update_sql = f"""
                UPDATE products
                SET {', '.join(set_parts)}
                WHERE {where_sql}
                RETURNING id
            """
            rows = await conn.fetch(update_sql, *params)
    except Exception:
        logger.error(
            "bulk_update_products_failed | business_id=%s filter=%s patch=%s",
            business_id,
            filter_dict,
            patch_dict,
            exc_info=True,
        )
        raise

    return {"matched_rows": matched, "updated_rows": len(rows)}
