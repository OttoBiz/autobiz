"""
Scenario 5 — Payment Receipt Verification
==========================================
Real PDF receipts built by the test and uploaded to the deployed backend via
multipart form.  The backend's media_processing_agent extracts receipt text;
the payment_verification_agent validates it against expected product/amount.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5A — Inappropriate document  (Lisa Thompson / Manny Gadgets — LONG history)
  Pre-history : 6 turns covering iPhone 12 specs, comparisons, and accessories.
  Receipt     : A CV / job-application PDF — clearly not a payment receipt.
  Expected    : Agent detects wrong document type and asks customer to re-submit.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5B — Invalid receipt — wrong amount & old date  (John Doe / Kemi Surprises)
  Pre-history : 2 turns establishing Red Shirt at $29.99.
  Receipt     : Correct vendor/product but amount = $299.90 (10×) and date
                is 6 months ago.
  Expected    : Agent flags the mismatch; does not confirm invalid payment.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5C — Valid receipt  (Sarah Johnson / Tesla Tech)
  Pre-history : 2 turns — customer agreed to buy Laptop at $1500.
  Receipt     : Correct vendor (Tesla Tech), product (Laptop), amount ($1500),
                today's date.
  Expected    : Agent confirms payment valid and tells customer next steps.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run:
    python tests/test_payment_verification.py
    python tests/test_payment_verification.py --scenario 5c
    python tests/test_payment_verification.py --base-url http://my-server:8000
"""
import argparse
import asyncio
import os
import sys
import uuid
from datetime import date

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from pydantic_ai.messages import ModelMessage

from tests.shared.actors import TEST_MODEL, make_customer_agent
from tests.shared.client import AutobizClient
from tests.shared.helpers import (
    evaluate,
    log,
    print_full_transcript,
    print_header,
    print_verdict,
    run_conversation,
    seed_chat_history,
)
from tests.shared.receipt_utils import (
    generate_inappropriate_document,
    generate_invalid_receipt,
    generate_valid_receipt,
)

# ── 5A ─────────────────────────────────────────────────────────────────────────

CUSTOMER_5A    = "Lisa Thompson"
CUSTOMER_ID_5A = "00000000-0000-0000-0000-000000000006"
BUSINESS_5A    = "Manny Gadgets"
BUSINESS_ID_5A = "00000000-0000-0000-0001-000000000003"
SCENARIO_5A    = "Scenario 5A – Inappropriate Receipt / CV Document (Manny Gadgets)"

CRITERIA_5A = [
    "The agent detected the uploaded document is not a payment receipt.",
    "The agent did not treat the CV as a valid receipt.",
    "The agent requested the customer to submit the correct payment receipt.",
    "The response was polite and did not expose a raw system error.",
    "The long chat history (iPhone discussions) did not cause the agent to ignore the receipt issue.",
]

# ── 5B ─────────────────────────────────────────────────────────────────────────

CUSTOMER_5B    = "John Doe"
CUSTOMER_ID_5B = "00000000-0000-0000-0000-000000000001"
BUSINESS_5B    = "Kemi Surprises"
BUSINESS_ID_5B = "00000000-0000-0000-0001-000000000005"
PRODUCT_5B     = "Red Shirt"
AMOUNT_5B      = 29.99
SCENARIO_5B    = "Scenario 5B – Invalid Receipt / Wrong Amount (Kemi Surprises / Shirt)"

CRITERIA_5B = [
    "The agent flagged that the receipt amount does not match the expected product price.",
    "The agent did not confirm a payment with mismatched details.",
    "The agent communicated the discrepancy clearly to the customer.",
    "The agent asked the customer to re-verify or re-submit the correct receipt.",
    "The agent remained professional despite the invalid submission.",
]

# ── 5C ─────────────────────────────────────────────────────────────────────────

CUSTOMER_5C    = "Sarah Johnson"
CUSTOMER_ID_5C = "00000000-0000-0000-0000-000000000002"
BUSINESS_5C    = "Tesla Tech"
BUSINESS_ID_5C = "00000000-0000-0000-0001-000000000004"
PRODUCT_5C     = "Laptop"
AMOUNT_5C      = 1500.00
SCENARIO_5C    = "Scenario 5C – Valid Receipt (Tesla Tech / Laptop $1500)"

CRITERIA_5C = [
    "The agent accepted the payment receipt as valid.",
    "The agent confirmed the payment was successful.",
    "The agent mentioned the product (Laptop) and/or amount ($1500) during verification.",
    "The customer was informed that their payment has been verified.",
    "The agent mentioned or asked about next steps (e.g. delivery).",
]


# ── Shared receipt-upload helper ───────────────────────────────────────────────


async def _send_receipt_and_continue(
    client: AutobizClient,
    customer_actor,
    user_id: str,
    vendor_id: str,
    session_id: str,
    receipt_message: str,
    receipt_bytes: bytes,
    receipt_filename: str,
    transcript: list[dict],
    max_followup_turns: int = 5,
) -> list[dict]:
    """
    Upload a receipt alongside a message, log the response, then continue
    the conversation for up to max_followup_turns.
    """
    log("customer", receipt_message, transcript)
    response = await client.customer_chat(
        user_id=user_id,
        vendor_id=vendor_id,
        session_id=session_id,
        message=receipt_message,
        receipt_bytes=receipt_bytes,
        receipt_filename=receipt_filename,
    )
    log("system",    f"[FILE UPLOADED] {receipt_filename} ({len(receipt_bytes)} bytes)", transcript)
    log("assistant", response, transcript)

    history: list[ModelMessage] = []
    r = await customer_actor.run(
        f'The store AI replied:\n\n"{response}"\n\nWhat do you say next?',
        message_history=history,
    )
    history = r.all_messages()
    reply = r.output

    if not reply.done and reply.message:
        transcript = await run_conversation(
            client=client,
            customer_actor=customer_actor,
            user_id=user_id,
            vendor_id=vendor_id,
            session_id=session_id,
            opening_message=reply.message,
            max_turns=max_followup_turns,
            transcript=transcript,
        )

    return transcript


# ── 5A simulation ──────────────────────────────────────────────────────────────


async def run_5a(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_5A,
        f"Customer: {CUSTOMER_5A} | Business: {BUSINESS_5A} | LONG history (6 turns) + CV upload",
    )

    client  = AutobizClient(base_url)
    session = f"s5a-{uuid.uuid4().hex[:8]}"

    # Seed: 6 turns covering iPhone 12 discussions (3 topics × 2 turns each)
    print("\n[SETUP] Pre-seeding LONG chat history: 6 turns about iPhone products…")
    await seed_chat_history(
        client=client,
        user_id=CUSTOMER_ID_5A,
        vendor_id=BUSINESS_ID_5A,
        session_id=session,
        seed_topics=[
            "iPhone 12 specs, storage options, and price",
            "comparing iPhone 12 vs iPhone 12 Pro Max",
            "best phone accessories for iPhone 12",
        ],
        model=model,
        turns_per_topic=2,
    )

    doc_bytes, doc_name = generate_inappropriate_document()
    print(f"\n[SETUP] Inappropriate document: {doc_name} ({len(doc_bytes)} bytes)")

    customer = make_customer_agent(
        customer_name=CUSTOMER_5A,
        business_name=BUSINESS_5A,
        model=model,
        scenario_prompt="""You chatted about iPhones and now want to finalise a purchase.
You accidentally have the wrong file — you'll attach a CV instead of a receipt.

YOUR JOURNEY:
1. Tell the agent you have paid and are sending your payment receipt.
2. The receipt will be attached automatically when you mention it.
3. After the agent responds, if they say it's not a valid receipt,
   apologise and say you'll find the correct receipt.
4. Wrap up.

Set done=True after the agent responds to your receipt submission.""",
    )

    transcript: list[dict] = []
    transcript = await _send_receipt_and_continue(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_5A,
        vendor_id=BUSINESS_ID_5A,
        session_id=session,
        receipt_message="I've made the payment! Here's my receipt for the iPhone 12.",
        receipt_bytes=doc_bytes,
        receipt_filename=doc_name,
        transcript=transcript,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_5A, transcript, CRITERIA_5A)
    print_verdict(verdict, SCENARIO_5A)
    return verdict


# ── 5B simulation ──────────────────────────────────────────────────────────────


async def run_5b(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_5B,
        f"Customer: {CUSTOMER_5B} | Business: {BUSINESS_5B} | Invalid amount (10×) + old date",
    )

    client  = AutobizClient(base_url)
    session = f"s5b-{uuid.uuid4().hex[:8]}"

    # Seed: 2 turns establishing Red Shirt at $29.99
    print(f"\n[SETUP] Pre-seeding: customer discussing {PRODUCT_5B} at ${AMOUNT_5B}…")
    await seed_chat_history(
        client=client,
        user_id=CUSTOMER_ID_5B,
        vendor_id=BUSINESS_ID_5B,
        session_id=session,
        seed_topics=[f"Red Shirt — price ${AMOUNT_5B}, customer wants to buy"],
        model=model,
        turns_per_topic=2,
    )

    receipt_bytes, receipt_name = generate_invalid_receipt(
        vendor_name=BUSINESS_5B,
        product_name=PRODUCT_5B,
        correct_amount=AMOUNT_5B,   # generate_invalid_receipt inflates × 10
        transaction_ref=f"TXN-{uuid.uuid4().hex[:8].upper()}",
    )
    print(f"[SETUP] Invalid receipt: {receipt_name}, wrong amount=${AMOUNT_5B*10:.2f}, old date")

    customer = make_customer_agent(
        customer_name=CUSTOMER_5B,
        business_name=BUSINESS_5B,
        model=model,
        scenario_prompt=f"""You agreed to buy a {PRODUCT_5B} and have now paid.
(The receipt you'll submit has wrong details — but you don't know that.)

YOUR JOURNEY:
1. Tell the agent you've made the bank transfer and are sending your receipt.
2. After the agent responds about the receipt, react naturally.
3. If they flag an issue, apologise and say you'll recheck your receipt.
4. Wrap up.

Set done=True after you receive the agent's response to your receipt.""",
    )

    transcript: list[dict] = []
    transcript = await _send_receipt_and_continue(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_5B,
        vendor_id=BUSINESS_ID_5B,
        session_id=session,
        receipt_message=f"I've transferred the money for the {PRODUCT_5B}. Here's my payment receipt.",
        receipt_bytes=receipt_bytes,
        receipt_filename=receipt_name,
        transcript=transcript,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_5B, transcript, CRITERIA_5B)
    print_verdict(verdict, SCENARIO_5B)
    return verdict


# ── 5C simulation ──────────────────────────────────────────────────────────────


async def run_5c(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_5C,
        f"Customer: {CUSTOMER_5C} | Business: {BUSINESS_5C} | Valid receipt — Laptop $1500",
    )

    client  = AutobizClient(base_url)
    session = f"s5c-{uuid.uuid4().hex[:8]}"

    # Seed: agree on Laptop purchase
    print(f"\n[SETUP] Pre-seeding: customer agrees to buy {PRODUCT_5C} at ${AMOUNT_5C}…")
    await seed_chat_history(
        client=client,
        user_id=CUSTOMER_ID_5C,
        vendor_id=BUSINESS_ID_5C,
        session_id=session,
        seed_topics=[
            f"{PRODUCT_5C} — price check and availability at ${AMOUNT_5C}",
            f"customer confirms they want to buy the {PRODUCT_5C}",
        ],
        model=model,
        turns_per_topic=2,
    )

    txn_ref = f"TXN-TESLA-{uuid.uuid4().hex[:8].upper()}"
    receipt_bytes, receipt_name = generate_valid_receipt(
        vendor_name=BUSINESS_5C,
        product_name=PRODUCT_5C,
        amount=AMOUNT_5C,
        transaction_ref=txn_ref,
        payment_date=date.today(),
    )
    print(f"[SETUP] Valid receipt: {receipt_name} — vendor={BUSINESS_5C}, "
          f"product={PRODUCT_5C}, amount=${AMOUNT_5C}, date={date.today()}, ref={txn_ref}")

    customer = make_customer_agent(
        customer_name=CUSTOMER_5C,
        business_name=BUSINESS_5C,
        model=model,
        scenario_prompt=f"""You have agreed to buy a {PRODUCT_5C} for ${AMOUNT_5C}
and have now completed the bank transfer.

YOUR JOURNEY:
1. Tell the agent the payment is done and you are sending the receipt.
   Reference: {txn_ref}.
2. The receipt will be attached automatically.
3. After the agent confirms payment, ask about delivery next steps.
4. Wrap up.

Set done=True after payment is confirmed and you know the next steps.""",
    )

    transcript: list[dict] = []
    transcript = await _send_receipt_and_continue(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID_5C,
        vendor_id=BUSINESS_ID_5C,
        session_id=session,
        receipt_message=(
            f"I've made the bank transfer of ${AMOUNT_5C} for the {PRODUCT_5C}. "
            f"Reference: {txn_ref}. Sending my payment receipt now."
        ),
        receipt_bytes=receipt_bytes,
        receipt_filename=receipt_name,
        transcript=transcript,
    )

    print_full_transcript(transcript)
    verdict = await evaluate(SCENARIO_5C, transcript, CRITERIA_5C)
    print_verdict(verdict, SCENARIO_5C)
    return verdict


# ── Entry-point ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scenario 5 – Payment Receipt Verification")
    parser.add_argument("--base-url", default=os.environ.get("AUTOBIZ_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--model",    default=os.environ.get("TEST_MODEL", TEST_MODEL))
    parser.add_argument("--scenario", choices=["5a", "5b", "5c", "all"], default="all")
    args = parser.parse_args()

    async def main():
        verdicts = {}
        if args.scenario in ("5a", "all"):
            verdicts["5A"] = await run_5a(args.base_url, args.model)
        if args.scenario in ("5b", "all"):
            verdicts["5B"] = await run_5b(args.base_url, args.model)
        if args.scenario in ("5c", "all"):
            verdicts["5C"] = await run_5c(args.base_url, args.model)
        all_passed = all(v.passed for v in verdicts.values())
        print(f"\n{'─' * 60}")
        for name, v in verdicts.items():
            status = "✓ PASSED" if v.passed else "✗ FAILED"
            print(f"  Scenario {name}: {status}  (score={v.score:.2f})")
        return all_passed

    passed = asyncio.run(main())
    sys.exit(0 if passed else 1)
