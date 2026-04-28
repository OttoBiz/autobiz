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
               created_at, updated_at
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
