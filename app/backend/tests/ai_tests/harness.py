"""Run one scenario against the live API with simulated personas + judge."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from .api_client import AutobizApiClient, new_session_id
from .config import INBOX_POLL_INTERVAL_S, INBOX_POLL_MAX_S
from .constants import LOGISTICS, USERS, VENDORS
from .llm_utils import customer_says, judge_scenario, logistics_says, vendor_says
from .pdf_receipts import (
    build_corrupt_pdf_bytes,
    build_inappropriate_receipt_pdf,
    build_plaintext_adversarial_non_receipt_pdf,
    build_plaintext_receipt_pdf,
    build_valid_receipt_pdf,
    compose_plaintext_inappropriate_receipt,
    compose_plaintext_valid_receipt,
)
from .scenarios import AIScenario

HistoryMode = str

PREAMBLES: Dict[HistoryMode, List[str]] = {
    "fresh": [],
    "short": [
        "Hi there!",
        "Quick question before I shop — do you offer same-day pickup?",
    ],
    "long": [
        "Hello!",
        "I'm browsing your catalog.",
        "Do you have warranties?",
        "What are your return rules?",
        "Thanks for explaining.",
        "I'll look at phones next.",
        "Actually one more thing — do you ship nationwide?",
        "Great, appreciated.",
    ],
    "mixed_prior_products": [
        "Do you still have those ankara dresses from last season?",
        "What about red heels in size 8?",
        "Never mind, different topic — any vitamin C serum?",
        "Ok noted. Switching to electronics now.",
    ],
}


@dataclass
class ScenarioRunResult:
    scenario_id: str
    history_mode: str
    passed: bool
    judge_confidence: float
    judge_reasoning: str
    transcript: str
    vendor_extras: str = ""
    error: str | None = None


def _format_transcript(turns: List[Dict[str, str]], extras: str = "") -> str:
    lines: List[str] = []
    for t in turns:
        lines.append(f"Customer: {t['user']}")
        lines.append(f"Assistant: {t['assistant']}")
    if extras:
        lines.append("")
        lines.append("--- Additional party lines ---")
        lines.append(extras)
    return "\n".join(lines)


async def _wait_inbox(
    api: AutobizApiClient,
    fetch_inbox,
    min_messages: int = 1,
) -> List[Dict[str, Any]]:
    deadline = time.monotonic() + INBOX_POLL_MAX_S
    last: List[Dict[str, Any]] = []
    while time.monotonic() < deadline:
        last = await fetch_inbox()
        if len(last) >= min_messages:
            return last
        await asyncio.sleep(INBOX_POLL_INTERVAL_S)
    return last


async def run_scenario(
    api: AutobizApiClient,
    scenario: AIScenario,
    history_mode: HistoryMode,
) -> ScenarioRunResult:
    uid = USERS[scenario.user_key]
    vid = VENDORS[scenario.vendor_key]
    lid = LOGISTICS[scenario.logistic_key] if scenario.logistic_key else None
    session_id = new_session_id(scenario.id)

    turns: List[Dict[str, str]] = []
    vendor_extra_lines: List[str] = []
    pdf_sent = False

    try:
        await api.health()
    except Exception as e:
        return ScenarioRunResult(
            scenario_id=scenario.id,
            history_mode=history_mode,
            passed=False,
            judge_confidence=0.0,
            judge_reasoning="",
            transcript="",
            error=f"API health check failed: {e}. Is AUTOBIZ_BASE_URL correct and Docker up?",
        )

    try:
        await api.session_clear(
            user_id=uid,
            vendor_id=vid,
            logistic_id=lid,
        )
    except Exception as e:
        return ScenarioRunResult(
            scenario_id=scenario.id,
            history_mode=history_mode,
            passed=False,
            judge_confidence=0.0,
            judge_reasoning="",
            transcript="",
            error=f"session/clear failed: {e}",
        )

    preamble = PREAMBLES.get(history_mode, [])
    for line in preamble:
        try:
            assistant = await api.customer_chat_json(
                uid, vid, line, session_id
            )
        except Exception as e:
            return ScenarioRunResult(
                scenario_id=scenario.id,
                history_mode=history_mode,
                passed=False,
                judge_confidence=0.0,
                judge_reasoning="",
                transcript=_format_transcript(turns),
                error=f"Preamble chat failed: {e}",
            )
        turns.append({"user": line, "assistant": assistant})

    extra_ctx = f"Chat history mode: {history_mode}."

    for turn in range(scenario.max_customer_turns):
        transcript = _format_transcript(turns)

        if (
            scenario.pdf_mode != "none"
            and not pdf_sent
            and turn >= min(scenario.pdf_turn_threshold, scenario.max_customer_turns - 1)
        ):
            msg = (
                "Here is my bank transfer receipt attached. Please confirm payment."
            )
            try:
                if scenario.pdf_mode == "valid":
                    if scenario.receipt_pdf_kind == "plaintext":
                        body = compose_plaintext_valid_receipt(
                            merchant=scenario.pdf_merchant_label,
                            product_name=scenario.pdf_product,
                            amount=scenario.pdf_amount,
                        )
                        pdf = build_plaintext_receipt_pdf(
                            body,
                            header="Fwd: payment slip (plain text PDF)",
                        )
                    else:
                        pdf = build_valid_receipt_pdf(
                            merchant=scenario.pdf_merchant_label,
                            product_name=scenario.pdf_product,
                            amount=scenario.pdf_amount,
                        )
                    assistant = await api.customer_chat_multipart(
                        uid,
                        vid,
                        msg,
                        session_id,
                        [("receipt.pdf", pdf, "application/pdf")],
                    )
                elif scenario.pdf_mode == "inappropriate":
                    if scenario.receipt_pdf_kind == "plaintext":
                        body = compose_plaintext_inappropriate_receipt(
                            merchant=scenario.pdf_merchant_label,
                            wrong_product=scenario.pdf_wrong_product,
                            wrong_amount=scenario.pdf_wrong_amount,
                        )
                        pdf = build_plaintext_receipt_pdf(
                            body,
                            header="Mobile banking export",
                        )
                    else:
                        pdf = build_inappropriate_receipt_pdf(
                            merchant=scenario.pdf_merchant_label,
                            wrong_product=scenario.pdf_wrong_product,
                            wrong_amount=scenario.pdf_wrong_amount,
                        )
                    assistant = await api.customer_chat_multipart(
                        uid,
                        vid,
                        msg,
                        session_id,
                        [("receipt.pdf", pdf, "application/pdf")],
                    )
                else:
                    if scenario.receipt_pdf_kind == "corrupt_bytes":
                        bad = build_corrupt_pdf_bytes()
                    else:
                        bad = build_plaintext_adversarial_non_receipt_pdf()
                    assistant = await api.customer_chat_multipart(
                        uid,
                        vid,
                        msg,
                        session_id,
                        [("receipt.pdf", bad, "application/pdf")],
                    )
                pdf_sent = True
            except Exception as e:
                return ScenarioRunResult(
                    scenario_id=scenario.id,
                    history_mode=history_mode,
                    passed=False,
                    judge_confidence=0.0,
                    judge_reasoning="",
                    transcript=_format_transcript(turns),
                    error=f"Multipart receipt upload failed: {e}",
                )
            turns.append({"user": f"{msg} [+file]", "assistant": assistant})
            continue

        try:
            user_line = await customer_says(
                goal=scenario.customer_goal,
                transcript=transcript,
                extra_context=extra_ctx,
            )
        except Exception as e:
            return ScenarioRunResult(
                scenario_id=scenario.id,
                history_mode=history_mode,
                passed=False,
                judge_confidence=0.0,
                judge_reasoning="",
                transcript=_format_transcript(turns),
                error=f"Customer actor LLM failed: {e}",
            )

        if user_line.upper() in ("[DONE]", "[STUCK]"):
            break

        try:
            assistant = await api.customer_chat_json(
                uid, vid, user_line, session_id
            )
        except Exception as e:
            return ScenarioRunResult(
                scenario_id=scenario.id,
                history_mode=history_mode,
                passed=False,
                judge_confidence=0.0,
                judge_reasoning="",
                transcript=_format_transcript(turns),
                error=f"customer/chat failed: {e}",
            )
        turns.append({"user": user_line, "assistant": assistant})

    if scenario.snapshot_vendor_inbox:
        await asyncio.sleep(3.0)
        try:
            snap = await api.get_vendor_inbox(vid)
            vendor_extra_lines.append(f"Vendor inbox tail: {snap[-8:]}")
        except Exception as e:
            vendor_extra_lines.append(f"vendor inbox snapshot error: {e}")

    if scenario.vendor_followup:
        inbox = await _wait_inbox(api, lambda: api.get_vendor_inbox(vid))
        summary = str(inbox[-3:]) if inbox else "(empty inbox)"
        try:
            vreply = await vendor_says(
                instruction=scenario.vendor_instruction,
                inbox_summary=summary,
            )
        except Exception as e:
            vendor_extra_lines.append(f"vendor actor error: {e}")
        else:
            if vreply.upper() != "[DONE]":
                try:
                    br = await api.business_chat(
                        vid, vreply, new_session_id("vendor"), sender="business"
                    )
                    vendor_extra_lines.append(f"Vendor reply: {vreply}")
                    vendor_extra_lines.append(f"Business assistant: {br}")
                except Exception as e:
                    vendor_extra_lines.append(f"business/chat error: {e}")

    if scenario.logistics_followup and lid:
        inbox_l = await _wait_inbox(
            api, lambda: api.get_logistics_inbox(lid), min_messages=0
        )
        summary_l = str(inbox_l[-3:]) if inbox_l else "(empty logistics inbox)"
        try:
            lreply = await logistics_says(
                instruction=scenario.logistics_instruction or "Acknowledge routing.",
                context=summary_l,
            )
        except Exception as e:
            vendor_extra_lines.append(f"logistics actor error: {e}")
        else:
            if lreply.upper() != "[DONE]":
                try:
                    lr = await api.logistics_chat(
                        lid, lreply, new_session_id("logistics")
                    )
                    vendor_extra_lines.append(f"Logistics reply: {lreply}")
                    vendor_extra_lines.append(f"Logistics assistant: {lr}")
                except Exception as e:
                    vendor_extra_lines.append(f"logistics/chat error: {e}")

    full_transcript = _format_transcript(
        turns, extras="\n".join(vendor_extra_lines)
    )

    try:
        verdict = await judge_scenario(
            title=scenario.title,
            rubric=scenario.judge_rubric,
            transcript=full_transcript,
            ground_truth=scenario.ground_truth,
        )
    except Exception as e:
        return ScenarioRunResult(
            scenario_id=scenario.id,
            history_mode=history_mode,
            passed=False,
            judge_confidence=0.0,
            judge_reasoning="",
            transcript=full_transcript,
            error=f"Judge LLM failed: {e}",
        )

    return ScenarioRunResult(
        scenario_id=scenario.id,
        history_mode=history_mode,
        passed=verdict.passed,
        judge_confidence=verdict.confidence,
        judge_reasoning=verdict.reasoning,
        transcript=full_transcript,
        vendor_extras="\n".join(vendor_extra_lines),
    )
