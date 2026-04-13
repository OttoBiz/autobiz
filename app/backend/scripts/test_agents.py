"""
Agent Testing Script for Ottobiz.

Runs curated "gold questions" against each agent, captures outputs,
timings, and errors, then writes a structured results JSON.

Run:
    cd app && python -m backend.scripts.test_agents
    cd app && python -m backend.scripts.test_agents --agent conversational_agent
    cd app && python -m backend.scripts.test_agents --output my_results.json
"""

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from backend.db.connection import close_db, get_db, init_db
from backend.logging_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

GOLD_QUESTIONS_PATH = Path(__file__).parent / "gold_questions.json"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class AgentTestResult:
    timestamp: str
    agent_name: str
    test_id: str
    description: str
    input_data: dict
    expected: Optional[Any]
    actual_output: Optional[Any]
    success: bool
    duration_ms: float
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Per-agent test functions
# ---------------------------------------------------------------------------


async def test_conversational_agent(q: dict, business_id: str, user_id: str) -> AgentTestResult:
    from backend.chatbot.agents.conversational_agent import run_conversational_agent

    start = time.perf_counter()
    error = None
    output = None
    success = False

    try:
        user_state = {"products": {}, "processes": {}, "chat_history": []}
        text = await run_conversational_agent(
            user_message=q["input"],
            chat_history=[],
            user_id=user_id,
            business_id=business_id,
            user_state=user_state,
        )
        output = {"response": text}
        text_str = (text or "").strip()
        success = len(text_str) > 5 and "error" not in text_str[:120].lower()
        sub = q.get("expected_substring")
        if success and sub:
            success = sub.lower() in text_str.lower()
    except Exception as e:
        error = str(e)

    return AgentTestResult(
        timestamp=datetime.now().isoformat(),
        agent_name="conversational_agent",
        test_id=q["id"],
        description=q["description"],
        input_data={"message": q["input"]},
        expected=q.get("expected_substring") or "non_empty_reply",
        actual_output=output,
        success=success,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        error=error,
    )


async def test_product_agent(q: dict, business_id: str, user_id: str) -> AgentTestResult:
    from backend.chatbot.agents.product_agent import run_product_agent

    start = time.perf_counter()
    error = None
    output = None
    success = False

    try:
        response, _state = await run_product_agent(
            customer_message=q["input"],
            product_name=q.get("product_name", "NONE"),
            product_category=q.get("category", ""),
            intent=q.get("intent", "enquiry"),
            user_id=user_id,
            business_id=business_id,
        )
        output = response
        success = isinstance(response, str) and len(response) > 0
    except Exception as e:
        error = str(e)

    return AgentTestResult(
        timestamp=datetime.now().isoformat(),
        agent_name="product_agent",
        test_id=q["id"],
        description=q["description"],
        input_data={"message": q["input"]},
        expected=None,
        actual_output=output,
        success=success,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        error=error,
    )


async def test_payment_agent(q: dict, business_id: str, user_id: str) -> AgentTestResult:
    from backend.chatbot.agents.payment_verification_agent import run_verification_agent

    start = time.perf_counter()
    error = None
    output = None
    success = False

    try:
        response = await run_verification_agent(
            customer_message=q["input"],
            user_id=user_id,
            business_id=business_id,
        )
        output = response
        success = isinstance(response, str) and len(response) > 0
    except Exception as e:
        error = str(e)

    return AgentTestResult(
        timestamp=datetime.now().isoformat(),
        agent_name="payment_agent",
        test_id=q["id"],
        description=q["description"],
        input_data={"message": q["input"]},
        expected=None,
        actual_output=output,
        success=success,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        error=error,
    )


async def test_upselling_agent(q: dict, business_id: str) -> AgentTestResult:
    from backend.chatbot.agents.upselling_agent import run_upselling_agent

    start = time.perf_counter()
    error = None
    output = None
    success = False

    try:
        response = await run_upselling_agent(
            product=q["input"],
            business_id=business_id,
        )
        output = response
        success = isinstance(response, str) and len(response) > 0
    except Exception as e:
        error = str(e)

    return AgentTestResult(
        timestamp=datetime.now().isoformat(),
        agent_name="upselling_agent",
        test_id=q["id"],
        description=q["description"],
        input_data={"product": q["input"]},
        expected=None,
        actual_output=output,
        success=success,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        error=error,
    )


async def test_complaint_agent(q: dict, business_id: str, user_id: str) -> AgentTestResult:
    from backend.chatbot.agents.customer_complaint_agent import (
        run_customer_complaint_agent,
    )

    start = time.perf_counter()
    error = None
    output = None
    success = False

    try:
        response, _state = await run_customer_complaint_agent(
            customer_message=q["input"],
            product_name=q.get("product_name", ""),
            user_id=user_id,
            business_id=business_id,
        )
        output = response
        success = isinstance(response, str) and len(response) > 0
    except Exception as e:
        error = str(e)

    return AgentTestResult(
        timestamp=datetime.now().isoformat(),
        agent_name="complaint_agent",
        test_id=q["id"],
        description=q["description"],
        input_data={"message": q["input"], "product_name": q.get("product_name", "")},
        expected=None,
        actual_output=output,
        success=success,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        error=error,
    )


async def test_evaluator_agent(q: dict) -> AgentTestResult:
    from backend.chatbot.agents.evaluator_agent import evaluate_response

    start = time.perf_counter()
    error = None
    output = None
    success = False

    try:
        result = await evaluate_response(
            response=q["input"],
            conversation_context=q.get("context", ""),
        )
        output = result.model_dump()
        # Good response should be approved, rude should be rejected
        if "good" in q["id"]:
            success = result.should_send is True
        elif "rude" in q["id"]:
            success = result.should_send is False
        else:
            success = True  # No specific expectation
    except Exception as e:
        error = str(e)

    return AgentTestResult(
        timestamp=datetime.now().isoformat(),
        agent_name="evaluator_agent",
        test_id=q["id"],
        description=q["description"],
        input_data={"response": q["input"], "context": q.get("context", "")},
        expected="should_send=True" if "good" in q["id"] else "should_send=False",
        actual_output=output,
        success=success,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        error=error,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

AGENT_RUNNERS = {
    "conversational_agent": test_conversational_agent,
    "product_agent": test_product_agent,
    "payment_agent": test_payment_agent,
    "upselling_agent": test_upselling_agent,
    "complaint_agent": test_complaint_agent,
    "evaluator_agent": test_evaluator_agent,
}


async def run_all_tests(agent_filter: Optional[str] = None, output_path: str = "test_results.json"):
    """Run all gold question tests and write results."""
    with open(GOLD_QUESTIONS_PATH) as f:
        gold = json.load(f)

    await init_db()
    pool = await get_db()

    # Fetch a test business + user from DB
    async with pool.acquire() as conn:
        biz_row = await conn.fetchrow(
            "SELECT id FROM businesses WHERE business_type = 'vendor' LIMIT 1"
        )
        user_row = await conn.fetchrow("SELECT id FROM users LIMIT 1")

    if not biz_row or not user_row:
        print("ERROR: No businesses or users in DB. Run prepopulate_db.py first.")
        await close_db()
        return

    business_id = str(biz_row["id"])
    user_id = str(user_row["id"])
    print(f"Using business_id={business_id}, user_id={user_id}\n")

    results: list[AgentTestResult] = []

    for agent_key, questions in gold.items():
        if agent_filter and agent_filter != agent_key:
            continue

        runner = AGENT_RUNNERS.get(agent_key)
        if not runner:
            print(f"  SKIP {agent_key} — no runner defined")
            continue

        print(f"--- {agent_key} ({len(questions)} tests) ---")

        for q in questions:
            # Determine which args the runner needs
            if agent_key == "upselling_agent":
                result = await runner(q, business_id)
            elif agent_key == "evaluator_agent":
                result = await runner(q)
            else:
                result = await runner(q, business_id, user_id)

            status = "PASS" if result.success else ("FAIL" if not result.error else "ERROR")
            print(f"  [{status}] {result.test_id} ({result.duration_ms}ms) — {result.description}")
            if result.error:
                print(f"         error: {result.error}")
            results.append(result)

    # Write results
    with open(output_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2, default=str)
    print(f"\nResults written to {output_path}")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success and not r.error)
    errored = sum(1 for r in results if r.error)
    print(f"\nSummary: {passed}/{total} passed, {failed} failed, {errored} errors")

    await close_db()


def main():
    parser = argparse.ArgumentParser(description="Run Ottobiz agent tests")
    parser.add_argument("--agent", type=str, default=None, help="Filter to a single agent (e.g. conversational_agent)")
    parser.add_argument("--output", type=str, default="test_results.json", help="Output JSON path")
    args = parser.parse_args()

    asyncio.run(run_all_tests(agent_filter=args.agent, output_path=args.output))


if __name__ == "__main__":
    main()
