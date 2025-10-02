"""Unit tests for db/queries/customer.py"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from db.models.customer import Customer
from db.queries.customer import (
    add_customer_tags,
    create_customer,
    delete_customer,
    find_customer_by_contact,
    get_business_customers,
    get_customer_by_id,
    update_customer,
)


@pytest.fixture
def mock_customer_data():
    """Fixture providing sample customer data."""
    return {
        "id": uuid4(),
        "business_id": uuid4(),
        "name": "John Doe",
        "email": "john@example.com",
        "phone": "+1234567890",
        "tags": ["vip", "returning"],
        "segments": ["high-value"],
        "lifecycle_stage": "active",
        "customer_value_score": 85,
        "notes": "Great customer",
        "custom_fields": {"preference": "email"},
        "preferences": {"newsletter": True},
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.fixture
def mock_connection():
    """Fixture providing a mock database connection."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_customer(mock_connection, mock_customer_data):
    """Test creating a new customer."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_customer_data)

    with patch("db.queries.customer.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        customer = await create_customer(
            business_id=mock_customer_data["business_id"],
            name=mock_customer_data["name"],
            email=mock_customer_data["email"],
            phone=mock_customer_data["phone"],
        )

        assert isinstance(customer, Customer)
        assert customer.name == mock_customer_data["name"]
        assert customer.email == mock_customer_data["email"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_customer_by_id(mock_connection, mock_customer_data):
    """Test getting a customer by ID."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_customer_data)

    with patch("db.queries.customer.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        customer = await get_customer_by_id(mock_customer_data["id"])

        assert customer is not None
        assert isinstance(customer, Customer)
        assert customer.id == mock_customer_data["id"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_find_customer_by_email(mock_connection, mock_customer_data):
    """Test finding a customer by email."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_customer_data)

    with patch("db.queries.customer.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        customer = await find_customer_by_contact(
            business_id=mock_customer_data["business_id"],
            email=mock_customer_data["email"],
        )

        assert customer is not None
        assert customer.email == mock_customer_data["email"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_find_customer_by_phone(mock_connection, mock_customer_data):
    """Test finding a customer by phone."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_customer_data)

    with patch("db.queries.customer.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        customer = await find_customer_by_contact(
            business_id=mock_customer_data["business_id"],
            phone=mock_customer_data["phone"],
        )

        assert customer is not None
        assert customer.phone == mock_customer_data["phone"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_find_customer_by_contact_no_params():
    """Test find_customer_by_contact with no email or phone returns None."""
    customer = await find_customer_by_contact(business_id=uuid4())
    assert customer is None


@pytest.mark.asyncio
async def test_get_business_customers(mock_connection, mock_customer_data):
    """Test getting all customers for a business."""
    customer_data_2 = {**mock_customer_data, "id": uuid4(), "email": "jane@example.com"}
    mock_connection.fetch = AsyncMock(return_value=[mock_customer_data, customer_data_2])

    with patch("db.queries.customer.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        customers = await get_business_customers(mock_customer_data["business_id"])

        assert len(customers) == 2
        assert all(isinstance(c, Customer) for c in customers)
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_update_customer(mock_connection, mock_customer_data):
    """Test updating a customer."""
    updated_data = {**mock_customer_data, "name": "Jane Doe"}
    mock_connection.fetchrow = AsyncMock(return_value=updated_data)

    with patch("db.queries.customer.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        customer = await update_customer(mock_customer_data["id"], name="Jane Doe")

        assert customer is not None
        assert customer.name == "Jane Doe"
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_add_customer_tags(mock_connection, mock_customer_data):
    """Test adding tags to a customer."""
    updated_data = {**mock_customer_data, "tags": ["vip", "returning", "premium"]}
    mock_connection.fetchrow = AsyncMock(return_value=updated_data)

    with patch("db.queries.customer.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        customer = await add_customer_tags(mock_customer_data["id"], ["premium"])

        assert customer is not None
        assert "premium" in customer.tags
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_delete_customer_success(mock_connection):
    """Test deleting a customer successfully."""
    mock_connection.execute = AsyncMock(return_value="DELETE 1")

    with patch("db.queries.customer.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_customer(uuid4())

        assert result is True
        mock_connection.execute.assert_called_once()
