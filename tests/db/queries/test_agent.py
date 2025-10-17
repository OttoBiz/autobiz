"""Unit tests for db/queries/agent.py"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from db.models.agent import Agent
from db.queries.agent import (
    create_agent,
    delete_agent,
    get_agent_by_business_id,
    get_agent_by_id,
    update_agent,
)


@pytest.fixture
def mock_agent_data():
    """Fixture providing sample agent data."""
    return {
        "id": uuid4(),
        "business_id": uuid4(),
        "name": "Test Agent",
        "key": "test_agent",
        "system_prompt": "You are a helpful assistant",
        "tool_groups": ["catalog", "customers"],
        "subagents": [],
        "metadata": {
            "avatar_url": "https://example.com/avatar.png",
            "personality": "Friendly and helpful",
            "tone": "Professional",
            "greeting_message": "Hello! How can I help you?",
        },
        "channels": {
            "whatsapp": {"enabled": True, "credentials": {}, "config": {}},
            "webchat": {"enabled": False, "config": {}},
        },
        "status": "active",
        "version": 1,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.fixture
def mock_connection():
    """Fixture providing a mock database connection."""
    conn = AsyncMock()
    return conn


@pytest.mark.asyncio
async def test_create_agent(mock_connection, mock_agent_data):
    """Test creating a new agent."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_agent_data)

    with patch("db.queries.agent.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        agent = await create_agent(
            business_id=mock_agent_data["business_id"],
            name=mock_agent_data["name"],
            key=mock_agent_data["key"],
            system_prompt=mock_agent_data["system_prompt"],
        )

        assert isinstance(agent, Agent)
        assert agent.name == mock_agent_data["name"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_agent_by_id_found(mock_connection, mock_agent_data):
    """Test getting an agent by ID when it exists."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_agent_data)

    with patch("db.queries.agent.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        agent = await get_agent_by_id(mock_agent_data["id"])

        assert agent is not None
        assert isinstance(agent, Agent)
        assert agent.id == mock_agent_data["id"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_agent_by_id_not_found(mock_connection):
    """Test getting an agent by ID when it doesn't exist."""
    mock_connection.fetchrow = AsyncMock(return_value=None)

    with patch("db.queries.agent.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        agent = await get_agent_by_id(uuid4())

        assert agent is None
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_agent_by_business_id(mock_connection, mock_agent_data):
    """Test getting an agent by business ID."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_agent_data)

    with patch("db.queries.agent.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        agent = await get_agent_by_business_id(mock_agent_data["business_id"])

        assert agent is not None
        assert isinstance(agent, Agent)
        assert agent.business_id == mock_agent_data["business_id"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_update_agent(mock_connection, mock_agent_data):
    """Test updating an agent."""
    updated_data = {**mock_agent_data, "name": "Updated Agent"}
    mock_connection.fetchrow = AsyncMock(return_value=updated_data)

    with patch("db.queries.agent.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        agent = await update_agent(mock_agent_data["id"], name="Updated Agent")

        assert agent is not None
        assert agent.name == "Updated Agent"
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_update_agent_no_updates(mock_connection, mock_agent_data):
    """Test updating an agent with no updates returns current agent."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_agent_data)

    with patch("db.queries.agent.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        agent = await update_agent(mock_agent_data["id"])

        assert agent is not None
        # Should call get_agent_by_id instead of UPDATE
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_delete_agent_success(mock_connection):
    """Test deleting an agent successfully."""
    mock_connection.execute = AsyncMock(return_value="DELETE 1")

    with patch("db.queries.agent.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_agent(uuid4())

        assert result is True
        mock_connection.execute.assert_called_once()


@pytest.mark.asyncio
async def test_delete_agent_not_found(mock_connection):
    """Test deleting a non-existent agent."""
    mock_connection.execute = AsyncMock(return_value="DELETE 0")

    with patch("db.queries.agent.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_agent(uuid4())

        assert result is False
        mock_connection.execute.assert_called_once()
