"""
End-to-end agent invocation script.
Calls each agent with real LLM, mocking only external I/O (DB, Redis, central agent).
Covers: main agent routing, product, payment, logistics, complaint, and outbound agents.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))

from backend.chatbot.agents.main_agent import (
    AgentDeps,
    SubagentDef,
    SUBAGENTS,
    agent as main_agent,
)
from backend.chatbot.agents.outbound import OutboundDeps, outbound_agent
from backend.chatbot.agents.product import product_agent
from backend.chatbot.agents.payment import payment_verification_agent
from backend.chatbot.agents.logistics import logistics_agent
from backend.chatbot.agents.customer_relation import customer_complaint_agent


# ── Helpers ──────────────────────────────────────────────────────────────────


def extract_tool_calls(result, tool_name: str = None) -> list[dict]:
    """Extract tool call details from message history."""
    from pydantic_ai.messages import ToolCallPart

    calls = []
    for msg in result.all_messages():
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                if tool_name and part.tool_name != tool_name:
                    continue
                args = part.args if isinstance(part.args, dict) else json.loads(part.args)
                calls.append({"tool_name": part.tool_name, "args": args})
    return calls


def print_result(label: str, result, extra: str = ""):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  Response: {result.output[:500]}")
    tool_calls = extract_tool_calls(result)
    if tool_calls:
        print(f"  Tool calls ({len(tool_calls)}):")
        for tc in tool_calls:
            args_str = json.dumps(tc["args"], indent=2)[:200]
            print(f"    - {tc['tool_name']}: {args_str}")
    if extra:
        print(f"  {extra}")
    print()


# ── Mock data ────────────────────────────────────────────────────────────────

MOCK_PRODUCTS = [
    {
        "id": "prod-001",
        "name": "Leather Bag",
        "price": 15000,
        "stock_quantity": 5,
        "category": "bags",
        "description": "Premium leather bag",
    },
    {
        "id": "prod-002",
        "name": "Canvas Bag",
        "price": 8000,
        "stock_quantity": 12,
        "category": "bags",
        "description": "Durable canvas bag",
    },
]

MOCK_ORDER = {
    "id": "order-001",
    "order_number": "ORD-2026-0421",
    "status": "shipped",
    "tracking_number": "TRK-9912",
    "delivery_address": "12 Lagos Street",
    "delivery_city": "Lagos",
    "delivery_state": "Lagos",
}

MOCK_BUSINESS_INFO = {
    "id": "business_456",
    "name": "ShopABC",
    "bank_name": "GTBank",
    "bank_account_name": "Shop ABC Ltd",
    "bank_account_number": "0123456789",
}


def make_deps(**overrides) -> AgentDeps:
    defaults = dict(
        user_id="customer_123",
        business_id="business_456",
        chat_history=[],
        state={
            "business_information": MOCK_BUSINESS_INFO,
            "processes": {
                "Leather Bag": {
                    "order_id": "order-001",
                    "order_number": "ORD-2026-0421",
                    "status": "shipped",
                }
            },
        },
    )
    defaults.update(overrides)
    return AgentDeps(**defaults)


# ── 1. Main agent routing (mock handlers) ────────────────────────────────────


async def test_main_agent_routing():
    """Test main agent routes to correct subagents with mocked handlers."""
    print("\n" + "=" * 70)
    print("  MAIN AGENT — ROUTING TESTS (mock handlers, real LLM)")
    print("=" * 70)

    call_log: list[str] = []

    async def mock_handler(name):
        async def handler(deps, prompt):
            call_log.append(name)
            return {"response": f"[{name}] handled: {prompt[:60]}"}
        return handler

    # Wire mock handlers
    original = dict(SUBAGENTS)
    for name in ["product", "payment", "logistics", "customer_relation", "outbound"]:
        fn = await mock_handler(name)
        SUBAGENTS[name] = SubagentDef(original[name].description, fn)

    scenarios = [
        ("Product enquiry", "What bags do you sell?", ["product"]),
        ("Order tracking", "Where is my Leather Bag order?", ["logistics"]),
        ("Customer complaint", "My bag arrived damaged, I want a refund!", ["customer_relation"]),
        ("Payment verification", "I just paid 15000 to your GTBank for the Leather Bag. Ref: TXN-88432", ["payment"]),
        ("Mixed: product + logistics", "Do you have Canvas Bags? Also where is my Leather Bag order?", ["product", "logistics"]),
        ("Outbound request", "Can you check with the vendor if they have the red version in stock?", ["outbound"]),
        ("General greeting", "Hello! How are you today?", []),
    ]

    deps = make_deps()
    results = []

    for label, message, expected in scenarios:
        call_log.clear()
        result = await main_agent.run(message, deps=deps)

        tool_calls = extract_tool_calls(result, "query_subagent")
        agents_called = []
        for tc in tool_calls:
            agents_called.extend(t["agent_name"] for t in tc["args"].get("tasks", []))

        match = set(expected) == set(agents_called)
        status = "PASS" if match else "FAIL"
        results.append(match)

        print(f"\n  [{status}] {label}")
        print(f"    User: {message}")
        print(f"    Expected: {expected} | Got: {agents_called}")
        print(f"    Response: {result.output[:150]}")
        if not match:
            print(f"    ⚠ MISMATCH")

    # Restore original handlers
    SUBAGENTS.update(original)

    passed = sum(results)
    print(f"\n  Routing: {passed}/{len(results)} passed")
    return passed, len(results)


# ── 2. Product agent ─────────────────────────────────────────────────────────


async def test_product_agent():
    """Invoke product agent with real LLM, mocked DB."""
    print("\n" + "=" * 70)
    print("  PRODUCT AGENT — Real LLM invocation")
    print("=" * 70)

    deps = make_deps()

    with patch("backend.chatbot.agents.product.get_products", new_callable=AsyncMock) as mock_get, \
         patch("backend.chatbot.agents.product.get_product_images", new_callable=AsyncMock) as mock_img, \
         patch("backend.chatbot.agents.product.get_user_state", new_callable=AsyncMock) as mock_state:

        mock_get.return_value = MOCK_PRODUCTS
        mock_img.return_value = ["https://example.com/bag.jpg"]
        mock_state.return_value = {"business_information": MOCK_BUSINESS_INFO}

        # Enquiry
        result = await product_agent.run(
            "What bags do you have available? I'm looking for something premium.",
            deps=deps,
        )
        print_result("Product enquiry", result)

        # Purchase intent
        result2 = await product_agent.run(
            "I want to buy the Leather Bag. How do I pay?",
            deps=deps,
        )
        print_result("Purchase intent", result2)


# ── 3. Payment verification agent ────────────────────────────────────────────


async def test_payment_agent():
    """Invoke payment verification agent with real LLM."""
    print("\n" + "=" * 70)
    print("  PAYMENT VERIFICATION AGENT — Real LLM invocation")
    print("=" * 70)

    deps = make_deps()

    # Payment link verification
    result = await payment_verification_agent.run(
        "I paid 15000 naira via Paystack for the Leather Bag. Transaction ref: PAY-12345.",
        deps=deps,
    )
    print_result("Payment link verification", result)

    # Receipt-based payment
    result2 = await payment_verification_agent.run(
        "I transferred 8000 naira to GTBank account 0123456789 for the Canvas Bag. Here is my receipt.",
        deps=deps,
    )
    print_result("Receipt-based payment", result2)


# ── 4. Logistics agent ───────────────────────────────────────────────────────


async def test_logistics_agent():
    """Invoke logistics agent with real LLM, mocked DB."""
    print("\n" + "=" * 70)
    print("  LOGISTICS AGENT — Real LLM invocation")
    print("=" * 70)

    deps = make_deps()

    with patch("backend.chatbot.agents.logistics.get_order_by_id", new_callable=AsyncMock) as mock_order:

        mock_order.return_value = MOCK_ORDER

        # Track order
        result = await logistics_agent.run(
            "Where is my Leather Bag order? When will it arrive?",
            deps=deps,
        )
        print_result("Order tracking", result)

        # Delivery address collection
        result2 = await logistics_agent.run(
            "My delivery address is 15 Victoria Island, Lagos.",
            deps=deps,
        )
        print_result("Delivery address", result2)


# ── 5. Customer complaint agent ──────────────────────────────────────────────


async def test_complaint_agent():
    """Invoke customer complaint agent with real LLM."""
    print("\n" + "=" * 70)
    print("  CUSTOMER COMPLAINT AGENT — Real LLM invocation")
    print("=" * 70)

    deps = make_deps()

    # Simple complaint
    result = await customer_complaint_agent.run(
        "The Leather Bag I received has a broken zipper. This is unacceptable!",
        deps=deps,
    )
    print_result("Product complaint", result)

    # Refund demand (should escalate)
    result2 = await customer_complaint_agent.run(
        "I want a full refund immediately. The product is defective.",
        deps=deps,
    )
    print_result("Refund demand (expect escalation)", result2)


# ── 6. Outbound agent ────────────────────────────────────────────────────────


async def test_outbound_agent():
    """Invoke outbound agent directly with real LLM. Verify mark_completed is called."""
    print("\n" + "=" * 70)
    print("  OUTBOUND AGENT — Real LLM invocation")
    print("=" * 70)

    outbound_deps = OutboundDeps(
        task_key="out-test001",
        customer_id="customer_123",
        business_name="ShopABC",
    )

    result = await outbound_agent.run(
        "Customer customer_123 wants to know if the red Leather Bag is available. "
        "Please check with the vendor and confirm stock availability.",
        deps=outbound_deps,
    )
    print_result("Outbound: vendor stock check", result,
                 extra=f"Resolution: {outbound_deps.resolution}")

    # Verify mark_completed was called
    tool_calls = extract_tool_calls(result, "mark_completed")
    if tool_calls:
        print(f"  ✓ mark_completed called with: {json.dumps(tool_calls[0]['args'], indent=2)[:300]}")
    else:
        print(f"  ⚠ mark_completed was NOT called")

    if outbound_deps.resolution:
        print(f"  ✓ Resolution written: status={outbound_deps.resolution.get('status')}")
    else:
        print(f"  ⚠ Resolution is empty")


# ── 7. Outbound via handler (fire-and-forget flow) ───────────────────────────


async def test_outbound_handler_flow():
    """Test the full outbound handler flow: fire-and-forget, then check resolution."""
    print("\n" + "=" * 70)
    print("  OUTBOUND HANDLER — Fire-and-forget flow")
    print("=" * 70)

    from backend.chatbot.agents.handlers import handle_outbound

    deps = make_deps()

    with patch("backend.chatbot.agents.handlers.get_business_info", new_callable=AsyncMock) as mock_biz:
        mock_biz.return_value = MOCK_BUSINESS_INFO

        result = await handle_outbound(deps, "Check if vendor has red Leather Bag in stock.")

    print(f"  Immediate result: {result}")
    assert result["status"] == "pending", f"Expected pending, got {result['status']}"
    print(f"  ✓ Returns immediately with status=pending, task_key={result['task_key']}")

    # Wait for the background task to finish
    print(f"  Waiting for background outbound task to complete...")
    await asyncio.sleep(15)

    # Check resolution on the outbound deps
    outbound_dep = deps.outbound[0]
    print(f"  Outbound deps resolution: {outbound_dep.resolution}")
    if outbound_dep.resolution:
        print(f"  ✓ Background task completed: status={outbound_dep.resolution.get('status')}")
    else:
        print(f"  ⚠ Background task may still be running (resolution empty)")


# ── 8. Full trajectory: main agent → subagent → response ─────────────────────


async def test_full_trajectory():
    """End-to-end: main agent dispatches to real subagents (with mocked DB)."""
    print("\n" + "=" * 70)
    print("  FULL TRAJECTORY — Main agent → real subagent → response")
    print("=" * 70)

    deps = make_deps()

    with patch("backend.chatbot.agents.product.get_products", new_callable=AsyncMock) as mock_get, \
         patch("backend.chatbot.agents.product.get_product_images", new_callable=AsyncMock) as mock_img, \
         patch("backend.chatbot.agents.product.get_user_state", new_callable=AsyncMock) as mock_state:

        mock_get.return_value = MOCK_PRODUCTS
        mock_img.return_value = ["https://example.com/bag.jpg"]
        mock_state.return_value = {"business_information": MOCK_BUSINESS_INFO}

        result = await main_agent.run(
            "What bags do you have for sale? I need something under 10000 naira.",
            deps=deps,
        )

        print_result("Full trajectory: product enquiry via main agent", result)

        # Check that query_subagent was called with product
        tool_calls = extract_tool_calls(result, "query_subagent")
        agents_used = []
        for tc in tool_calls:
            agents_used.extend(t["agent_name"] for t in tc["args"].get("tasks", []))
        print(f"  Agents dispatched: {agents_used}")


# ── Runner ────────────────────────────────────────────────────────────────────


async def main():
    print("\n" + "#" * 70)
    print("#  AGENT INVOCATION TESTS — End-to-End with Real LLM")
    print("#" * 70)

    totals = {"passed": 0, "total": 0}

    # 1. Main agent routing
    passed, total = await test_main_agent_routing()
    totals["passed"] += passed
    totals["total"] += total

    # 2-5. Individual agent invocations
    await test_product_agent()
    await test_payment_agent()
    await test_logistics_agent()
    await test_complaint_agent()

    # 6. Outbound agent direct
    await test_outbound_agent()

    # 7. Outbound handler flow
    await test_outbound_handler_flow()

    # 8. Full trajectory
    await test_full_trajectory()

    print("\n" + "#" * 70)
    print(f"#  ROUTING SUMMARY: {totals['passed']}/{totals['total']} passed")
    print(f"#  All agent invocations completed. Review outputs above.")
    print("#" * 70)


if __name__ == "__main__":
    asyncio.run(main())
