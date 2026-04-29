"""
Simulated multi-turn conversation covering the full customer journey:
  1. Product enquiry  — customer asks for a product NOT in inventory.
  2. Outbound          — agent checks with vendor, vendor offers sourcing option.
  3. Purchase decision — customer agrees, asks how to pay.
  4. Payment           — customer sends payment, agent verifies.
  5. Logistics         — customer asks about delivery / provides address.

Actors:
  - customer_agent  : LLM playing the customer (structured output with done flag).
  - main_agent      : the real orchestrator, dispatches to subagents.
  - outbound_agent  : real agent, calls contact_vendor tool → vendor_agent.
  - vendor_agent    : LLM playing the business owner.

All external I/O (DB, Redis, images) is mocked. LLM calls are real.
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import logfire

sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))

from backend.chatbot.agents.main_agent import (
    SUBAGENTS,
    AgentDeps,
    SubagentDef,
)
from backend.chatbot.agents.main_agent import (
    agent as main_agent,
)
from backend.chatbot.agents.outbound import OutboundDeps, outbound_agent
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import KnownModelName

logfire.configure()

# ── Configuration ─────────────────────────────────────────────────────────────

MODEL: KnownModelName = "openai:gpt-5.2-chat-latest"

BUSINESS_NAME = "LuxeBags Nigeria"
CUSTOMER_NAME = "Adaeze"
REQUESTED_PRODUCT = "Red Crocodile Skin Handbag"

MOCK_INVENTORY = [
    {
        "id": "p1",
        "name": "Black Leather Tote",
        "price": 25000,
        "stock_quantity": 4,
        "category": "bags",
    },
    {
        "id": "p2",
        "name": "Brown Canvas Messenger",
        "price": 12000,
        "stock_quantity": 8,
        "category": "bags",
    },
]

MOCK_BUSINESS_INFO = {
    "id": "biz-001",
    "name": BUSINESS_NAME,
    "bank_name": "GTBank",
    "bank_account_name": "LuxeBags Nigeria Ltd",
    "bank_account_number": "0112233445",
}

MOCK_ORDER = {
    "id": "order-001",
    "order_number": "ORD-2026-0042",
    "status": "pending",
    "tracking_number": None,
    "delivery_address": None,
    "delivery_city": None,
    "delivery_state": None,
}

# ── Logging ───────────────────────────────────────────────────────────────────

conversation_log: list[dict[str, str]] = []


def log(role: str, message: str):
    conversation_log.append({"role": role, "message": message})
    label = {
        "customer": f"\033[96m[CUSTOMER] {CUSTOMER_NAME}\033[0m",
        "assistant": f"\033[93m[ASSISTANT] {BUSINESS_NAME} AI\033[0m",
        "vendor": f"\033[92m[VENDOR] {BUSINESS_NAME} Owner\033[0m",
        "outbound": "\033[95m[OUTBOUND AGENT]\033[0m",
        "system": "\033[90m[SYSTEM]\033[0m",
    }.get(role, f"[{role.upper()}]")
    print(f"\n{label}")
    print(f"  {message}")


# ── Customer agent ────────────────────────────────────────────────────────────


class CustomerReply(BaseModel):
    message: str = Field(description="The customer's reply message.")
    done: bool = Field(
        description="True if the customer has no more questions and is wrapping up "
        "(e.g. said goodbye, confirmed delivery details, everything is settled). "
        "False if they still have questions or actions to take."
    )


customer_agent = Agent(
    model=MODEL,
    output_type=CustomerReply,
    system_prompt=f"""You are {CUSTOMER_NAME}, a customer chatting with {BUSINESS_NAME} on WhatsApp.
You want to buy a {REQUESTED_PRODUCT}.

YOUR JOURNEY (follow this progression):
1. First, ask about the {REQUESTED_PRODUCT}.
2. If it's not available but can be sourced, agree to the sourcing option.
3. Ask how to pay. When given bank details, say you've made the transfer and provide a
   fake receipt reference (e.g. "TXN-NGN-78432").
4. After payment is acknowledged, ask about delivery — provide your address:
   "15 Admiralty Way, Lekki Phase 1, Lagos".
5. Once delivery is confirmed/noted, say thank you and wrap up.

RULES:
- Stay in character. Keep messages short and natural (1-3 sentences).
- Only set done=true after delivery details are settled and you're saying goodbye.
- Do NOT skip steps — go through enquiry → payment → delivery in order.""",
)


# ── Vendor agent ──────────────────────────────────────────────────────────────

vendor_agent = Agent(
    model=MODEL,
    system_prompt=f"""You are the owner of {BUSINESS_NAME}. An AI assistant is contacting you on behalf of a customer.

Your current inventory:
- Black Leather Tote: N25,000 (4 in stock)
- Brown Canvas Messenger: N12,000 (8 in stock)

You do NOT have the {REQUESTED_PRODUCT} in stock, but you can source it from a supplier
within 5-7 business days for N45,000.

Payment: Customers pay to your GTBank account (LuxeBags Nigeria Ltd, 0112233445).
Delivery: You use GIG Logistics for Lagos deliveries (2-3 business days after dispatch).

RULES:
- Reply concisely and professionally (1-3 sentences).
- Provide honest stock info and sourcing options.
- When asked about delivery, mention GIG Logistics and the timeline.""",
)

vendor_messages: list[Any] = []


# ── Wire vendor agent as a tool on the real outbound agent ────────────────────


@outbound_agent.tool
async def contact_vendor(
    ctx: RunContext[OutboundDeps],
    message: str = Field(description="Message to send to the vendor."),
) -> str:
    """Send a message to the vendor and get their reply. Use this to ask about stock, pricing, sourcing, delivery, etc."""
    global vendor_messages

    log("outbound", f"→ Vendor: {message}")

    vendor_result = await vendor_agent.run(message, message_history=vendor_messages)
    vendor_messages = vendor_result.all_messages()
    vendor_reply = vendor_result.output

    log("vendor", vendor_reply)

    return vendor_reply


# ── Outbound handler (real outbound agent) ────────────────────────────────────


async def test_handle_outbound(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    task_key = f"out-{uuid.uuid4().hex[:8]}"

    log("system", f"Outbound triggered → task_key={task_key}")
    log("system", f"Outbound prompt: {prompt[:200]}")

    outbound_deps = OutboundDeps(
        task_key=task_key,
        customer_id=deps.user_id,
        business_name=BUSINESS_NAME,
    )

    await outbound_agent.run(prompt, deps=outbound_deps)

    log(
        "outbound",
        f"Finished. Resolution: {json.dumps(outbound_deps.resolution, indent=2)}",
    )

    deps.outbound.append(outbound_deps)

    return {
        "status": outbound_deps.resolution.get("status", "pending"),
        "task_key": task_key,
        "vendor_response": outbound_deps.resolution.get("result", ""),
    }


# ── Mock DB that evolves with the conversation ───────────────────────────────
# After "payment verified", the order status updates to reflect real progression.

order_state = dict(MOCK_ORDER)  # mutable copy


async def mock_get_order_by_id(order_id: str):
    return order_state


async def mock_verify_payment(*args, **kwargs):
    """Simulate DEBUG=true so verify_payment_link returns verified."""
    return {"verified": True, "amount": 45000, "message": "Dev mode: assume verified"}


# ── Test version of outbound hook ────────────────────────────────────────────


async def test_notify_main_agent(outbound_deps: OutboundDeps) -> None:
    """Test version of notify_main_agent hook.

    In production, this would run the main agent to craft a proactive message
    and push it to the customer via WhatsApp. In tests, we log the hook firing.
    """
    log("system", f"[HOOK] notify_main_agent fired for task {outbound_deps.task_key}")
    logfire.info(
        "hook fired: notify_main_agent",
        task_key=outbound_deps.task_key,
        customer_id=outbound_deps.customer_id,
        resolution=outbound_deps.resolution,
    )


# ── Main conversation loop ───────────────────────────────────────────────────


async def run_conversation():
    print("\n" + "#" * 70)
    print("#  FULL JOURNEY SIMULATION")
    print("#  Customer: {CUSTOMER_NAME} | Store: {BUSINESS_NAME}")
    print("#  Phases: Product Enquiry → Payment → Logistics")
    print(f"#  Scenario: '{REQUESTED_PRODUCT}' is NOT in inventory (can be sourced)")
    print("#" * 70)

    # Wire outbound handler
    original_outbound = SUBAGENTS["outbound"]
    SUBAGENTS["outbound"] = SubagentDef(
        original_outbound.description,
        test_handle_outbound,
    )

    deps = AgentDeps(
        user_id="customer-ada-001",
        business_id="biz-001",
        state={
            "business_information": MOCK_BUSINESS_INFO,
            "processes": {},
        },
    )

    patches_map = {
        # Product agent
        "backend.chatbot.agents.product.get_products": AsyncMock(
            return_value=MOCK_INVENTORY
        ),
        "backend.chatbot.agents.product.get_product_images": AsyncMock(
            return_value=[]
        ),
        "backend.chatbot.agents.product.get_user_state": AsyncMock(
            return_value={"business_information": MOCK_BUSINESS_INFO}
        ),
        # Handlers
        "backend.chatbot.agents.handlers.get_business_info": AsyncMock(
            return_value=MOCK_BUSINESS_INFO
        ),
        # Logistics agent
        "backend.chatbot.agents.logistics.get_order_by_id": mock_get_order_by_id,
        # Outbound hook
        "backend.chatbot.agents.utils.notify_main_agent": test_notify_main_agent,
    }

    assistant_history: list[Any] = []
    customer_history: list[Any] = []

    opening = f"Hi! I'm looking for a {REQUESTED_PRODUCT}. Do you have one available?"

    active_patches = [patch(k, v) for k, v in patches_map.items()]
    for p in active_patches:
        p.start()

    # Also patch DEBUG env for payment verification
    env_patch = patch.dict("os.environ", {"DEBUG": "true"})
    env_patch.start()

    try:
        max_turns = 12
        customer_msg = opening
        phase_tracker: list[str] = []

        for turn in range(1, max_turns + 1):
            print(f"\n{'─' * 70}")
            print(f"  Turn {turn}")
            print(f"{'─' * 70}")

            # 1. Customer speaks
            log("customer", customer_msg)

            # 2. Build context for orchestrator
            outbound_context = ""
            for ob in deps.outbound:
                if ob.resolution:
                    outbound_context += f"\n[Outbound {ob.task_key} resolved]: {ob.resolution.get('result', '')}"

            # Inject order state if an order exists
            if deps.state.get("processes"):
                order_ctx = json.dumps(deps.state["processes"], indent=2)
                outbound_context += f"\n[Active orders]: {order_ctx}"

            full_prompt = customer_msg
            if outbound_context:
                full_prompt += f"\n\n--- SYSTEM CONTEXT ---{outbound_context}"

            # 3. Main agent responds
            result = await main_agent.run(
                full_prompt,
                deps=deps,
                message_history=assistant_history,
            )
            assistant_history = result.all_messages()
            assistant_reply = result.output

            log("assistant", assistant_reply)

            # Log tool calls and track phases
            from pydantic_ai.messages import ToolCallPart

            for msg in result.new_messages():
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        args = (
                            part.args
                            if isinstance(part.args, dict)
                            else json.loads(part.args)
                        )
                        log(
                            "system",
                            f"Tool: {part.tool_name} → {json.dumps(args, indent=2)[:300]}",
                        )

                        # Track which phases have been hit
                        if part.tool_name == "query_subagent":
                            for task in args.get("tasks", []):
                                agent_name = task.get("agent_name", "")
                                if agent_name not in phase_tracker:
                                    phase_tracker.append(agent_name)

            # After payment-related turn, simulate order creation in state
            if "payment" in phase_tracker and not deps.state["processes"]:
                deps.state["processes"][REQUESTED_PRODUCT] = {
                    "order_id": "order-001",
                    "order_number": "ORD-2026-0042",
                    "status": "payment_verified",
                }
                order_state["status"] = "payment_verified"
                log("system", "Order created in state after payment verification.")

            # 4. Customer agent replies
            customer_result = await customer_agent.run(
                f'The store assistant just said:\n\n"{assistant_reply}"\n\nReply as the customer.',
                message_history=customer_history,
            )
            customer_history = customer_result.all_messages()
            reply: CustomerReply = customer_result.output

            # 5. If customer is done, final exchange
            if reply.done:
                log("customer", reply.message)
                farewell = await main_agent.run(
                    reply.message,
                    deps=deps,
                    message_history=assistant_history,
                )
                assistant_history = farewell.all_messages()
                log("assistant", farewell.output)
                break

            customer_msg = reply.message

    finally:
        for p in active_patches:
            p.stop()
        env_patch.stop()
        SUBAGENTS["outbound"] = original_outbound

    # ── Print full transcript ─────────────────────────────────────────────
    print("\n\n" + "#" * 70)
    print("#  FULL TRANSCRIPT")
    print("#" * 70)
    for entry in conversation_log:
        role = entry["role"]
        tag = {
            "customer": "CUSTOMER",
            "assistant": "ASSISTANT",
            "vendor": "VENDOR",
            "outbound": "OUTBOUND",
            "system": "SYSTEM",
        }.get(role, role.upper())
        print(f"\n[{tag}] {entry['message']}")

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n\n" + "#" * 70)
    print("#  SUMMARY")
    print("#" * 70)
    customer_count = len([e for e in conversation_log if e["role"] == "customer"])
    assistant_count = len([e for e in conversation_log if e["role"] == "assistant"])
    print(f"#  Turns: {customer_count} customer / {assistant_count} assistant messages")
    print(f"#  Phases hit: {phase_tracker}")
    print(f"#  Outbound tasks: {len(deps.outbound)}")
    for ob in deps.outbound:
        print(f"#    - {ob.task_key}: {ob.resolution.get('status', 'pending')}")
    print(
        f"#  Final order state: {json.dumps(deps.state.get('processes', {}), indent=2)}"
    )

    # Phase coverage check
    expected_phases = {"product", "payment", "logistics"}
    covered = expected_phases & set(phase_tracker)
    missing = expected_phases - covered
    if missing:
        print(f"#  ⚠ Missing phases: {missing}")
    else:
        print(f"#  ✓ All phases covered: {covered}")
    print("#" * 70)


if __name__ == "__main__":
    asyncio.run(run_conversation())
