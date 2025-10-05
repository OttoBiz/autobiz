"""Product catalog and inventory management toolset.

All tools are prefixed with 'catalog_' to prevent naming collisions.
"""

from pydantic_ai import FunctionToolset, RunContext

from agents.deps import AgentDeps
from db.queries.product import get_product_by_sku, search_products

# Create toolset
catalog_toolset = FunctionToolset()


@catalog_toolset.tool
async def product_search(
    ctx: RunContext[AgentDeps],
    query: str,
    limit: int = 5,
) -> str:
    """Search for products by name or description.

    Operation: READ (Simple GET)
    Customer Interaction: No

    Use this tool when:
    - Customer asks about products by name, category, or description
    - Customer wants to browse available items
    - You need product information for recommendations

    Do NOT use if:
    - Customer provides a specific SKU (use inventory_check instead)
    - Customer is asking about order status or account information

    Args:
        query: Search term (product name, category, or description keywords)
        limit: Maximum number of results to return (default: 5, max: 20)

    Returns:
        List of matching products with names, prices, descriptions, and availability.
        Returns message if no products found.
    """
    if not query or len(query.strip()) < 2:
        return "Error: Please provide a search term with at least 2 characters."

    # Cap limit at 20
    limit = min(limit, 20)

    products = await search_products(ctx.deps.business_id, query.strip(), limit=limit)

    if not products:
        return f"No products found matching '{query}'. Please try different search terms or browse our catalog."

    # Format results in natural language
    result_lines = [f"Found {len(products)} product(s) matching '{query}':\n"]

    for i, product in enumerate(products, 1):
        # Stock status
        if product.inventory_count == 0:
            stock_status = "Out of stock"
        elif product.inventory_count <= product.low_stock_threshold:
            stock_status = f"Low stock ({product.inventory_count} available)"
        else:
            stock_status = f"In stock ({product.inventory_count} available)"

        # Price formatting
        price_str = f"{product.currency} {product.price:.2f}"

        # Product description (truncate if too long)
        description = product.description or "No description available"
        if len(description) > 100:
            description = description[:97] + "..."

        result_lines.append(
            f"{i}. {product.name} (SKU: {product.sku})\n"
            f"   Price: {price_str}\n"
            f"   {description}\n"
            f"   Status: {stock_status}\n"
        )

    return "\n".join(result_lines)


@catalog_toolset.tool
async def inventory_check(
    ctx: RunContext[AgentDeps],
    sku: str,
) -> str:
    """Check inventory availability for a specific product by SKU.

    Operation: READ (Simple GET)
    Customer Interaction: No

    Use this tool when:
    - Customer asks if a specific product (by SKU) is in stock
    - You need to verify availability before creating an order
    - Customer provides a product code/SKU directly

    Do NOT use if:
    - Customer doesn't know the SKU (use product_search instead)
    - You need to search by product name or description

    Args:
        sku: Product SKU/code (exact match required)

    Returns:
        Product availability status, price, and stock information.
        Returns message if SKU not found.
    """
    if not sku or not sku.strip():
        return "Error: Please provide a valid product SKU."

    product = await get_product_by_sku(ctx.deps.business_id, sku.strip().upper())

    if not product:
        return f"Product with SKU '{sku}' not found. Please verify the SKU or use product search to find the item."

    if product.status != "active":
        return f"Product '{product.name}' (SKU: {sku}) is currently unavailable."

    # Stock status with thresholds
    if product.inventory_count == 0:
        stock_status = "❌ Out of stock"
        availability_msg = (
            "This product is currently unavailable. Would you like to search for alternatives?"
        )
    elif product.inventory_count <= product.low_stock_threshold:
        stock_status = f"⚠️  Low stock - only {product.inventory_count} units remaining"
        availability_msg = "Limited availability. Order soon to secure your purchase."
    else:
        stock_status = f"✅ In stock - {product.inventory_count} units available"
        availability_msg = "Product is readily available for immediate order."

    # Price formatting
    price_str = f"{product.currency} {product.price:.2f}"

    return f"""Product: {product.name}
SKU: {product.sku}
Price: {price_str}
Category: {product.category or "Uncategorized"}

Inventory Status: {stock_status}

{availability_msg}

{product.description or "No additional product details available."}"""


# Export with prefix
catalog_toolset = catalog_toolset.prefix("catalog_")
