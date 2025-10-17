"""Unit tests for collaboration tools."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from agents.deps import AgentDeps
from agents.toolsets.collaboration import consult


@pytest.fixture
def agent_deps():
    """Fixture providing agent dependencies."""
    return AgentDeps(
        business_id=uuid4(),
        conversation_id=uuid4(),
        customer_id=uuid4(),
        current_agent_key="sales",
    )


@pytest.mark.asyncio
async def test_consult_calls_executor_with_correct_params(agent_deps):
    """Test that consult calls executor.run with correct parameters."""

    mock_executor = AsyncMock()
    mock_executor.run.return_value = "The inventory count is 42 units"

    agent_deps.executor = mock_executor

    ctx = RunContext(deps=agent_deps, model=TestModel(), usage=RunUsage())

    result = await consult(
        ctx, target_agent_key="inventory", question="What's the stock count for SKU-123?"
    )

    mock_executor.run.assert_called_once()
    assert result == "The inventory count is 42 units"


@pytest.mark.asyncio
async def test_consult_passes_correct_params_to_executor(agent_deps):
    """Test that consult passes the right parameters to executor.run."""

    mock_executor = AsyncMock()
    mock_executor.run.return_value = "Answer from pricing agent"
    agent_deps.executor = mock_executor

    ctx = RunContext(deps=agent_deps, model=TestModel(), usage=RunUsage())

    await consult(ctx, target_agent_key="pricing", question="What's the price?")

    call_args = mock_executor.run.call_args
    assert call_args.kwargs["agent_key"] == "pricing"
    assert "What's the price?" in call_args.kwargs["user_message"]
    assert call_args.kwargs["business_id"] == agent_deps.business_id
    assert call_args.kwargs["conversation_id"] == agent_deps.conversation_id


async def test_consult_includes_consultation_context(agent_deps):
    """Test that consult wraps the question with consultation context."""

    mock_executor = AsyncMock()
    mock_executor.run.return_value = "Response"
    agent_deps.executor = mock_executor

    ctx = RunContext(deps=agent_deps, model=TestModel(), usage=RunUsage())

    await consult(ctx, target_agent_key="legal", question="Can we offer net-30?")

    # Verify the message includes consultation context
    call_args = mock_executor.run.call_args
    message = call_args.kwargs["user_message"]
    assert "[INTERNAL CONSULTATION from sales]" in message
    assert "Can we offer net-30?" in message
