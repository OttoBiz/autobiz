"""
Integration test for the main agent with real LLM (GPT-5.2).
Tests routing to correct subagents for various intents including mixed.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))

from backend.chatbot.agents.main_agent import (
    AgentDeps,
    SubagentDef,
    SUBAGENTS,
    agent,
)


# Mock handlers that return structured data and log which subagent was called
call_log: list[str] = []


async def mock_product(deps: AgentDeps, prompt: str) -> dict:
    call_log.append("product")
    return {
        "products": [
            {"name": "Leather Bag", "price": 15000, "stock": 3},
            {"name": "Canvas Bag", "price": 8000, "stock": 10},
            {"name": "Laptop Bag", "price": 22000, "stock": 0},
        ]
    }


async def mock_payment(deps: AgentDeps, prompt: str) -> dict:
    call_log.append("payment")
    return {"verified": True, "amount": 15000, "product": "Leather Bag"}


async def mock_logistics(deps: AgentDeps, prompt: str) -> dict:
    call_log.append("logistics")
    return {
        "order_id": "ORD-421",
        "order_number": "ORD-2026-0421",
        "status": "shipped",
        "tracking_number": "TRK-9912",
        "estimated_delivery": "2026-03-23",
    }


async def mock_customer_relation(deps: AgentDeps, prompt: str) -> dict:
    call_log.append("customer_relation")
    return {
        "action": "escalate_to_human",
        "reason": "Customer demands refund for defective product",
    }


async def mock_outbound(deps: AgentDeps, prompt: str) -> dict:
    call_log.append("outbound")
    return {"status": "vendor_contacted", "message": "Awaiting vendor confirmation on payment"}


# Wire mocks
SUBAGENTS["product"] = SubagentDef(SUBAGENTS["product"].description, mock_product)
SUBAGENTS["payment"] = SubagentDef(SUBAGENTS["payment"].description, mock_payment)
SUBAGENTS["logistics"] = SubagentDef(SUBAGENTS["logistics"].description, mock_logistics)
SUBAGENTS["customer_relation"] = SubagentDef(SUBAGENTS["customer_relation"].description, mock_customer_relation)
SUBAGENTS["outbound"] = SubagentDef(SUBAGENTS["outbound"].description, mock_outbound)


def extract_tool_calls(result) -> list[dict]:
    """Extract tool call details from message history."""
    from pydantic_ai.messages import ToolCallPart
    calls = []
    for msg in result.all_messages():
        for part in msg.parts:
            if isinstance(part, ToolCallPart) and part.tool_name == "query_subagent":
                args = part.args if isinstance(part.args, dict) else json.loads(part.args)
                tasks = args.get("tasks", [])
                calls.append({
                    "agents_called": [t["agent_name"] for t in tasks],
                    "prompts": [t["prompt"] for t in tasks],
                })
    return calls


async def run_test(label: str, message: str, deps: AgentDeps, expected_agents: list[str]):
    call_log.clear()
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"User: {message}")
    print(f"Expected agents: {expected_agents}")
    print(f"{'='*60}")

    result = await agent.run(message, deps=deps)

    tool_calls = extract_tool_calls(result)
    agents_called = []
    for tc in tool_calls:
        agents_called.extend(tc["agents_called"])
        for i, (a, p) in enumerate(zip(tc["agents_called"], tc["prompts"])):
            print(f"  Tool call: {a} → \"{p[:100]}\"")

    print(f"\nAgents routed to: {agents_called}")
    print(f"Handlers fired:   {call_log}")
    print(f"\nAgent response:\n  {result.output}")

    # Check routing
    match = set(expected_agents) == set(agents_called)
    status = "PASS" if match else "FAIL"
    if not match:
        print(f"\n  ⚠ Expected {expected_agents}, got {agents_called}")
    print(f"\nResult: {status}")
    return match


async def main():
    deps = AgentDeps(
        user_id="customer_123",
        business_id="business_456",
        state={
            "business": {"name": "ShopABC", "bank_name": "GTBank"},
            "processes": {
                "Leather Bag": {
                    "order_id": "ORD-421",
                    "order_number": "ORD-2026-0421",
                    "status": "shipped",
                }
            },
            "outbound": {},
        },
    )

    results = []

    # 1. Single intent: product enquiry
    results.append(await run_test(
        "Product enquiry",
        "What bags do you have available?",
        deps,
        ["product"],
    ))

    # 2. Single intent: logistics/tracking
    results.append(await run_test(
        "Order tracking",
        "Where is my order? I ordered a Leather Bag last week.",
        deps,
        ["logistics"],
    ))

    # 3. Single intent: complaint
    results.append(await run_test(
        "Customer complaint",
        "The bag I received is damaged and I want a refund!",
        deps,
        ["customer_relation"],
    ))

    # 4. Single intent: payment verification
    results.append(await run_test(
        "Payment verification",
        "I just paid 15000 naira to your GTBank account for the Leather Bag. Here is my receipt reference: TXN-88432",
        deps,
        ["payment"],
    ))

    # 5. Mixed intent: product + logistics
    results.append(await run_test(
        "Mixed: product + logistics",
        "Do you have Canvas Bags in stock? Also, where is my Leather Bag order?",
        deps,
        ["product", "logistics"],
    ))

    # 6. Mixed intent: complaint + product
    results.append(await run_test(
        "Mixed: complaint + product",
        "The Leather Bag I got is terrible quality. But I still need a Laptop Bag - do you have any?",
        deps,
        ["customer_relation", "product"],
    ))

    # 7. General greeting (should NOT call any subagent)
    call_log.clear()
    print(f"\n{'='*60}")
    print("TEST: General greeting (no subagent expected)")
    print("User: Hello! How are you?")
    print(f"{'='*60}")
    result = await agent.run("Hello! How are you?", deps=deps)
    tool_calls = extract_tool_calls(result)
    agents_called = []
    for tc in tool_calls:
        agents_called.extend(tc["agents_called"])
    print(f"Agents routed to: {agents_called}")
    print(f"Agent response:\n  {result.output}")
    no_subagent = len(agents_called) == 0
    print(f"Result: {'PASS' if no_subagent else 'FAIL'}")
    results.append(no_subagent)

    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY: {sum(results)}/{len(results)} passed")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
