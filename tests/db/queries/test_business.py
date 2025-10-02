"""Unit tests for db/queries/business.py"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from db.models.business import Business
from db.queries.business import (
    create_business,
    delete_business,
    get_business_by_id,
    get_business_by_slug,
    get_businesses_by_owner,
    update_business,
)


@pytest.fixture
def mock_business_data():
    """Fixture providing sample business data."""
    return {
        "id": uuid4(),
        "name": "Test Business",
        "slug": "test-business",
        "owner_user_id": uuid4(),
        "subscription_plan_id": uuid4(),
        "subscription_status": "active",
        "description": "A test business",
        "industry": "Technology",
        "contact_email": "contact@test.com",
        "policies": {},
        "logo_url": "https://example.com/logo.png",
        "primary_color": "#000000",
        "theme_config": {},
        "timezone": "UTC",
        "currency": "USD",
        "business_hours": {},
        "catalog_sync_source": None,
        "catalog_sync_config": {},
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.fixture
def mock_connection():
    """Fixture providing a mock database connection."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_business(mock_connection, mock_business_data):
    """Test creating a new business."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_business_data)

    with patch("db.queries.business.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        business = await create_business(
            name=mock_business_data["name"],
            slug=mock_business_data["slug"],
            owner_user_id=mock_business_data["owner_user_id"],
            subscription_plan_id=mock_business_data["subscription_plan_id"],
        )

        assert isinstance(business, Business)
        assert business.name == mock_business_data["name"]
        assert business.slug == mock_business_data["slug"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_business_by_id(mock_connection, mock_business_data):
    """Test getting a business by ID."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_business_data)

    with patch("db.queries.business.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        business = await get_business_by_id(mock_business_data["id"])

        assert business is not None
        assert isinstance(business, Business)
        assert business.id == mock_business_data["id"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_business_by_slug(mock_connection, mock_business_data):
    """Test getting a business by slug."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_business_data)

    with patch("db.queries.business.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        business = await get_business_by_slug(mock_business_data["slug"])

        assert business is not None
        assert business.slug == mock_business_data["slug"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_businesses_by_owner(mock_connection, mock_business_data):
    """Test getting all businesses owned by a user."""
    business_data_2 = {**mock_business_data, "id": uuid4(), "slug": "test-business-2"}
    mock_connection.fetch = AsyncMock(return_value=[mock_business_data, business_data_2])

    with patch("db.queries.business.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        businesses = await get_businesses_by_owner(mock_business_data["owner_user_id"])

        assert len(businesses) == 2
        assert all(isinstance(b, Business) for b in businesses)
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_update_business(mock_connection, mock_business_data):
    """Test updating a business."""
    updated_data = {**mock_business_data, "name": "Updated Business"}
    mock_connection.fetchrow = AsyncMock(return_value=updated_data)

    with patch("db.queries.business.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        business = await update_business(mock_business_data["id"], name="Updated Business")

        assert business is not None
        assert business.name == "Updated Business"
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_delete_business_success(mock_connection):
    """Test deleting a business successfully."""
    mock_connection.execute = AsyncMock(return_value="DELETE 1")

    with patch("db.queries.business.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_business(uuid4())

        assert result is True
        mock_connection.execute.assert_called_once()


@pytest.mark.asyncio
async def test_delete_business_not_found(mock_connection):
    """Test deleting a non-existent business."""
    mock_connection.execute = AsyncMock(return_value="DELETE 0")

    with patch("db.queries.business.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_business(uuid4())

        assert result is False
        mock_connection.execute.assert_called_once()
