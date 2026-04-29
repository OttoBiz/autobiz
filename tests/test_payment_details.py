"""
Scenario 3 & 4 — Payment Details
====================================

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scenario 3 — Bank details fetched from DB  (Emily Rodriguez / Tesla Tech)
  Flow  : Customer enquires about Laptop → confirms purchase intent →
          asks how to pay → agent returns real bank details from the DB.
  Judge : bank name + account number + account name all present.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scenario 4 — Payment link not available  (David Wilson / Junae Cosmetics)
  Flow  : Customer explicitly asks for a Paystack / online payment link →
          not configured → agent handles gracefully and offers an alternative.
  Judge : link unavailable acknowledged; alternative method offered; no crash.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run:
    python tests/test_payment_details.py
    python tests/test_payment_details.py --scenario 3
    python tests/test_payment_details.py --base-url http://my-server:8000
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
)

# ── Scenario 3 ─────────────────────────────────────────────────────────────────

CUSTOMER_3    = "Emily Rodriguez"
CUSTOMER_ID_3 = "00000000-0000-0000-0000-000000000004"
BUSINESS_3    = "Tesla Tech"
BUSINESS_ID_3 = "00000000-0000-0000-0001-000000000004"
PRODUCT_3     = "Laptop"
SCENARIO_3    = "Scenario 3 – Bank Details from DB (Tesla Tech / Laptop)"

CRITERIA_3 = [
    "The agent confirmed Laptop availability and provided the price.",
    "When the customer asked how to pay, the agent provided bank transfer details.",
    "The response included a bank name.",
    "The response included an account number.",
    "The response included an account name.",
    "The payment instructions were clear and actionable.",
]

# ── Scenario 4 ─────────────────────────────────────────────────────────────────

CUSTOMER_4    = "David Wilson"
CUSTOMER_ID_4 = "00000000-0000-0000-0000-000000000005"
BUSINESS_4    = "Junae Cosmetics"
BUSINESS_ID_4 = "00000000-0000-0000-0001-000000000002"
SCENARIO_4    = "Scenario 4 – Payment Link Not Available (Junae Cosmetics)"

CRITERIA_4 = [
    "The agent did not crash or return a raw error message when asked for a Paystack link.",
    "The agent communicated that an online/Paystack payment link is not available.",
    "The agent offered an alternative payment method (bank transfer details, etc.).",
    "The customer was not left without any payment path.",
    "The agent remained professional throughout.",
]


# ── Scenario 3 simulation ──────────────────────────────────────────────────────


async def run_3(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_3,
        f"Customer: {CUSTOMER_3} | Business: {BUSINESS_3} | Fresh session",
    )

    client  = AutobizClient(base_url)
    session = f"s3-{uuid.uuid4().hex[:8]}"

    customer = make_customer_agent(
        customer_name=CUSTOMER_3,
        business_name=BUSINESS_3,
        model=model,
        scenario_prompt=f"""You want to buy a {PRODUCT_3} from {BUSINESS_3}.

YOUR JOURNEY:
1. Ask if they have a {PRODUCT_3} and what it costs.
2. Once you like the price, say you want to buy it.
3. Explicitly ask: "How do I pay? Please send me the bank account details."
4. Note down the bank name, account number, and account name from the response.
5. Confirm you have the details and say you will transfer the money.

Set done=True after you receive bank details and confirm you'll make the transfer.""",
    )

    transcript: list[dict] = []
    transcript = await run_conversation(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_3,
        vendor_id=BUSINESS_ID_3,
        session_id=session,
        opening_message=f"Hello! Do you have a {PRODUCT_3} available? I'm ready to buy today.",
        max_turns=12,
        transcript=transcript,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_3, transcript, CRITERIA_3)
    print_verdict(verdict, SCENARIO_3)
    return verdict


# ── Scenario 4 simulation ──────────────────────────────────────────────────────


async def run_4(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_4,
        f"Customer: {CUSTOMER_4} | Business: {BUSINESS_4} | Paystack link not configured",
    )

    client  = AutobizClient(base_url)
    session = f"s4-{uuid.uuid4().hex[:8]}"

    customer = make_customer_agent(
        customer_name=CUSTOMER_4,
        business_name=BUSINESS_4,
        model=model,
        scenario_prompt=f"""You want to buy a beauty product from {BUSINESS_4}.

YOUR JOURNEY:
1. Ask what beauty products they have available and pick one.
2. Explicitly ask: "Can you send me a Paystack or online payment link?
   I prefer to pay online rather than doing a bank transfer."
3. If told no payment link is available, ask what payment options they do offer.
4. Accept the alternative and wrap up.

Set done=True after you receive any payment option and acknowledge it.""",
    )

    transcript: list[dict] = []
    transcript = await run_conversation(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_4,
        vendor_id=BUSINESS_ID_4,
        session_id=session,
        opening_message="Hi! What beauty products do you have available today?",
        max_turns=12,
        transcript=transcript,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_4, transcript, CRITERIA_4)
    print_verdict(verdict, SCENARIO_4)
    return verdict


# ── Entry-point ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scenario 3 & 4 – Payment Details")
    parser.add_argument("--base-url", default=os.environ.get("AUTOBIZ_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--model",    default=os.environ.get("TEST_MODEL", TEST_MODEL))
    parser.add_argument("--scenario", choices=["3", "4", "all"], default="all")
    args = parser.parse_args()

    async def main():
        verdicts = {}
        if args.scenario in ("3", "all"):
            verdicts["3"] = await run_3(args.base_url, args.model)
        if args.scenario in ("4", "all"):
            verdicts["4"] = await run_4(args.base_url, args.model)
        all_passed = all(v.passed for v in verdicts.values())
        print(f"\n{'─' * 60}")
        for name, v in verdicts.items():
            status = "✓ PASSED" if v.passed else "✗ FAILED"
            print(f"  Scenario {name}: {status}  (score={v.score:.2f})")
        return all_passed

    passed = asyncio.run(main())
    sys.exit(0 if passed else 1)
