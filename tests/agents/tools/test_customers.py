"""Unit tests for customer lookup tool."""

from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from agents import customer_agent
from agents.deps import AgentDeps
from db.models.customer import Customer


@pytest.fixture
def mock_customer():
    """Fixture providing a sample customer."""
    return Customer(
        id=uuid4(),
        business_id=uuid4(),
        name="John Doe",
        email="john@example.com",
        phone="+1234567890",
        tags=["vip", "returning"],
        segments=["high-value"],
        lifecycle_stage="active",
        customer_value_score=85,
        notes="Great customer, always polite",
        custom_fields={},
        preferences={},
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
async def test_customer_lookup_by_email_found(mock_customer, agent_deps):
    """Test customer_lookup when customer is found by email."""
    from agents.tools.customers import customer_lookup

    with patch("agents.tools.customers.find_customer_by_contact") as mock_find:
        mock_find.return_value = mock_customer

        ctx = RunContext(
            deps=agent_deps,
            retry=0,
            messages=[],
            model=TestModel(),
            usage=RunUsage(),
        )
        result = await customer_lookup(ctx, email="john@example.com")

        # Verify the tool was called and returned customer info
        mock_find.assert_called_once()
        assert "John Doe" in result
        assert "john@example.com" in result


@pytest.mark.asyncio
async def test_customer_lookup_by_phone_found(mock_customer, agent_deps):
    """Test customer_lookup when customer is found by phone."""
    from agents.tools.customers import customer_lookup

    with patch("agents.tools.customers.find_customer_by_contact") as mock_find:
        mock_find.return_value = mock_customer

        ctx = RunContext(
            deps=agent_deps,
            retry=0,
            messages=[],
            model=TestModel(),
            usage=RunUsage(),
        )
        result = await customer_lookup(ctx, phone="+1234567890")

        mock_find.assert_called_once()
        assert "John Doe" in result


@pytest.mark.asyncio
async def test_customer_lookup_not_found(agent_deps):
    """Test customer_lookup when customer is not found."""
    from agents.tools.customers import customer_lookup

    with patch("agents.tools.customers.find_customer_by_contact") as mock_find:
        mock_find.return_value = None

        ctx = RunContext(
            deps=agent_deps,
            retry=0,
            messages=[],
            model=TestModel(),
            usage=RunUsage(),
        )
        result = await customer_lookup(ctx, email="unknown@example.com")

        mock_find.assert_called_once()
        assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_customer_lookup_formats_response_correctly(mock_customer, agent_deps):
    """Test that customer_lookup returns properly formatted natural language response."""
    from agents.tools.customers import customer_lookup

    with patch("agents.tools.customers.find_customer_by_contact") as mock_find:
        mock_find.return_value = mock_customer

        ctx = RunContext(
            deps=agent_deps,
            retry=0,
            messages=[],
            model=TestModel(),
            usage=RunUsage(),
        )
        result = await customer_lookup(ctx, email="john@example.com")

        # Verify response contains key information in natural language
        assert "John Doe" in result
        assert "john@example.com" in result
        assert "active" in result
        assert "vip" in result
        assert "85/100" in result
        assert "Great customer" in result


@pytest.mark.asyncio
async def test_customer_lookup_new_customer_message(agent_deps):
    """Test that customer_lookup returns appropriate message for new customers."""
    from agents.tools.customers import customer_lookup

    with patch("agents.tools.customers.find_customer_by_contact") as mock_find:
        mock_find.return_value = None

        ctx = RunContext(
            deps=agent_deps,
            retry=0,
            messages=[],
            model=TestModel(),
            usage=RunUsage(),
        )
        result = await customer_lookup(ctx, email="newcustomer@example.com")

        assert "not found" in result.lower()
        assert "new customer" in result.lower()


@pytest.mark.asyncio
async def test_customer_lookup_requires_contact_info(agent_deps):
    """Test that customer_lookup requires email or phone."""
    from agents.tools.customers import customer_lookup

    ctx = RunContext(
        deps=agent_deps,
        retry=0,
        messages=[],
        model=TestModel(),
        usage=RunUsage(),
    )
    result = await customer_lookup(ctx)

    assert "Error" in result
    assert "email" in result.lower() or "phone" in result.lower()


@pytest.mark.asyncio
async def test_customer_lookup_handles_missing_optional_fields(agent_deps):
    """Test customer_lookup handles customers with minimal information."""
    minimal_customer = Customer(
        id=uuid4(),
        business_id=agent_deps.business_id,
        name=None,
        email="minimal@example.com",
        phone=None,
        tags=[],
        segments=[],
        lifecycle_stage=None,
        customer_value_score=None,
        notes=None,
        custom_fields={},
        preferences={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    from agents.tools.customers import customer_lookup

    with patch("agents.tools.customers.find_customer_by_contact") as mock_find:
        mock_find.return_value = minimal_customer

        ctx = RunContext(
            deps=agent_deps,
            retry=0,
            messages=[],
            model=TestModel(),
            usage=RunUsage(),
        )
        result = await customer_lookup(ctx, email="minimal@example.com")

        # Should not crash and should handle None values gracefully
        assert "minimal@example.com" in result
        assert "Not provided" in result or "None" in result
