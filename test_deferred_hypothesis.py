"""
Hypothesis test: Temporal workflow handling deferred tool interruptions.

Demonstrates a Temporal-style workflow where:
1. User sends a message → agent defers a tool call (e.g., external lookup)
2. While waiting for the deferred result, user sends a NEW message (interruption)
3. Workflow handles the interruption, then resumes the deferred tool flow

Pattern: strip pending tool call → handle interrupt → re-inject tool call → send deferred result
"""

import asyncio
import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import (
    Agent,
    CallDeferred,
    DeferredToolRequests,
    DeferredToolResults,
)
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# -- Agent setup --

agent = Agent("openai:gpt-4o", output_type=[str, DeferredToolRequests])


@agent.tool_plain
def lookup_order(order_id: str) -> str:
    """Look up order details by order ID. This is an external system call."""
    log.info(f"[TOOL] lookup_order called with order_id={order_id!r} -- deferring")
    raise CallDeferred(metadata={"order_id": order_id})


# -- Workflow state (mirrors what Temporal would persist) --


@dataclass
class PendingDeferral:
    """A parked deferred tool request waiting to be resolved."""

    deferred_requests: DeferredToolRequests
    tool_call_message: ModelResponse  # The ModelResponse containing the ToolCallPart


@dataclass
class ChatWorkflowState:
    """
    State that a Temporal workflow would hold.

    In a real Temporal workflow, this would be the workflow's instance state,
    persisted across signals/updates via event sourcing.
    """

    messages: list[ModelMessage] = field(default_factory=list)
    pending_deferrals: list[PendingDeferral] = field(default_factory=list)


# -- Workflow logic (simulating Temporal signal/update handlers) --


def strip_pending_tool_calls(
    messages: list[ModelMessage],
) -> tuple[list[ModelMessage], ModelResponse | None]:
    """
    Strip the trailing ModelResponse if it contains only unprocessed ToolCallParts.
    Returns (cleaned_messages, stripped_message_or_None).
    """
    cleaned = list(messages)  # shallow copy is fine, we only pop
    stripped: ModelResponse | None = None
    if cleaned and isinstance(cleaned[-1], ModelResponse):
        last = cleaned[-1]
        if all(isinstance(p, ToolCallPart) for p in last.parts):
            stripped = cleaned.pop()  # type: ignore[assignment]
            log.info(f"Stripped pending tool call message with {len(last.parts)} call(s)")
    return cleaned, stripped


async def handle_user_message(
    state: ChatWorkflowState, user_message: str
) -> str:
    """
    Simulate Temporal @workflow.signal / @workflow.update for a new user message.

    If there are pending deferrals, park them and handle the new message on clean history.
    """
    log.info(f">> handle_user_message: {user_message!r}")

    if state.pending_deferrals:
        log.info(
            f"   Parking {len(state.pending_deferrals)} pending deferral(s) to handle interruption"
        )
        # Strip pending tool call from history so we can send a new prompt
        cleaned, _ = strip_pending_tool_calls(state.messages)
        state.messages = cleaned

    result = await agent.run(user_message, message_history=state.messages)
    state.messages = list(result.all_messages())

    if isinstance(result.output, DeferredToolRequests):
        # New message also triggered a deferral
        tool_call_msg = state.messages[-1]
        assert isinstance(tool_call_msg, ModelResponse)
        state.pending_deferrals.append(
            PendingDeferral(
                deferred_requests=result.output,
                tool_call_message=tool_call_msg,
            )
        )
        return f"[DEFERRED] Tool call deferred: {[c.tool_name for c in result.output.calls]}"

    return result.output  # type: ignore[return-value]


async def handle_initial_request(
    state: ChatWorkflowState, user_message: str
) -> str:
    """First message — may trigger a deferred tool."""
    log.info(f">> handle_initial_request: {user_message!r}")

    result = await agent.run(user_message, message_history=state.messages)
    state.messages = list(result.all_messages())

    if isinstance(result.output, DeferredToolRequests):
        tool_call_msg = state.messages[-1]
        assert isinstance(tool_call_msg, ModelResponse)
        state.pending_deferrals.append(
            PendingDeferral(
                deferred_requests=result.output,
                tool_call_message=tool_call_msg,
            )
        )
        return f"[DEFERRED] Tool call deferred: {[c.tool_name for c in result.output.calls]}"

    return result.output  # type: ignore[return-value]


async def handle_deferred_result(
    state: ChatWorkflowState,
    results: dict[str, Any],
) -> str:
    """
    Simulate Temporal @workflow.signal for receiving deferred tool results.

    Re-injects the parked tool call into history, then sends the deferred results.
    """
    log.info(f">> handle_deferred_result: {len(results)} result(s)")

    if not state.pending_deferrals:
        log.warning("   No pending deferrals to resolve!")
        return "[ERROR] No pending deferrals"

    # Pop the oldest pending deferral (FIFO)
    deferral = state.pending_deferrals.pop(0)

    # Re-inject the tool call ModelResponse into the current history
    state.messages.append(deferral.tool_call_message)
    log.info(f"   Re-injected tool call message into history (now {len(state.messages)} messages)")

    # Build DeferredToolResults
    deferred_results = DeferredToolResults()
    for call in deferral.deferred_requests.calls:
        if call.tool_call_id in results:
            deferred_results.calls[call.tool_call_id] = results[call.tool_call_id]
        else:
            deferred_results.calls[call.tool_call_id] = f"No result provided for {call.tool_call_id}"

    result = await agent.run(
        message_history=state.messages,
        deferred_tool_results=deferred_results,
    )
    state.messages = list(result.all_messages())

    if isinstance(result.output, DeferredToolRequests):
        return f"[DEFERRED AGAIN] {result.output}"

    return result.output  # type: ignore[return-value]


# -- Main: simulate the full flow --


async def main():
    state = ChatWorkflowState()

    # == Step 1: User asks about order → triggers deferred tool ==
    log.info("=" * 70)
    log.info("STEP 1: Initial request (triggers deferred tool)")
    log.info("=" * 70)

    resp1 = await handle_initial_request(state, "What is the status of order #12345?")
    log.info(f"Response: {resp1}")
    log.info(f"Pending deferrals: {len(state.pending_deferrals)}")
    log.info(f"Message count: {len(state.messages)}")

    # == Step 2: User interrupts with a different question ==
    log.info("")
    log.info("=" * 70)
    log.info("STEP 2: User interrupts with a new question (while tool is deferred)")
    log.info("=" * 70)

    resp2 = await handle_user_message(state, "Actually, what is 2 + 2?")
    log.info(f"Response: {resp2}")
    log.info(f"Pending deferrals: {len(state.pending_deferrals)}")
    log.info(f"Message count: {len(state.messages)}")

    # == Step 3: Deferred tool result arrives ==
    log.info("")
    log.info("=" * 70)
    log.info("STEP 3: Deferred tool result arrives (re-inject + resolve)")
    log.info("=" * 70)

    # Simulate the external system returning the order data
    tool_call_id = state.pending_deferrals[0].deferred_requests.calls[0].tool_call_id
    resp3 = await handle_deferred_result(
        state,
        {tool_call_id: "Order #12345: Shipped 2026-03-20, ETA 2026-03-23"},
    )
    log.info(f"Response: {resp3}")
    log.info(f"Pending deferrals: {len(state.pending_deferrals)}")
    log.info(f"Message count: {len(state.messages)}")

    # == Final history dump ==
    log.info("")
    log.info("=" * 70)
    log.info("FINAL MESSAGE HISTORY")
    log.info("=" * 70)
    for i, msg in enumerate(state.messages):
        if isinstance(msg, ModelRequest):
            parts_summary = ", ".join(type(p).__name__ + ": " + str(getattr(p, 'content', getattr(p, 'tool_name', '?')))[:60] for p in msg.parts)
        elif isinstance(msg, ModelResponse):
            parts_summary = ", ".join(type(p).__name__ + ": " + str(getattr(p, 'content', getattr(p, 'tool_name', '?')))[:60] for p in msg.parts)
        else:
            parts_summary = str(msg)[:80]
        log.info(f"  [{i}] {type(msg).__name__}: {parts_summary}")

    log.info("")
    log.info("=" * 70)
    log.info("CONCLUSION")
    log.info("=" * 70)
    log.info("The Temporal-style workflow successfully:")
    log.info("  1. Parked the deferred tool call when an interruption arrived")
    log.info("  2. Handled the interrupting message on clean history")
    log.info("  3. Re-injected the parked tool call and resolved it with deferred results")
    log.info("  4. The agent produced a coherent answer from the deferred tool data")


if __name__ == "__main__":
    asyncio.run(main())
