"""
Scenario 2 — Product Not Available
=====================================
Two sub-scenarios with different customer + business pairs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2A — Wrong product attribute  (Kemi Surprises / Sarah Johnson)
  Pre-history : 2 warm-up turns about Trousers (to test history handling)
  Request     : "Blue Shirt, size M"  — only XL Blue and M Black exist.
  Expected    : Agent recognises exact match unavailable, suggests closest
                alternatives clearly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2B — Product does not exist at all  (Manny Gadgets / Michael Chen)
  Pre-history : 3 turns about iPhone 12 (DIFFERENT product type)
  Request     : "Diamond Ring"
  Expected    : Agent clearly states unavailability; does not fabricate info;
                prior iPhone history does not bleed into the Diamond Ring answer.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run:
    python tests/test_product_unavailable.py
    python tests/test_product_unavailable.py --scenario 2a
    python tests/test_product_unavailable.py --scenario 2b
    python tests/test_product_unavailable.py --base-url http://my-server:8000
"""
import argparse
import asyncio
import os
import sys
import uuid

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from tests.shared.actors import TEST_MODEL, make_customer_agent
from tests.shared.client import AutobizClient
from tests.shared.helpers import (
    evaluate,
    print_full_transcript,
    print_header,
    print_verdict,
    run_conversation,
    seed_chat_history,
)

# ── Scenario 2A ───────────────────────────────────────────────────────────────

CUSTOMER_2A    = "Sarah Johnson"
CUSTOMER_ID_2A = "00000000-0000-0000-0000-000000000002"
BUSINESS_2A    = "Kemi Surprises"
BUSINESS_ID_2A = "00000000-0000-0000-0001-000000000005"
SCENARIO_2A    = "Scenario 2A – Wrong Attribute (Kemi Surprises / Blue Shirt size M)"

CRITERIA_2A = [
    "The agent acknowledged that the exact combination (Blue Shirt, size M) is not available.",
    "The agent suggested at least one similar alternative (e.g. different size or different colour shirt).",
    "The agent described the available alternative clearly (colour, size, or price).",
    "The agent did not just say 'we don't have it' without offering an alternative.",
    "Prior history about Trousers was present in the conversation but did not prevent the agent from addressing the Shirt request.",
]

# ── Scenario 2B ───────────────────────────────────────────────────────────────

CUSTOMER_2B    = "Michael Chen"
CUSTOMER_ID_2B = "00000000-0000-0000-0000-000000000003"
BUSINESS_2B    = "Manny Gadgets"
BUSINESS_ID_2B = "00000000-0000-0000-0001-000000000003"
SCENARIO_2B    = "Scenario 2B – Product Not Available at All (Manny Gadgets / Diamond Ring)"

CRITERIA_2B = [
    "The agent clearly stated Diamond Ring is not available.",
    "The agent did not fabricate product info or claim to have a Diamond Ring.",
    "The agent either suggested alternatives in their actual category (phones/gadgets) or politely offered to help with something else.",
    "The agent was professional and empathetic.",
    "The prior iPhone 12 conversation in the history did not confuse the agent's Diamond Ring response.",
]


# ── Scenario 2A simulation ─────────────────────────────────────────────────────


async def run_2a(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_2A,
        f"Customer: {CUSTOMER_2A} | Business: {BUSINESS_2A} | Pre-seeded: Trousers history",
    )

    client  = AutobizClient(base_url)
    session = f"s2a-{uuid.uuid4().hex[:8]}"

    # Build 2 turns of prior history about Trousers
    print("\n[SETUP] Pre-seeding 2 turns about black formal Trousers…")
    await seed_chat_history(
        client=client,
        user_id=CUSTOMER_ID_2A,
        vendor_id=BUSINESS_ID_2A,
        session_id=session,
        seed_topics=["black formal trousers — size and price"],
        model=model,
        turns_per_topic=2,
    )

    customer = make_customer_agent(
        customer_name=CUSTOMER_2A,
        business_name=BUSINESS_2A,
        model=model,
        scenario_prompt="""You were asking about trousers earlier, but now you specifically want a shirt.

YOUR JOURNEY:
1. Ask for a Blue Shirt in size M specifically.
2. If told that exact combination is unavailable, ask what shirt options they do have.
3. Find out what Blue shirts or Medium-size shirts are available.
4. Once you understand the alternatives, say you'll think about it and wrap up.

Set done=True after the agent explains available shirt options.""",
    )

    transcript: list[dict] = []
    transcript = await run_conversation(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_2A,
        vendor_id=BUSINESS_ID_2A,
        session_id=session,
        opening_message="Hi! I want a Blue Shirt in size M specifically. Do you have that?",
        max_turns=12,
        transcript=transcript,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_2A, transcript, CRITERIA_2A)
    print_verdict(verdict, SCENARIO_2A)
    return verdict


# ── Scenario 2B simulation ─────────────────────────────────────────────────────


async def run_2b(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_2B,
        f"Customer: {CUSTOMER_2B} | Business: {BUSINESS_2B} | Pre-seeded: iPhone 12 history",
    )

    client  = AutobizClient(base_url)
    session = f"s2b-{uuid.uuid4().hex[:8]}"

    # Build 3 turns of prior history about iPhone 12 (a product Manny Gadgets HAS)
    print("\n[SETUP] Pre-seeding 3 turns about iPhone 12…")
    await seed_chat_history(
        client=client,
        user_id=CUSTOMER_ID_2B,
        vendor_id=BUSINESS_ID_2B,
        session_id=session,
        seed_topics=["iPhone 12 price and availability"],
        model=model,
        turns_per_topic=3,
    )

    customer = make_customer_agent(
        customer_name=CUSTOMER_2B,
        business_name=BUSINESS_2B,
        model=model,
        scenario_prompt="""You have been asking about iPhones, but now you want jewellery.

YOUR JOURNEY:
1. Ask if they sell Diamond Rings.
2. If they say no, ask if they have any jewellery at all.
3. Accept the response and wrap up politely.

Set done=True after the agent responds to your Diamond Ring question.""",
    )

    transcript: list[dict] = []
    transcript = await run_conversation(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_2B,
        vendor_id=BUSINESS_ID_2B,
        session_id=session,
        opening_message="Actually, do you sell Diamond Rings? I need one as a gift.",
        max_turns=8,
        transcript=transcript,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_2B, transcript, CRITERIA_2B)
    print_verdict(verdict, SCENARIO_2B)
    return verdict


# ── Entry-point ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scenario 2 – Product Not Available")
    parser.add_argument("--base-url", default=os.environ.get("AUTOBIZ_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--model",    default=os.environ.get("TEST_MODEL", TEST_MODEL))
    parser.add_argument("--scenario", choices=["2a", "2b", "all"], default="all")
    args = parser.parse_args()

    async def main():
        verdicts = {}
        if args.scenario in ("2a", "all"):
            verdicts["2A"] = await run_2a(args.base_url, args.model)
        if args.scenario in ("2b", "all"):
            verdicts["2B"] = await run_2b(args.base_url, args.model)
        all_passed = all(v.passed for v in verdicts.values())
        print(f"\n{'─' * 60}")
        for name, v in verdicts.items():
            status = "✓ PASSED" if v.passed else "✗ FAILED"
            print(f"  Scenario {name}: {status}  (score={v.score:.2f})")
        return all_passed

    passed = asyncio.run(main())
    sys.exit(0 if passed else 1)
