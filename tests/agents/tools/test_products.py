"""Unit tests for product search and inventory tools."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from agents.deps import AgentDeps
from db.models.product import Product


@pytest.fixture
def mock_products():
    """Fixture providing sample products."""
    business_id = uuid4()
    return [
        Product(
            id=uuid4(),
            business_id=business_id,
            sku="PROD-001",
            name="Test Product 1",
            description="A great product for testing",
            price=Decimal("99.99"),
            currency="USD",
            category="Electronics",
            inventory_count=50,
            low_stock_threshold=10,
            images=["https://example.com/image1.jpg"],
            variants={},
            metadata={},
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        Product(
            id=uuid4(),
            business_id=business_id,
            sku="PROD-002",
            name="Test Product 2",
            description="Another great product",
            price=Decimal("149.99"),
            currency="USD",
            category="Electronics",
            inventory_count=5,  # Low stock
            low_stock_threshold=10,
            images=[],
            variants={},
            metadata={},
            status="active",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
    ]


@pytest.fixture
def out_of_stock_product():
    """Fixture providing an out-of-stock product."""
    return Product(
        id=uuid4(),
        business_id=uuid4(),
        sku="PROD-OUT",
        name="Out of Stock Product",
        description="Currently unavailable",
        price=Decimal("199.99"),
        currency="USD",
        category="Electronics",
        inventory_count=0,
        low_stock_threshold=10,
        images=[],
        variants={},
        metadata={},
        status="active",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def agent_deps():
    """Fixture providing agent dependencies."""
    return AgentDeps(
        business_id=uuid4(),
        conversation_id=uuid4(),
        customer_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_product_search_formats_response(mock_products, agent_deps):
    """Test product_search formats response in natural language."""
    from agents.toolsets.catalog import product_search

    with patch("agents.toolsets.catalog.search_products") as mock_search:
        mock_search.return_value = mock_products

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await product_search(ctx, query="test")

        # Verify response contains product information
        assert "Test Product 1" in result
        assert "PROD-001" in result
        assert "99.99" in result
        assert "In stock" in result
        assert "Low stock" in result  # For product 2


@pytest.mark.asyncio
async def test_product_search_no_results(agent_deps):
    """Test product_search when no products match."""
    from agents.toolsets.catalog import product_search

    with patch("agents.toolsets.catalog.search_products") as mock_search:
        mock_search.return_value = []

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await product_search(ctx, query="nonexistent")

        assert "No products found" in result
        assert "nonexistent" in result


@pytest.mark.asyncio
async def test_product_search_validates_query(agent_deps):
    """Test product_search requires valid query."""
    from agents.toolsets.catalog import product_search

    ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())

    # Empty query
    result = await product_search(ctx, query="")
    assert "Error" in result

    # Very short query
    result = await product_search(ctx, query="a")
    assert "Error" in result


@pytest.mark.asyncio
async def test_product_search_respects_limit(mock_products, agent_deps):
    """Test product_search respects limit parameter."""
    from agents.toolsets.catalog import product_search

    with patch("agents.toolsets.catalog.search_products") as mock_search:
        mock_search.return_value = mock_products

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await product_search(ctx, query="test", limit=1)

        # Verify limit was passed to search function
        call_args = mock_search.call_args
        assert call_args.kwargs["limit"] == 1 or call_args.args[2] == 1


@pytest.mark.asyncio
async def test_product_search_caps_limit_at_20(mock_products, agent_deps):
    """Test product_search caps limit at 20."""
    from agents.toolsets.catalog import product_search

    with patch("agents.toolsets.catalog.search_products") as mock_search:
        mock_search.return_value = mock_products

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await product_search(ctx, query="test", limit=100)

        # Verify limit was capped at 20
        call_args = mock_search.call_args
        assert call_args.kwargs["limit"] == 20 or call_args.args[2] == 20


@pytest.mark.asyncio
async def test_product_check_inventory_formats_in_stock(mock_products, agent_deps):
    """Test inventory_check shows in-stock status correctly."""
    from agents.toolsets.catalog import inventory_check

    with patch("agents.toolsets.catalog.get_product_by_sku") as mock_get:
        mock_get.return_value = mock_products[0]  # 50 units in stock

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await inventory_check(ctx, sku="PROD-001")

        assert "Test Product 1" in result
        assert "✅" in result or "In stock" in result
        assert "50" in result


@pytest.mark.asyncio
async def test_product_check_inventory_formats_low_stock(mock_products, agent_deps):
    """Test inventory_check shows low-stock warning."""
    from agents.toolsets.catalog import inventory_check

    with patch("agents.toolsets.catalog.get_product_by_sku") as mock_get:
        mock_get.return_value = mock_products[1]  # 5 units, threshold 10

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await inventory_check(ctx, sku="PROD-002")

        assert "⚠️" in result or "Low stock" in result
        assert "5" in result


@pytest.mark.asyncio
async def test_product_check_inventory_formats_out_of_stock(out_of_stock_product, agent_deps):
    """Test inventory_check shows out-of-stock status."""
    from agents.toolsets.catalog import inventory_check

    with patch("agents.toolsets.catalog.get_product_by_sku") as mock_get:
        mock_get.return_value = out_of_stock_product

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await inventory_check(ctx, sku="PROD-OUT")

        assert "❌" in result or "Out of stock" in result
        assert "unavailable" in result.lower()


@pytest.mark.asyncio
async def test_product_check_inventory_not_found(agent_deps):
    """Test inventory_check when SKU doesn't exist."""
    from agents.toolsets.catalog import inventory_check

    with patch("agents.toolsets.catalog.get_product_by_sku") as mock_get:
        mock_get.return_value = None

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await inventory_check(ctx, sku="INVALID-SKU")

        assert "not found" in result.lower()
        assert "INVALID-SKU" in result


@pytest.mark.asyncio
async def test_product_check_inventory_validates_sku(agent_deps):
    """Test inventory_check requires valid SKU."""
    from agents.toolsets.catalog import inventory_check

    ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
    result = await inventory_check(ctx, sku="")

    assert "Error" in result


@pytest.mark.asyncio
async def test_product_check_inventory_handles_inactive_product(mock_products, agent_deps):
    """Test inventory_check handles inactive products."""
    from agents.toolsets.catalog import inventory_check

    inactive_product = mock_products[0]
    inactive_product.status = "inactive"

    with patch("agents.toolsets.catalog.get_product_by_sku") as mock_get:
        mock_get.return_value = inactive_product

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await inventory_check(ctx, sku="PROD-001")

        assert "unavailable" in result.lower()
