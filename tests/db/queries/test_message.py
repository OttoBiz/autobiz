"""Unit tests for db/queries/message.py"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from db.models.message import Message, MessageSenderType
from db.queries.message import (
    create_message,
    delete_message,
    get_conversation_messages,
    get_message_by_id,
    get_public_messages,
    update_message,
)


@pytest.fixture
def mock_message_data():
    """Fixture providing sample message data."""
    return {
        "id": uuid4(),
        "conversation_id": uuid4(),
        "sender_type": "customer",
        "content": "Hello, I need help with my order",
        "is_internal": False,
        "timestamp": datetime.now(),
    }


@pytest.fixture
def mock_internal_message_data():
    """Fixture providing sample internal message data."""
    return {
        "id": uuid4(),
        "conversation_id": uuid4(),
        "sender_type": "user",
        "content": "This customer seems frustrated",
        "is_internal": True,
        "timestamp": datetime.now(),
    }


@pytest.fixture
def mock_connection():
    """Fixture providing a mock database connection."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_message(mock_connection, mock_message_data):
    """Test creating a new message."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_message_data)

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        message = await create_message(
            conversation_id=mock_message_data["conversation_id"],
            sender_type=MessageSenderType.CUSTOMER,
            content=mock_message_data["content"],
        )

        assert isinstance(message, Message)
        assert message.content == mock_message_data["content"]
        assert message.is_internal is False
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_create_internal_message(mock_connection, mock_internal_message_data):
    """Test creating an internal message."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_internal_message_data)

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        message = await create_message(
            conversation_id=mock_internal_message_data["conversation_id"],
            sender_type=MessageSenderType.USER,
            content=mock_internal_message_data["content"],
            is_internal=True,
        )

        assert isinstance(message, Message)
        assert message.is_internal is True
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_create_message_with_string_sender_type(mock_connection, mock_message_data):
    """Test creating a message with sender_type as string."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_message_data)

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        message = await create_message(
            conversation_id=mock_message_data["conversation_id"],
            sender_type="customer",
            content=mock_message_data["content"],
        )

        assert isinstance(message, Message)
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_message_by_id(mock_connection, mock_message_data):
    """Test getting a message by ID."""
    mock_connection.fetchrow = AsyncMock(return_value=mock_message_data)

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        message = await get_message_by_id(mock_message_data["id"])

        assert message is not None
        assert isinstance(message, Message)
        assert message.id == mock_message_data["id"]
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_get_conversation_messages_include_internal(
    mock_connection, mock_message_data, mock_internal_message_data
):
    """Test getting all messages including internal ones."""
    mock_connection.fetch = AsyncMock(return_value=[mock_message_data, mock_internal_message_data])

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        messages = await get_conversation_messages(
            mock_message_data["conversation_id"], include_internal=True
        )

        assert len(messages) == 2
        assert all(isinstance(m, Message) for m in messages)
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_conversation_messages_exclude_internal(mock_connection, mock_message_data):
    """Test getting messages excluding internal ones."""
    mock_connection.fetch = AsyncMock(return_value=[mock_message_data])

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        messages = await get_conversation_messages(
            mock_message_data["conversation_id"], include_internal=False
        )

        assert len(messages) == 1
        assert messages[0].is_internal is False
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_public_messages(mock_connection, mock_message_data):
    """Test getting only public messages."""
    mock_connection.fetch = AsyncMock(return_value=[mock_message_data])

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        messages = await get_public_messages(mock_message_data["conversation_id"])

        assert len(messages) == 1
        assert messages[0].is_internal is False
        mock_connection.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_update_message(mock_connection, mock_message_data):
    """Test updating a message."""
    updated_data = {**mock_message_data, "content": "Updated content"}
    mock_connection.fetchrow = AsyncMock(return_value=updated_data)

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        message = await update_message(mock_message_data["id"], content="Updated content")

        assert message is not None
        assert message.content == "Updated content"
        mock_connection.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_delete_message_success(mock_connection):
    """Test deleting a message successfully."""
    mock_connection.execute = AsyncMock(return_value="DELETE 1")

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_message(uuid4())

        assert result is True
        mock_connection.execute.assert_called_once()


@pytest.mark.asyncio
async def test_delete_message_not_found(mock_connection):
    """Test deleting a non-existent message."""
    mock_connection.execute = AsyncMock(return_value="DELETE 0")

    with patch("db.queries.message.get_db_connection") as mock_get_conn:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_get_conn.return_value = mock_ctx

        result = await delete_message(uuid4())

        assert result is False
        mock_connection.execute.assert_called_once()
