from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from pydantic_ai import Agent
import pytest

from agents.deps import AgentDeps
from agents.executor import AgentConfig, AgentExecutor
from agents.models import (
    HandoffResponse,
    MessageContent,
    MessageResponse,
    MultiMessageResponse,
    PauseResponse,
)


@pytest.fixture
def agent_config():
    return AgentConfig(
        id=uuid4(),
        business_id=uuid4(),
        name="legal",
        role="legal",
        system_prompt="You are a legal agent",
        tool_groups=["catalog", "customers"],
    )


@pytest.fixture
def executor():
    return AgentExecutor()


@pytest.fixture
def agent_deps():
    return AgentDeps(
        business_id=uuid4(),
        conversation_id=uuid4(),
        current_agent_id=uuid4(),
        current_agent_role="agent",
    )


def test_create_agent_executor_creates_agent(executor, agent_config):
    agent = executor.create_agent(agent_config)
    assert isinstance(agent, Agent)


def test_create_agent_executor_with_collab_tools(executor, agent_config):
    with patch("agents.executor.Agent") as MockAgent:
        agent_config.tool_groups.append("collab")
        executor.create_agent(agent_config)
        call_args = MockAgent.call_args
        assert "CONSULT" in call_args[1]["system_prompt"]
        assert "HANDOFF" in call_args[1]["system_prompt"]
        assert "Collaboration Guidelines" in call_args[1]["system_prompt"]


@pytest.mark.asyncio
async def test_run_handles_message_response(executor, agent_config, agent_deps):
    mock_agent = AsyncMock()
    mock_agent.run.return_value = MagicMock(output=MessageResponse(content="Hello customer"))
    with patch.object(executor, "load_agent_config", return_value=agent_config):
        with patch.object(executor, "create_agent", return_value=mock_agent):
            with patch.object(executor, "_send_to_channel", new_callable=AsyncMock) as mock_send:
                result = await executor.run(
                    business_id=agent_deps.business_id,
                    conversation_id=agent_deps.conversation_id,
                    agent_role="agent",
                    user_message="Hi",
                    deps=agent_deps,
                )

                mock_send.assert_called_once_with(agent_deps.channel, "Hello customer", {})
                assert result == "Hello customer"


@pytest.mark.asyncio
async def test_run_handles_pause_response(executor, agent_config, agent_deps):
    mock_agent = AsyncMock()
    mock_agent.run.return_value = MagicMock(
        output=PauseResponse(
            content="I need more info", reason="Awaiting webhook action", resume_trigger="webhook"
        )
    )
    with patch.object(executor, "load_agent_config", return_value=agent_config):
        with patch.object(executor, "create_agent", return_value=mock_agent):
            with patch.object(executor, "_send_to_channel", new_callable=AsyncMock) as mock_send:
                result = await executor.run(
                    business_id=agent_deps.business_id,
                    conversation_id=agent_deps.conversation_id,
                    agent_role="agent",
                    user_message="Hi",
                    deps=agent_deps,
                )

                mock_send.assert_called_once_with(agent_deps.channel, "I need more info")
                assert result == "I need more info"


@pytest.mark.asyncio
async def test_run_handles_multi_message_response(executor, agent_config, agent_deps):
    mock_agent = AsyncMock()
    mock_agent.run.return_value = MagicMock(
        output=MultiMessageResponse(
            messages=[
                MessageContent(content="This is a message"),
                MessageContent(content="This is another message"),
            ]
        )
    )

    with patch.object(executor, "load_agent_config", return_value=agent_config):
        with patch.object(executor, "create_agent", return_value=mock_agent):
            with patch.object(executor, "_send_to_channel", new_callable=AsyncMock) as mock_send:
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    result = await executor.run(
                        business_id=agent_deps.business_id,
                        conversation_id=agent_deps.conversation_id,
                        agent_role="agent",
                        user_message="Hi",
                        deps=agent_deps,
                    )

                    assert mock_send.call_count == 2
                    mock_send.assert_any_call(
                        agent_deps.channel, "This is a message", media_url=None, media_type=None
                    )
                    mock_send.assert_any_call(
                        agent_deps.channel,
                        "This is another message",
                        media_url=None,
                        media_type=None,
                    )
                    mock_sleep.assert_called_once_with(1.0)

                    assert "This is a message" in result
                    assert "This is another message" in result


@pytest.mark.asyncio
async def test_run_handles_handoff_response(executor, agent_config, agent_deps):
    mock_agent = AsyncMock()
    mock_agent.run.return_value = MagicMock(
        output=HandoffResponse(
            target_agent_role="legal",
            reason="Customer needs contract review",
            context_summary="Contract question",
        )
    )

    with patch.object(executor, "load_agent_config", return_value=agent_config):
        with patch.object(executor, "create_agent", return_value=mock_agent):
            with patch.object(
                executor, "_record_handoff", return_value=AsyncMock
            ) as mock_record_handoff:
                initial_run = executor.run

                async def mock_recursive_run(*args, **kwargs):
                    if kwargs.get("agent_role") == "legal":
                        return "Legal agent response"

                    return await initial_run(*args, **kwargs)

                with patch.object(executor, "run", side_effect=mock_recursive_run):
                    result = await executor.run(
                        business_id=agent_deps.business_id,
                        conversation_id=agent_deps.conversation_id,
                        agent_role="sales",
                        user_message="Hi",
                        deps=agent_deps,
                    )

                    mock_record_handoff.assert_called_once()
