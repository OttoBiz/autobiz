"""
Scenario 1 — Product Is Available
===================================
Business : Donrey Fashion
Customer : John Doe   (fresh session — no prior history)

Journey:
  1. Customer asks if Sneakers are available.
  2. Agent confirms availability, mentions price ($50) and description.
  3. Customer asks follow-up questions (stock, colour/options).
  4. Customer wraps up satisfied.

Judge checks:
  - Product name confirmed available.
  - Price explicitly stated.
  - Stock quantity / availability communicated.
  - Product description given.
  - Customer's questions were answered helpfully.

Run:
    python tests/test_product_available.py
    python tests/test_product_available.py --base-url http://my-server:8000
    python tests/test_product_available.py --model openai:gpt-4o
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

# ── Configuration ──────────────────────────────────────────────────────────────

CUSTOMER_NAME = "John Doe"
CUSTOMER_ID   = "00000000-0000-0000-0000-000000000001"
BUSINESS_NAME = "Donrey Fashion"
BUSINESS_ID   = "00000000-0000-0000-0001-000000000001"

SCENARIO_NAME = "Scenario 1 – Product Available (Donrey Fashion / Sneakers)"

CRITERIA = [
    "The agent confirmed that Sneakers are available in stock.",
    "The agent mentioned the price (around $50).",
    "The agent described the product (e.g. 'Classic white sneakers' or similar).",
    "Stock quantity or availability was explicitly communicated.",
    "The customer's enquiry was answered naturally and helpfully.",
]


# ── Main simulation ────────────────────────────────────────────────────────────


async def run(base_url: str, model: str = TEST_MODEL):
    print_header(
        SCENARIO_NAME,
        f"Customer: {CUSTOMER_NAME} | Business: {BUSINESS_NAME} | Short history",
    )

    client  = AutobizClient(base_url)
    session = f"s1-{uuid.uuid4().hex[:8]}"   # fresh session

    customer = make_customer_agent(
        customer_name=CUSTOMER_NAME,
        business_name=BUSINESS_NAME,
        model=model,
        scenario_prompt="""You want to buy Sneakers from this store.

YOUR JOURNEY:
1. Start by asking if they have Sneakers available.
2. Ask about the price and what they look like.
3. Ask how many pairs are in stock.
4. Once you have all the info, say thank you and wrap up.

Set done=True after you've received price and availability info and said goodbye.""",
    )

    transcript: list[dict] = []
    transcript = await run_conversation(
        client=client,
        customer_actor=customer,
        user_id=CUSTOMER_ID,
        vendor_id=BUSINESS_ID,
        session_id=session,
        opening_message="Hi! I'm looking for Sneakers. Do you have them available?",
        max_turns=10,
        transcript=transcript,
    )

    print_full_transcript(transcript)

    verdict = await evaluate(SCENARIO_NAME, transcript, CRITERIA)
    print_verdict(verdict, SCENARIO_NAME)
    return verdict


# ── Entry-point ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=SCENARIO_NAME)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AUTOBIZ_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("TEST_MODEL", TEST_MODEL),
    )
    args = parser.parse_args()

    verdict = asyncio.run(run(args.base_url, model=args.model))
    sys.exit(0 if verdict.passed else 1)
