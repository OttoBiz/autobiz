"""Conversation workflow for durable agent interactions.

State Management:
- Conversation state is persisted in PostgreSQL via activities
- Workflow only tracks pending messages and conversation metadata
- Uses load_conversation_state and save_conversation_state activities
"""

from datetime import timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from temporal.models import AgentResponse, CustomerMessage


@workflow.defn
class ConversationWorkflow:
    """Long-running workflow for customer conversations.

    Each conversation is a single workflow instance that:
    - Waits indefinitely for customer messages (via signals)
    - Executes agent logic when messages arrive (via activities)
    - Loads/saves state from PostgreSQL (via activities)
    - Handles agent transfers and collaboration
    """

    def __init__(self) -> None:
        self.conversation_id: UUID | None = None
        self.business_id: UUID | None = None
        self.pending_messages: list[CustomerMessage] = []

    @workflow.run
    async def run(
        self,
        conversation_id: UUID,
        business_id: UUID,
        agent_id: UUID,
        agent_role: str,
        customer_id: UUID | None = None,
    ) -> None:
        """Start the conversation workflow."""
        # Store conversation metadata
        self.conversation_id = conversation_id
        self.business_id = business_id

        # Initialize conversation state in database
        await workflow.execute_activity(
            "initialize_conversation_state",
            args=[
                str(conversation_id),
                str(business_id),
                str(customer_id) if customer_id else None,
                str(agent_id),
            ],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                backoff_coefficient=2.0,
            ),
        )

        # Main event loop - runs indefinitely
        while True:
            # Wait for customer message signal (or timeout after 30 days)
            await workflow.wait_condition(
                lambda: len(self.pending_messages) > 0,
                timeout=timedelta(days=30),
            )

            if not self.pending_messages:
                # Timeout reached - cleanup and end workflow
                workflow.logger.info(
                    f"Conversation {conversation_id} timed out after 30 days of inactivity"
                )

                # Archive conversation
                await workflow.execute_activity(
                    "archive_conversation",
                    args=[str(conversation_id)],
                    start_to_close_timeout=timedelta(seconds=30),
                )

                break

            # Process next message
            message = self.pending_messages.pop(0)

            # Execute agent activity (loads and saves state internally)
            response: AgentResponse = await workflow.execute_activity(
                "execute_agent",
                args=[
                    str(conversation_id),
                    str(business_id),
                    str(agent_id),
                    message.message,
                ],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2.0,
                ),
            )

            # Send response to customer
            await workflow.execute_activity(
                "send_message",
                args=[
                    str(conversation_id),
                    str(business_id),
                    response.message,
                ],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2.0,
                ),
            )

            # Handle agent transfer
            # Note: State is already updated in agent activity via state_manager.add_handoff()
            # We just need to update workflow's local agent_id for next iteration
            if response.should_transfer and response.transfer_to_agent_id:
                workflow.logger.info(
                    f"Transferred conversation {conversation_id} to agent {response.transfer_to_agent_id}"
                )
                agent_id = response.transfer_to_agent_id
                agent_role = response.transfer_to_role or "unknown"

            # Handle pause (state updated in activity)
            if response.should_pause:
                workflow.logger.info(
                    f"Paused conversation {conversation_id}: {response.pause_reason}"
                )
                # Create state snapshot for resume
                await workflow.execute_activity(
                    "create_state_snapshot",
                    args=[str(conversation_id)],
                    start_to_close_timeout=timedelta(seconds=10),
                )

    @workflow.signal
    async def new_message(self, message: CustomerMessage) -> None:
        """Handle incoming customer message signal."""
        self.pending_messages.append(message)

    @workflow.signal
    async def resume_conversation(self) -> None:
        """Resume a paused conversation.

        Note: State is loaded from PostgreSQL, not workflow memory.
        """
        if self.conversation_id:
            workflow.logger.info(f"Resuming conversation {self.conversation_id}")
            # State will be loaded from DB on next message processing

    @workflow.query
    def get_metadata(self) -> dict:
        """Query workflow metadata (lightweight, in-memory only).

        Note: For full conversation state, use get_conversation_state_external()
        endpoint which loads from PostgreSQL outside the workflow.
        """
        return {
            "conversation_id": str(self.conversation_id) if self.conversation_id else None,
            "business_id": str(self.business_id) if self.business_id else None,
            "pending_message_count": len(self.pending_messages),
        }

    @workflow.query
    def get_conversation_id(self) -> str | None:
        """Query conversation ID."""
        return str(self.conversation_id) if self.conversation_id else None

    @workflow.query
    def get_pending_message_count(self) -> int:
        """Query number of pending messages."""
        return len(self.pending_messages)
