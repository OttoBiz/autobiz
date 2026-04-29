"""
Scenario 6 — Logistics Planning
================================
All three sub-scenarios start with a pre-seeded "payment confirmed" context
so the logistics agent has the right state to work from.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6A — Customer agrees delivery date  (Michael Chen / Junae Cosmetics)
  Flow  : Customer announces payment confirmed → provides address → agent
          proposes delivery date → customer agrees → agent acknowledges.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6B — Customer reschedules  (Emily Rodriguez / Donrey Fashion)
  Flow  : Agent proposes a date → customer says not available, proposes
          a later date → agent confirms the rescheduled date.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6C — Vendor receives logistics details  (David Wilson / Manny Gadgets)
  Flow  : Customer arranges delivery (address confirmed, date agreed) →
          a vendor actor polls the business inbox → should receive a
          notification with delivery details (address, time/date, cost).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run:
    python tests/test_logistics.py
    python tests/test_logistics.py --scenario 6b
    python tests/test_logistics.py --base-url http://my-server:8000
"""
import argparse
import asyncio
import os
import sys
import uuid

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from tests.shared.actors import TEST_MODEL, make_customer_agent, make_vendor_agent
from tests.shared.client import AutobizClient
from tests.shared.helpers import (
    evaluate,
    print_full_transcript,
    print_header,
    print_verdict,
    run_conversation,
    run_vendor_polling,
    seed_chat_history,
)

# ── 6A ─────────────────────────────────────────────────────────────────────────

CUSTOMER_6A    = "Michael Chen"
CUSTOMER_ID_6A = "00000000-0000-0000-0000-000000000003"
BUSINESS_6A    = "Junae Cosmetics"
BUSINESS_ID_6A = "00000000-0000-0000-0001-000000000002"
SCENARIO_6A    = "Scenario 6A – Customer Agrees Delivery Date (Junae Cosmetics)"

CRITERIA_6A = [
    "The agent suggested or mentioned a delivery date or estimated timeline.",
    "The customer confirmed / agreed to the proposed delivery date.",
    "The agent acknowledged the customer's confirmation.",
    "The customer's delivery address was referenced in the conversation.",
    "The customer was left knowing when to expect their order.",
]

# ── 6B ─────────────────────────────────────────────────────────────────────────

CUSTOMER_6B    = "Emily Rodriguez"
CUSTOMER_ID_6B = "00000000-0000-0000-0000-000000000004"
BUSINESS_6B    = "Donrey Fashion"
BUSINESS_ID_6B = "00000000-0000-0000-0001-000000000001"
SCENARIO_6B    = "Scenario 6B – Customer Reschedules Delivery (Donrey Fashion)"

CRITERIA_6B = [
    "The agent proposed an initial delivery date.",
    "The customer rejected the initial date and proposed a different (later) date.",
    "The agent accepted or confirmed the rescheduled date.",
    "The final confirmed date in the conversation is the one the customer chose.",
    "The rescheduling was handled smoothly without confusion.",
]

# ── 6C ─────────────────────────────────────────────────────────────────────────

CUSTOMER_6C    = "David Wilson"
CUSTOMER_ID_6C = "00000000-0000-0000-0000-000000000005"
BUSINESS_6C    = "Manny Gadgets"
BUSINESS_ID_6C = "00000000-0000-0000-0001-000000000003"
SCENARIO_6C    = "Scenario 6C – Vendor Receives Logistics Details (Manny Gadgets)"

CRITERIA_6C = [
    "Delivery was discussed between the customer and the agent.",
    "The customer provided or confirmed their delivery address.",
    "The agent communicated a delivery date or timeline to the customer.",
    "A logistics or order notification appeared in the vendor inbox.",
    "The vendor inbox message contained delivery details "
    "(address, date/time, or delivery cost).",
]


# ── Shared: seed payment context ───────────────────────────────────────────────


async def _seed_payment_context(
    client: AutobizClient,
    user_id: str,
    vendor_id: str,
    session_id: str,
    product: str,
    price: float,
    model: str,
) -> None:
    """
    Pre-populate Redis with a conversation where the customer has already
    agreed to buy the product and sent payment.  Logistics tests start
    from this confirmed-payment state.
    """
    print(f"\n[SETUP] Pre-seeding payment context: {product} at ${price}…")
    await seed_chat_history(
        client=client,
        user_id=user_id,
        vendor_id=vendor_id,
        session_id=session_id,
        seed_topics=[
            f"{product} — price ${price} and availability",
            f"customer agreed to buy {product} and will make bank transfer",
        ],
        model=model,
        turns_per_topic=2,
    )


# ── 6A simulation ──────────────────────────────────────────────────────────────


async def run_6a(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_6A,
        f"Customer: {CUSTOMER_6A} | Business: {BUSINESS_6A} | Customer agrees delivery date",
    )

    client  = AutobizClient(base_url)
    session = f"s6a-{uuid.uuid4().hex[:8]}"

    await _seed_payment_context(
        client, CUSTOMER_ID_6A, BUSINESS_ID_6A, session,
        product="Lipstick", price=14.99, model=model,
    )

    customer = make_customer_agent(
        customer_name=CUSTOMER_6A,
        business_name=BUSINESS_6A,
        model=model,
        scenario_prompt="""Payment for your Lipstick has been confirmed.
Now you need to arrange delivery.

YOUR JOURNEY:
1. Tell the agent payment is confirmed and ask about delivery arrangements.
2. Provide your delivery address when asked:
   "24 Adeola Odeku Street, Victoria Island, Lagos".
3. When the agent suggests a delivery date or timeline, AGREE to it
   (do not try to reschedule).
4. Ask if there's anything else needed.
5. Wrap up with a thank-you.

Set done=True after the delivery date is confirmed and you say goodbye.""",
    )

    transcript: list[dict] = []
    transcript = await run_conversation(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_6A,
        vendor_id=BUSINESS_ID_6A,
        session_id=session,
        opening_message=(
            "Great news — my payment for the Lipstick has been confirmed! "
            "How do we arrange delivery? When can I expect it?"
        ),
        max_turns=12,
        transcript=transcript,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_6A, transcript, CRITERIA_6A)
    print_verdict(verdict, SCENARIO_6A)
    return verdict


# ── 6B simulation ──────────────────────────────────────────────────────────────


async def run_6b(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_6B,
        f"Customer: {CUSTOMER_6B} | Business: {BUSINESS_6B} | Customer reschedules delivery date",
    )

    client  = AutobizClient(base_url)
    session = f"s6b-{uuid.uuid4().hex[:8]}"

    await _seed_payment_context(
        client, CUSTOMER_ID_6B, BUSINESS_ID_6B, session,
        product="Sneakers", price=50.0, model=model,
    )

    customer = make_customer_agent(
        customer_name=CUSTOMER_6B,
        business_name=BUSINESS_6B,
        model=model,
        scenario_prompt="""Your Sneakers payment is confirmed. You want delivery but
your schedule is very tight — you cannot accept the first date the agent suggests.

YOUR JOURNEY:
1. Tell the agent payment is confirmed and ask about delivery.
2. When the agent suggests a delivery date, say you are NOT available on that day.
   Say exactly: "I won't be available on that date. Can we schedule it
   for the following week instead?"
3. Once the agent proposes a new date, AGREE to it.
4. Ask for a quick confirmation summary.
5. Wrap up.

Set done=True after the rescheduled date is confirmed.""",
    )

    transcript: list[dict] = []
    transcript = await run_conversation(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_6B,
        vendor_id=BUSINESS_ID_6B,
        session_id=session,
        opening_message=(
            "Hi! My Sneakers payment has been confirmed. "
            "Let's sort out the delivery — what dates are available?"
        ),
        max_turns=14,
        transcript=transcript,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_6B, transcript, CRITERIA_6B)
    print_verdict(verdict, SCENARIO_6B)
    return verdict


# ── 6C simulation ──────────────────────────────────────────────────────────────


async def run_6c(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_6C,
        f"Customer: {CUSTOMER_6C} | Business: {BUSINESS_6C} | Vendor inbox receives logistics details",
    )

    client         = AutobizClient(base_url)
    session        = f"s6c-{uuid.uuid4().hex[:8]}"
    vendor_session = f"s6c-vend-{uuid.uuid4().hex[:8]}"

    await _seed_payment_context(
        client, CUSTOMER_ID_6C, BUSINESS_ID_6C, session,
        product="iPhone 12", price=999.0, model=model,
    )

    # ── Customer side ──────────────────────────────────────────────────────────
    customer = make_customer_agent(
        customer_name=CUSTOMER_6C,
        business_name=BUSINESS_6C,
        model=model,
        scenario_prompt="""Your iPhone 12 payment is confirmed. Arrange delivery.

YOUR JOURNEY:
1. Tell the agent payment is done and give your delivery address:
   "12 Allen Avenue, Ikeja, Lagos".
2. Agree to whatever delivery date the agent proposes.
3. Ask about delivery cost.
4. Once everything is confirmed, wrap up.

Set done=True after delivery date and cost are confirmed.""",
    )

    transcript: list[dict] = []
    transcript = await run_conversation(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_6C,
        vendor_id=BUSINESS_ID_6C,
        session_id=session,
        opening_message=(
            "My iPhone 12 payment was confirmed. Please arrange delivery to: "
            "12 Allen Avenue, Ikeja, Lagos."
        ),
        max_turns=12,
        transcript=transcript,
    )

    # ── Vendor side: poll inbox for logistics notification ─────────────────────
    print("\n[VENDOR] Starting inbox polling for logistics details…")

    vendor = make_vendor_agent(
        vendor_name=BUSINESS_6C,
        inventory_description=(
            "Phones and gadgets: iPhone 12 ($999), Samsung Galaxy S21 ($899), "
            "JBL Wireless Earbuds ($99), Apple AirPods Pro ($199), etc."
        ),
        payment_info=(
            "Customers pay via GTBank. Account: Manny Gadgets Ltd, 0011223344. "
            "Delivery handled through Express Logistics."
        ),
        model=model,
    )

    await run_vendor_polling(
        client=client,
        vendor_actor=vendor,
        vendor_id=BUSINESS_ID_6C,
        session_id=vendor_session,
        transcript=transcript,
        poll_interval=3.0,
        max_polls=15,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_6C, transcript, CRITERIA_6C)
    print_verdict(verdict, SCENARIO_6C)
    return verdict


# ── Entry-point ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scenario 6 – Logistics Planning")
    parser.add_argument("--base-url", default=os.environ.get("AUTOBIZ_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--model",    default=os.environ.get("TEST_MODEL", TEST_MODEL))
    parser.add_argument("--scenario", choices=["6a", "6b", "6c", "all"], default="all")
    args = parser.parse_args()

    async def main():
        verdicts = {}
        if args.scenario in ("6a", "all"):
            verdicts["6A"] = await run_6a(args.base_url, args.model)
        if args.scenario in ("6b", "all"):
            verdicts["6B"] = await run_6b(args.base_url, args.model)
        if args.scenario in ("6c", "all"):
            verdicts["6C"] = await run_6c(args.base_url, args.model)
        all_passed = all(v.passed for v in verdicts.values())
        print(f"\n{'─' * 60}")
        for name, v in verdicts.items():
            status = "✓ PASSED" if v.passed else "✗ FAILED"
            print(f"  Scenario {name}: {status}  (score={v.score:.2f})")
        return all_passed

    passed = asyncio.run(main())
    sys.exit(0 if passed else 1)
