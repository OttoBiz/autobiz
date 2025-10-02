"""Unit tests for db/queries/product.py"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from db.models.product import Product
from db.queries.product import (
    check_low_stock,
    create_product,
    delete_product,
    get_business_products,
    get_product_by_id,
    get_product_by_sku,
    search_products,
    update_inventory,
    update_product,
)


@pytest.fixture
def mock_product_data():
    """Fixture providing sample product data."""
    return {
        "id": uuid4(),
        "business_id": uuid4(),
        "sku": "PROD-001",
        "name": "Test Product",
        "description": "A test product description",
        "price": Decimal("99.99"),
        "currency": "USD",
        "category": "Electronics",
        "inventory_count": 50,
        "low_stock_threshold": 10,
        "images": ["https://example.com/image1.jpg"],
        "variants": {"size": ["S", "M", "L"]},
        "metadata": {"brand": "TestBrand"},
        "status": "active",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.fixture
def mock_connection():
    """Fixture providing a mock database connection."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_product(mock_connection, mock_product_data):
    """Test creating a new product."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_product_data)

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        product = await create_product(
            business_id=mock_product_data["business_id"],
            sku=mock_product_data["sku"],
            name=mock_product_data["name"],
            price=mock_product_data["price"],
        )

        assert isinstance(product, Product)
        assert product.name == mock_product_data["name"]
        assert product.sku == mock_product_data["sku"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_product_by_id(mock_connection, mock_product_data):
    """Test getting a product by ID."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_product_data)

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        product = await get_product_by_id(mock_product_data["id"])

        assert product is not None
        assert isinstance(product, Product)
        assert product.id == mock_product_data["id"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_product_by_sku(mock_connection, mock_product_data):
    """Test getting a product by SKU."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_product_data)

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        product = await get_product_by_sku(
            mock_product_data["business_id"], mock_product_data["sku"]
        )

        assert product is not None
        assert product.sku == mock_product_data["sku"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_business_products_no_filters(mock_connection, mock_product_data):
    """Test getting all products for a business without filters."""
    product_data_2 = {**mock_product_data, "id": uuid4(), "sku": "PROD-002"}
    mock_connection.fetch = AsyncMock(return_value=[mock_product_data, product_data_2])

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        products = await get_business_products(mock_product_data["business_id"])

        assert len(products) == 2
        assert all(isinstance(p, Product) for p in products)
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_business_products_with_category(mock_connection, mock_product_data):
    """Test getting products filtered by category."""
    mock_connection.fetch = AsyncMock(return_value=[mock_product_data])

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        products = await get_business_products(
            mock_product_data["business_id"], category="Electronics"
        )

        assert len(products) == 1
        assert products[0].category == "Electronics"
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_business_products_with_status(mock_connection, mock_product_data):
    """Test getting products filtered by status."""
    mock_connection.fetch = AsyncMock(return_value=[mock_product_data])

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        products = await get_business_products(mock_product_data["business_id"], status="active")

        assert len(products) == 1
        assert products[0].status == "active"
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_search_products(mock_connection, mock_product_data):
    """Test searching products by name or description."""
    mock_connection.fetch = AsyncMock(return_value=[mock_product_data])

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        products = await search_products(mock_product_data["business_id"], "Test")

        assert len(products) == 1
        assert products[0].name == mock_product_data["name"]
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_update_product(mock_connection, mock_product_data):
    """Test updating a product."""
    updated_data = {**mock_product_data, "name": "Updated Product"}
    mock_connection.fetchrow = AsyncMock(return_value=updated_data)

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        product = await update_product(mock_product_data["id"], name="Updated Product")

        assert product is not None
        assert product.name == "Updated Product"
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_update_inventory_increment(mock_connection, mock_product_data):
    """Test incrementing product inventory."""
    updated_data = {**mock_product_data, "inventory_count": 60}
    mock_connection.fetchrow = AsyncMock(return_value=updated_data)

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        product = await update_inventory(mock_product_data["id"], 10)

        assert product is not None
        assert product.inventory_count == 60
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_update_inventory_decrement(mock_connection, mock_product_data):
    """Test decrementing product inventory."""
    updated_data = {**mock_product_data, "inventory_count": 45}
    mock_connection.fetchrow = AsyncMock(return_value=updated_data)

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        product = await update_inventory(mock_product_data["id"], -5)

        assert product is not None
        assert product.inventory_count == 45
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_check_low_stock(mock_connection, mock_product_data):
    """Test checking for low stock products."""
    low_stock_product = {**mock_product_data, "inventory_count": 5}
    mock_connection.fetch = AsyncMock(return_value=[low_stock_product])

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        products = await check_low_stock(mock_product_data["business_id"])

        assert len(products) == 1
        assert products[0].inventory_count <= products[0].low_stock_threshold
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_delete_product_success(mock_connection):
    """Test deleting a product successfully."""
    mock_connection.execute = AsyncMock(return_value="DELETE 1")

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_product(uuid4())

        assert result is True
        mock_connection.execute.assert_called_once()


@pytest.mark.asyncio
async def test_delete_product_not_found(mock_connection):
    """Test deleting a non-existent product."""
    mock_connection.execute = AsyncMock(return_value="DELETE 0")

    with patch("db.queries.product.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_product(uuid4())

        assert result is False
        mock_connection.execute.assert_called_once()
