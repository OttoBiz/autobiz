"""
Shared helpers for all scenario tests:
  - Conversation loop that drives the customer via HTTP
  - Chat history seeder (pre-populates Redis state)
  - Transcript printer
  - Judge evaluation wrapper
"""
import asyncio
from typing import Any, Optional

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage

from .actors import CustomerReply, JudgeVerdict, judge_agent, make_customer_agent
from .client import AutobizClient

# ── Colour helpers ─────────────────────────────────────────────────────────────

_COLORS = {
    "customer": "\033[96m",    # cyan
    "assistant": "\033[93m",   # yellow
    "vendor": "\033[92m",      # green
    "logistics": "\033[94m",   # blue
    "system": "\033[90m",      # grey
    "judge": "\033[95m",       # magenta
}
_RESET = "\033[0m"


def log(role: str, message: str, transcript: list[dict]) -> None:
    transcript.append({"role": role, "message": message})
    color = _COLORS.get(role, "")
    print(f"\n{color}[{role.upper()}]{_RESET}")
    print(f"  {message}")


# ── Core conversation loop ─────────────────────────────────────────────────────


async def run_conversation(
    client: AutobizClient,
    customer_actor: Agent,
    user_id: str,
    vendor_id: str,
    session_id: str,
    opening_message: str,
    max_turns: int = 15,
    receipt_bytes: Optional[bytes] = None,
    receipt_filename: Optional[str] = None,
    transcript: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Drive a multi-turn customer conversation through the deployed HTTP API.

    The customer_actor LLM decides each reply.  When it sets upload_receipt=True,
    the next HTTP call carries the receipt file.  When done=True the final message
    is sent and the loop ends.
    """
    if transcript is None:
        transcript = []

    customer_history: list[ModelMessage] = []
    customer_msg = opening_message
    receipt_uploaded = False

    for turn in range(1, max_turns + 1):
        print(f"\n{'─' * 60}\n  Turn {turn}\n{'─' * 60}")

        log("customer", customer_msg, transcript)

        # Customer actor chooses next reply BEFORE we know the assistant's response.
        # We need to decide receipt upload BEFORE this turn's HTTP call so we can
        # attach the file.  We use a sticky flag from the *previous* actor decision.
        response = await client.customer_chat(
            user_id=user_id,
            vendor_id=vendor_id,
            session_id=session_id,
            message=customer_msg,
            receipt_bytes=receipt_bytes if (receipt_bytes and not receipt_uploaded and _should_upload(customer_msg)) else None,
            receipt_filename=receipt_filename if (receipt_bytes and not receipt_uploaded and _should_upload(customer_msg)) else None,
        )
        if receipt_bytes and not receipt_uploaded and _should_upload(customer_msg):
            receipt_uploaded = True
            log("system", f"Receipt uploaded: {receipt_filename}", transcript)

        log("assistant", response, transcript)

        # Ask customer actor what to say next
        customer_result = await customer_actor.run(
            f'The store AI just replied:\n\n"{response}"\n\nWhat do you say next as the customer?',
            message_history=customer_history,
        )
        customer_history = customer_result.all_messages()
        reply: CustomerReply = customer_result.output

        if reply.upload_receipt and not receipt_uploaded and receipt_bytes is not None:
            # Actor signals: next message should carry the receipt
            customer_msg = reply.message
            # Mark so that on the next loop iteration the file is attached
            # We do this by checking if the message mentions receipt
            # (handled by _should_upload, but we force the flag by including the word)
            if "receipt" not in customer_msg.lower():
                customer_msg = reply.message + " (receipt attached)"
        elif reply.done:
            log("customer", reply.message, transcript)
            final_resp = await client.customer_chat(
                user_id=user_id,
                vendor_id=vendor_id,
                session_id=session_id,
                message=reply.message,
            )
            log("assistant", final_resp, transcript)
            break
        else:
            customer_msg = reply.message

    return transcript


def _should_upload(message: str) -> bool:
    """Heuristic: does this message signal a receipt upload?"""
    keywords = ("receipt", "payment receipt", "proof of payment", "i've paid", "i have paid",
                "here's my receipt", "attached", "screenshot")
    msg_lower = message.lower()
    return any(k in msg_lower for k in keywords)


# ── Conversation seeder ────────────────────────────────────────────────────────


async def seed_chat_history(
    client: AutobizClient,
    user_id: str,
    vendor_id: str,
    session_id: str,
    seed_topics: list[str],
    model: Optional[str] = None,
    turns_per_topic: int = 2,
) -> list[dict]:
    """
    Pre-populate Redis chat history by sending warm-up messages about given topics.
    This simulates a customer who has talked to the store about these things before.
    Returns the warm-up transcript.
    """
    from .actors import TEST_MODEL
    model = model or TEST_MODEL

    transcript = []

    for topic in seed_topics:
        warm_up = make_customer_agent(
            customer_name="Customer",
            business_name="Store",
            scenario_prompt=(
                f"You are browsing and want to ask about {topic}. "
                f"Ask {turns_per_topic} short questions then set done=True."
            ),
            model=model,
        )
        history: list[ModelMessage] = []
        msg = f"Hi, I had a quick question about {topic}"

        for _ in range(turns_per_topic + 1):
            resp = await client.customer_chat(
                user_id=user_id,
                vendor_id=vendor_id,
                session_id=session_id,
                message=msg,
            )
            log("system", f"[SEED] Customer: {msg}", transcript)
            log("system", f"[SEED] Assistant: {resp}", transcript)

            r = await warm_up.run(
                f'Store replied: "{resp}". Continue briefly.',
                message_history=history,
            )
            history = r.all_messages()
            reply: CustomerReply = r.output
            if reply.done:
                break
            msg = reply.message

    return transcript


# ── Vendor/logistics polling loop ──────────────────────────────────────────────


async def run_vendor_polling(
    client: AutobizClient,
    vendor_actor: Agent,
    vendor_id: str,
    session_id: str,
    transcript: list[dict],
    poll_interval: float = 3.0,
    max_polls: int = 20,
) -> list[dict]:
    """
    Poll the vendor inbox and reply via the business chat endpoint.
    Simulates a vendor reading outbound messages and responding.
    """
    from .actors import VendorReply

    print("\n[VENDOR POLLING] Waiting for inbox messages...")
    vendor_history: list[ModelMessage] = []

    for attempt in range(max_polls):
        await asyncio.sleep(poll_interval)
        messages = await client.get_vendor_inbox(vendor_id)
        if not messages:
            continue

        for msg_text in messages:
            if isinstance(msg_text, dict):
                msg_text = msg_text.get("message") or str(msg_text)
            log("system", f"[VENDOR INBOX] {msg_text}", transcript)

            v_result = await vendor_actor.run(
                f'The AI system sent you this message:\n\n"{msg_text}"\n\nHow do you respond?',
                message_history=vendor_history,
            )
            vendor_history = v_result.all_messages()
            v_reply: VendorReply = v_result.output

            log("vendor", v_reply.message, transcript)

            await client.business_chat(
                session_id=session_id,
                vendor_id=vendor_id,
                message=v_reply.message,
                sender="business",
                recent_inbox=messages,
            )

            if v_reply.done:
                return transcript
        break

    return transcript


# ── Judge evaluation ───────────────────────────────────────────────────────────


async def evaluate(
    scenario_name: str,
    transcript: list[dict],
    criteria: list[str],
) -> JudgeVerdict:
    """Ask the judge agent to evaluate the transcript against a list of criteria."""
    lines = "\n".join(f"[{t['role'].upper()}]: {t['message']}" for t in transcript)
    criteria_block = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(criteria))

    prompt = f"""SCENARIO: {scenario_name}

TRANSCRIPT:
{lines}

CRITERIA TO EVALUATE:
{criteria_block}

Evaluate each criterion based strictly on what is in the transcript."""

    result = await judge_agent.run(prompt)
    return result.output


# ── Display helpers ────────────────────────────────────────────────────────────


def print_header(title: str, details: str = "") -> None:
    print(f"\n{'#' * 70}")
    print(f"#  {title}")
    if details:
        print(f"#  {details}")
    print(f"{'#' * 70}")


def print_full_transcript(transcript: list[dict]) -> None:
    print(f"\n{'#' * 70}")
    print("#  FULL TRANSCRIPT")
    print(f"{'#' * 70}")
    for entry in transcript:
        role = entry["role"].upper()
        print(f"\n[{role}] {entry['message']}")


def print_verdict(verdict: JudgeVerdict, scenario_name: str) -> None:
    status = "✓ PASSED" if verdict.passed else "✗ FAILED"
    color = "\033[92m" if verdict.passed else "\033[91m"
    print(f"\n{'#' * 70}")
    print(f"#  JUDGE VERDICT: {scenario_name}")
    print(f"{'#' * 70}")
    print(f"#  {color}{status}\033[0m  (score: {verdict.score:.2f})")
    print(f"#  {verdict.reason}")
    if verdict.found_criteria:
        print(f"#\n#  ✓ Met:")
        for c in verdict.found_criteria:
            print(f"#    - {c}")
    if verdict.missing_criteria:
        print(f"#\n#  ✗ Missing:")
        for c in verdict.missing_criteria:
            print(f"#    - {c}")
    print(f"{'#' * 70}")


def assert_verdict(verdict: JudgeVerdict, scenario_name: str) -> None:
    """pytest-friendly assertion — raises AssertionError with details if failed."""
    print_verdict(verdict, scenario_name)
    missing = "\n  - ".join(verdict.missing_criteria) if verdict.missing_criteria else "none"
    assert verdict.passed, (
        f"Scenario '{scenario_name}' FAILED (score={verdict.score:.2f}).\n"
        f"Reason: {verdict.reason}\n"
        f"Missing criteria:\n  - {missing}"
    )
