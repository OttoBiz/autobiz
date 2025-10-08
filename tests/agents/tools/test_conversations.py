"""Unit tests for conversation management tools."""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from agents.deps import AgentDeps
from db.models.conversation import Conversation, ConversationChannel, ConversationStatus


@pytest.fixture
def mock_conversation():
    """Fixture providing a sample conversation."""
    return Conversation(
        id=uuid4(),
        customer_id=uuid4(),
        business_id=uuid4(),
        channel=ConversationChannel.WHATSAPP,
        status=ConversationStatus.ACTIVE,
        assigned_to_user_id=None,
        escalated_at=None,
        feedback_score=None,
        business_notes=None,
        metadata={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def escalated_conversation(mock_conversation):
    """Fixture providing an escalated conversation."""
    user_id = uuid4()
    escalated = mock_conversation.model_copy()
    escalated.status = ConversationStatus.ESCALATED
    escalated.assigned_to_user_id = user_id
    escalated.escalated_at = datetime.now()
    return escalated


@pytest.fixture
def agent_deps():
    """Fixture providing agent dependencies."""
    return AgentDeps(
        business_id=uuid4(),
        conversation_id=uuid4(),
        customer_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_conversation_escalate_creates_internal_note(escalated_conversation, agent_deps):
    """Test that escalation creates an internal note."""
    from agents.toolsets.conversations import escalate_to_human

    user_id = str(uuid4())
    reason = "Customer is frustrated with shipping delays"

    with (
        patch("agents.toolsets.conversations.escalate_conversation") as mock_escalate,
        patch("agents.toolsets.conversations.create_message") as mock_create_msg,
    ):
        mock_escalate.return_value = escalated_conversation
        mock_create_msg.return_value = AsyncMock()

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await escalate_to_human(ctx, reason=reason, user_id=user_id)

        # Verify escalation was called with the conversation_id and the converted UUID
        mock_escalate.assert_called_once()
        call_args = mock_escalate.call_args
        assert call_args.args[0] == agent_deps.conversation_id  # First arg is conversation_id
        assert isinstance(call_args.args[1], UUID)  # Second arg is the UUID from user_id string

        # Verify internal message was created
        mock_create_msg.assert_called_once()
        call_args = mock_create_msg.call_args
        assert call_args.kwargs["is_internal"] is True
        assert reason in call_args.kwargs["content"]


@pytest.mark.asyncio
async def test_conversation_escalate_formats_success_message(escalated_conversation, agent_deps):
    """Test escalate_to_human returns proper success message."""
    from agents.toolsets.conversations import escalate_to_human

    user_id = str(uuid4())
    reason = "Complex technical issue"

    with (
        patch("agents.toolsets.conversations.escalate_conversation") as mock_escalate,
        patch("agents.toolsets.conversations.create_message") as mock_create_msg,
    ):
        mock_escalate.return_value = escalated_conversation
        mock_create_msg.return_value = AsyncMock()

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await escalate_to_human(ctx, reason=reason, user_id=user_id)

        assert "successfully escalated" in result.lower()
        assert "team member" in result.lower()
        assert reason in result


@pytest.mark.asyncio
async def test_conversation_escalate_requires_conversation_id(agent_deps):
    """Test escalate_to_human requires active conversation."""
    from agents.toolsets.conversations import escalate_to_human

    # No conversation_id in deps
    deps_no_conversation = AgentDeps(business_id=uuid4())

    ctx = RunContext(
        deps=deps_no_conversation, retry=0, messages=[], model=TestModel(), usage=RunUsage()
    )
    result = await escalate_to_human(ctx, reason="Test reason", user_id=str(uuid4()))

    assert "Error" in result
    assert "no active conversation" in result.lower()


@pytest.mark.asyncio
async def test_conversation_escalate_validates_reason(agent_deps):
    """Test escalate_to_human requires detailed reason."""
    from agents.toolsets.conversations import escalate_to_human

    ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())

    # Too short reason
    result = await escalate_to_human(ctx, reason="short", user_id=str(uuid4()))

    assert "Error" in result
    assert "detailed reason" in result.lower()


@pytest.mark.asyncio
async def test_conversation_escalate_validates_user_id(agent_deps):
    """Test escalate_to_human validates user_id format."""
    from agents.toolsets.conversations import escalate_to_human

    ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())

    # Invalid UUID format
    result = await escalate_to_human(
        ctx, reason="This is a valid detailed reason", user_id="not-a-uuid"
    )

    assert "Error" in result
    assert "Invalid user_id" in result or "UUID" in result


@pytest.mark.asyncio
async def test_conversation_escalate_handles_failed_escalation(agent_deps):
    """Test escalate_to_human handles when escalation fails."""
    from agents.toolsets.conversations import escalate_to_human

    with patch("agents.toolsets.conversations.escalate_conversation") as mock_escalate:
        mock_escalate.return_value = None  # Escalation failed

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await escalate_to_human(
            ctx, reason="Valid reason for escalation", user_id=str(uuid4())
        )

        assert "Error" in result
        assert "Failed to escalate" in result


@pytest.mark.asyncio
async def test_conversation_add_note_success(agent_deps):
    """Test add_internal_note successfully adds internal note."""
    from agents.toolsets.conversations import add_internal_note

    with patch("agents.toolsets.conversations.create_message") as mock_create_msg:
        mock_create_msg.return_value = AsyncMock()

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await add_internal_note(
            ctx, note="Customer mentioned they're interested in premium features"
        )

        # Verify message was created as internal
        mock_create_msg.assert_called_once()
        call_args = mock_create_msg.call_args
        assert call_args.kwargs["is_internal"] is True
        assert call_args.kwargs["sender_type"] == "agent"
        assert "premium features" in call_args.kwargs["content"]

        assert "✅" in result or "successfully" in result.lower()


@pytest.mark.asyncio
async def test_conversation_add_note_requires_conversation_id(agent_deps):
    """Test add_internal_note requires active conversation."""
    from agents.toolsets.conversations import add_internal_note

    # No conversation_id in deps
    deps_no_conversation = AgentDeps(business_id=uuid4())

    ctx = RunContext(
        deps=deps_no_conversation, retry=0, messages=[], model=TestModel(), usage=RunUsage()
    )
    result = await add_internal_note(ctx, note="Test note")

    assert "Error" in result
    assert "no active conversation" in result.lower()


@pytest.mark.asyncio
async def test_conversation_add_note_validates_note_length(agent_deps):
    """Test add_internal_note requires meaningful note."""
    from agents.toolsets.conversations import add_internal_note

    ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())

    # Too short note
    result = await add_internal_note(ctx, note="hi")

    assert "Error" in result
    assert "meaningful" in result.lower() or "5 characters" in result


@pytest.mark.asyncio
async def test_conversation_add_note_formats_with_prefix(agent_deps):
    """Test add_internal_note adds INTERNAL NOTE prefix."""
    from agents.toolsets.conversations import add_internal_note

    with patch("agents.toolsets.conversations.create_message") as mock_create_msg:
        mock_create_msg.return_value = AsyncMock()

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        note_content = "Customer is a high-value prospect"
        result = await add_internal_note(ctx, note=note_content)

        # Verify note has internal prefix
        call_args = mock_create_msg.call_args
        assert "[INTERNAL NOTE]" in call_args.kwargs["content"]
        assert note_content in call_args.kwargs["content"]


@pytest.mark.asyncio
async def test_conversation_add_note_confirms_invisibility_to_customer(agent_deps):
    """Test add_internal_note confirms note is invisible to customer."""
    from agents.toolsets.conversations import add_internal_note

    with patch("agents.toolsets.conversations.create_message") as mock_create_msg:
        mock_create_msg.return_value = AsyncMock()

        ctx = RunContext(deps=agent_deps, retry=0, messages=[], model=TestModel(), usage=RunUsage())
        result = await add_internal_note(ctx, note="Important context note")

        assert "not to the customer" in result.lower() or "visible to your team" in result.lower()
