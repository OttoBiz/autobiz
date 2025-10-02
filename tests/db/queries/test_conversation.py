"""Unit tests for db/queries/conversation.py"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from db.models.conversation import Conversation, ConversationChannel, ConversationStatus
from db.queries.conversation import (
    create_conversation,
    delete_conversation,
    escalate_conversation,
    get_business_conversations,
    get_conversation_by_id,
    get_customer_conversations,
    update_conversation,
)


@pytest.fixture
def mock_conversation_data():
    """Fixture providing sample conversation data."""
    return {
        "id": uuid4(),
        "customer_id": uuid4(),
        "business_id": uuid4(),
        "channel": "whatsapp",
        "status": "active",
        "assigned_to_user_id": None,
        "escalated_at": None,
        "feedback_score": None,
        "business_notes": None,
        "metadata": {},
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.fixture
def mock_connection():
    """Fixture providing a mock database connection."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_conversation(mock_connection, mock_conversation_data):
    """Test creating a new conversation."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_conversation_data)

    with patch("db.queries.conversation.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        conversation = await create_conversation(
            business_id=mock_conversation_data["business_id"],
            channel=ConversationChannel.WHATSAPP,
            customer_id=mock_conversation_data["customer_id"],
        )

        assert isinstance(conversation, Conversation)
        assert conversation.channel == ConversationChannel.WHATSAPP
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_create_conversation_with_string_channel(mock_connection, mock_conversation_data):
    """Test creating a conversation with channel as string."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_conversation_data)

    with patch("db.queries.conversation.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        conversation = await create_conversation(
            business_id=mock_conversation_data["business_id"],
            channel="whatsapp",
        )

        assert isinstance(conversation, Conversation)
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_conversation_by_id(mock_connection, mock_conversation_data):
    """Test getting a conversation by ID."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_conversation_data)

    with patch("db.queries.conversation.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        conversation = await get_conversation_by_id(mock_conversation_data["id"])

        assert conversation is not None
        assert isinstance(conversation, Conversation)
        assert conversation.id == mock_conversation_data["id"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_customer_conversations(mock_connection, mock_conversation_data):
    """Test getting all conversations for a customer."""
    conv_data_2 = {**mock_conversation_data, "id": uuid4()}
    mock_connection.fetch = AsyncMock(return_value=[mock_conversation_data, conv_data_2])

    with patch("db.queries.conversation.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        conversations = await get_customer_conversations(mock_conversation_data["customer_id"])

        assert len(conversations) == 2
        assert all(isinstance(c, Conversation) for c in conversations)
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_business_conversations_all(mock_connection, mock_conversation_data):
    """Test getting all conversations for a business without status filter."""
    conv_data_2 = {**mock_conversation_data, "id": uuid4(), "status": "resolved"}
    mock_connection.fetch = AsyncMock(return_value=[mock_conversation_data, conv_data_2])

    with patch("db.queries.conversation.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        conversations = await get_business_conversations(mock_conversation_data["business_id"])

        assert len(conversations) == 2
        assert all(isinstance(c, Conversation) for c in conversations)
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_business_conversations_with_status(mock_connection, mock_conversation_data):
    """Test getting conversations for a business filtered by status."""
    mock_connection.fetch = AsyncMock(return_value=[mock_conversation_data])

    with patch("db.queries.conversation.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        conversations = await get_business_conversations(
            business_id=mock_conversation_data["business_id"],
            status=ConversationStatus.ACTIVE,
        )

        assert len(conversations) == 1
        assert conversations[0].status == ConversationStatus.ACTIVE
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_update_conversation(mock_connection, mock_conversation_data):
    """Test updating a conversation."""
    updated_data = {**mock_conversation_data, "status": "resolved"}
    mock_connection.fetchrow = AsyncMock(return_value=updated_data)

    with patch("db.queries.conversation.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        conversation = await update_conversation(mock_conversation_data["id"], status="resolved")

        assert conversation is not None
        assert conversation.status == ConversationStatus.RESOLVED
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_escalate_conversation(mock_connection, mock_conversation_data):
    """Test escalating a conversation to a user."""
    user_id = uuid4()
    escalated_data = {
        **mock_conversation_data,
        "status": "escalated",
        "assigned_to_user_id": user_id,
        "escalated_at": datetime.now(),
    }
    mock_connection.fetchrow = AsyncMock(return_value=escalated_data)

    with patch("db.queries.conversation.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        conversation = await escalate_conversation(mock_conversation_data["id"], user_id)

        assert conversation is not None
        assert conversation.status == ConversationStatus.ESCALATED
        assert conversation.assigned_to_user_id == user_id
        assert conversation.escalated_at is not None
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_delete_conversation_success(mock_connection):
    """Test deleting a conversation successfully."""
    mock_connection.execute = AsyncMock(return_value="DELETE 1")

    with patch("db.queries.conversation.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_conversation(uuid4())

        assert result is True
        mock_connection.execute.assert_called_once()
