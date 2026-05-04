"""
Payment Verification Agent - Verifies customer payments
Converted to pydantic_ai with media processing support
"""
import json
import logging
import re
from datetime import date, datetime, time, timezone
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks
from pydantic import BaseModel
from pydantic_ai import RunContext

from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.central_agent_utils import (
    create_structured_input,
    ensure_central_process,
)
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.struct import Customer, EntityType, Product, TaskType, Vendor
from backend.chatbot.utils.agent_utils import (
    format_handoff_process_context,
    get_or_create_user_state,
    get_process_snapshot,
    save_user_state,
)
from backend.db.db_utils import get_business_info
from backend.config import BANK_RECEIPT_AMOUNT_TOLERANCE, BANK_RECEIPT_MAX_AGE_HOURS
from backend.payments.paystack_client import kobo_to_major, verify_transaction

from .base_agent import BaseAgent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

logger = logging.getLogger(__name__)


def _product_name_for_notify(us: Dict[str, Any], process_id: Optional[str]) -> str:
    pid = (process_id or "").strip()
    if pid:
        raw = (us.get("processes") or {}).get(pid)
        if isinstance(raw, dict) and (raw.get("product_name") or "").strip():
            return str(raw.get("product_name")).strip()
    pd = us.get("products_discussed")
    if isinstance(pd, list) and pd:
        last = pd[-1]
        n = (last.get("name") if isinstance(last, dict) else str(last)).strip()
        if n:
            return n
    return "Payment verification"


class PaymentVerificationDeps(BaseModel):
    """Dependencies for payment verification agent"""

    user_id: str
    business_id: str
    user_state: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None
    process_id: Optional[str] = None


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _parse_iso_date(s: str) -> Optional[date]:
    t = (s or "").strip()[:10]
    if not t:
        return None
    try:
        return date.fromisoformat(t)
    except ValueError:
        return None


def _parse_receipt_datetime_utc(
    date_s: Optional[str], time_s: Optional[str]
) -> Optional[datetime]:
    """Combine receipt date + optional time for recency; naive UTC for comparison."""
    d = _parse_iso_date((date_s or "")[:10] if (date_s or "") else "")
    if d is None:
        return None
    ts = (time_s or "").strip()
    if not ts:
        return datetime.combine(d, time(12, 0), tzinfo=timezone.utc)
    for fmt, sample in (("%H:%M", 5), ("%H:%M:%S", 8), ("%H.%M", 5)):
        try:
            tpart = datetime.strptime(ts[:sample], fmt).time()
            return datetime.combine(d, tpart, tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        tpart = datetime.strptime(ts, "%I:%M %p").time()
        return datetime.combine(d, tpart, tzinfo=timezone.utc)
    except ValueError:
        pass
    return datetime.combine(d, time(12, 0), tzinfo=timezone.utc)


def _conversation_start_date_from_state(user_state: Dict[str, Any]) -> Optional[date]:
    raw = (user_state or {}).get("conversation_started_at")
    if not raw or not isinstance(raw, str):
        return None
    try:
        dtp = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(dtp).date()
    except (ValueError, OSError, TypeError):
        return _parse_iso_date(str(raw)[:10])


# Initialize payment verification agent
payment_verification_agent_base = BaseAgent(
    system_prompt="""You are the **payment specialist**. Calm, precise, fraud-aware. Your job is to verify payment claimed to be made for a product.
    You verify this using either paystack or conversing with the business owner to ascertain if said amount for said product and quantity was indeed made given the sender's details.

**Workflow**
1. **Online payment (Paystack)**: if customer used paystack link, call `verify_payment_link` with the transaction reference. On success → `notify_payment_outcome(payment_confirmed=True, ...)`.
2. **Bank transfer / receipt (no Paystack link)**: You will receive a `[Payment context]` with transaction/receipt details. Call `verify_bank_receipt_against_business` first. If all checks pass → `notify_payment_outcome(payment_confirmed=True, ...)` to create the order. If checks fail, inform the customer clearly and ask for a valid receipt.
3. **Ambiguous**: If you have low confidence, call `notify_payment_outcome(payment_confirmed=False, receipt_details=..., transaction_reference=...)` to ask the vendor to confirm manually.

**Rules**
- Run `verify_bank_receipt_against_business` when you have numeric/structured fields before claiming bank-transfer status.
- Reassure with realistic timelines (vendor often reviews within a few hours).""",
    deps_type=PaymentVerificationDeps
)

payment_verification_agent = payment_verification_agent_base.agent


async def _pv_user_state(ctx: RunContext[PaymentVerificationDeps]) -> Dict[str, Any]:
    if ctx.deps.user_state is not None:
        return ctx.deps.user_state
    return await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {}


async def _run_notify_vendor_for_confirmation(
    ctx: RunContext[PaymentVerificationDeps],
    product_name: str,
    amount: float,
    process_id: Optional[str] = None,
    task_type: Optional[TaskType] = None,
    transaction_reference: Optional[Dict[Any, str]] = None,
    receipt_details: Optional[str] = None,
) -> Dict[str, Any]:
    """Send vendor a payment-confirmation request via central (shared by tool + auto path after verify)."""
    us = await _pv_user_state(ctx)
    tt = task_type or TaskType.PAYMENT_VERIFICATION
    pid = ensure_central_process(
        us,
        task_type=tt,
        customer_id=ctx.deps.user_id,
        vendor_id=ctx.deps.business_id,
        product_name=product_name,
        process_id=process_id,
    )
    await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, us)
    agent_input = await create_structured_input(
        sender=EntityType.AGENT,
        recipient=EntityType.VENDOR,
        message=f"Payment verification request: Customer claims payment for product '{product_name}', Amount: ${amount}. Receipt details: {receipt_details}, Transaction reference: {transaction_reference}. Please confirm if payment was received.",
        customer=Customer(id=ctx.deps.user_id),
        business=Vendor(id=ctx.deps.business_id),
        product=Product(id="", name=product_name, quantity=1, price=amount),
        process_id=pid,
        task_type=tt,
    )
    try:
        await run_central_agent(
            event_message=agent_input,
            user_state=us,
            caller_agent="payment_verification_agent",
        )
    except Exception as e:
        return {"status": "error", "message": f"Error notifying vendor: {e}"}
    return {
        "status": "vendor_notified",
        "message": "Vendor notified. When vendor confirms payment, call notify_central_payment_confirmed to create order.",
    }


@payment_verification_agent.tool
async def verify_payment_link(
    ctx: RunContext[PaymentVerificationDeps],
    transaction_reference: str,
) -> Dict[str, Any]:
    """Verify payment status via Paystack (vendor secret key). Returns verified=True if payment succeeded."""
    ref = (transaction_reference or "").strip()
    if not ref:
        return {"verified": False, "message": "Missing transaction reference."}

    us = await _pv_user_state(ctx)
    for entry in us.get("paystack_webhook_confirmed") or []:
        if isinstance(entry, dict) and entry.get("reference") == ref:
            ak = entry.get("amount_kobo")
            amt = kobo_to_major(int(ak)) if ak is not None else None
            return {
                "verified": True,
                "amount": amt,
                "message": "Already confirmed via Paystack webhook.",
            }

    biz = us.get("business_information") or await get_business_info(ctx.deps.business_id) or {}
    secret = (biz.get("paystack_secret_key") or "").strip()
    if not secret:
        return {"verified": False, "message": "Paystack not configured for this vendor."}

    out = await verify_transaction(secret, ref)
    if not out.get("ok"):
        return {"verified": False, "message": out.get("message", "Verification failed")}
    if out.get("verified"):
        return {
            "verified": True,
            "amount": out.get("amount_major"),
            "currency": out.get("currency"),
            "message": out.get("message", "success"),
        }
    return {"verified": False, "message": out.get("message", "Payment not successful yet.")}


@payment_verification_agent.tool
async def modify_task_type_for_process_id(
    ctx: RunContext[PaymentVerificationDeps],
    process_id: str,
    task_type: TaskType,
) -> Dict[str, Any]:
    """Modify task type for the current (existing) process. Use this to change the task type from PAYMENT_VERIFICATION to logistics coordination once payment has been verified either by vendor or through paystack."""
    us = await _pv_user_state(ctx)
    pid = ensure_central_process(
        us,
        task_type=task_type or TaskType.PAYMENT_VERIFICATION,
        customer_id=ctx.deps.user_id,
        vendor_id=ctx.deps.business_id,
        process_id=process_id,
    )
    proc = us.get("processes", {}).get(pid)
    if not isinstance(proc, dict):
        return {"status": "error", "message": f"Process {pid!r} not found."}
    proc["task_type"] = task_type
    us["processes"][pid] = proc
    await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, us)
    return {"status": "success", "message": f"Task type modified to {task_type.value}."}

# @payment_verification_agent.tool
# async def verify_amount_paid(ctx: RunContext[PaymentVerificationDeps], product_unit_price: float, quantity: float, amount_paid_by_customer: float) -> Dict[str, Any]:
#     """Verify amount paid for the product. This is used to verify the amount paid for the product by the customer.
#     You must call this function (before calling notify_central_payment_confirmed) if a receipt is uploaded by the customer to match amounts with the product unit price and quantity.
#     """
#     if amount_paid_by_customer < product_unit_price * quantity: 
#         return {"verified": False, "detail": "Amount paid by customer is less than the product unit price * quantity."}           
#     if amount_paid_by_customer > product_unit_price * quantity: 
#         return {"verified": False, "detail": "Amount paid by customer is greater than the product unit price * quantity."}
#     if amount_paid_by_customer == product_unit_price * quantity: 
#         return {"verified": True, "detail": "Amount paid by customer is equal to the product unit price * quantity."}
#     return {"verified": False, "detail": "Amount paid by customer is not equal to the product unit price * quantity."}


@payment_verification_agent.tool
async def verify_bank_receipt_against_business(
    ctx: RunContext[PaymentVerificationDeps],
    amount_paid: float,
    product_unit_price: float,
    quantity: float,
    receiver_account_on_receipt: str = "",
    receipt_date: str = "",
    receipt_time: str = "",
) -> Dict[str, Any]:
    """Deterministic checks: `amount_paid` from receipt; `product_unit_price` and `quantity` from session PRODUCT DETAILS (catalog), not the receipt. YYYY-MM-DD for receipt_date; receipt_time e.g. 14:30."""
    us = await _pv_user_state(ctx)

    def _done(result: Dict[str, Any]) -> Dict[str, Any]:
        try:
            line = json.dumps(result, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            line = repr(result)
        if len(line) > 24000:
            line = line[:24000] + "…[truncated]"
        logger.info("verify_bank_receipt_against_business return | %s", line)
        return result

    try:
        exp = float(product_unit_price) * float(quantity)
        amount_ok = abs(float(amount_paid) - exp) <= BANK_RECEIPT_AMOUNT_TOLERANCE
    except (TypeError, ValueError) as _fe:
        return _done({"all_passed": False, "checks": {"amount": {"ok": False,
            "detail": f"non-numeric value — product_unit_price={product_unit_price!r} quantity={quantity!r} amount_paid={amount_paid!r}: {_fe}"}}})
    amount_detail = "ok" if amount_ok else f"expected {exp}, receipt shows {amount_paid}"

    biz = us.get("business_information") or await get_business_info(ctx.deps.business_id) or {}
    expected_acct = _digits(str(biz.get("bank_account_number") or ""))
    recv = _digits(receiver_account_on_receipt or "")
    if not expected_acct:
        return _done(
            {
                "all_passed": False,
                "checks": {
                    "amount": {"ok": amount_ok, "detail": amount_detail},
                    "receiver_account": {
                        "ok": False,
                        "detail": "Business bank account not on file — set bank_account_number for this store.",
                    },
                },
            }
        )
    if not recv:
        return _done(
            {
                "all_passed": False,
                "checks": {
                    "amount": {"ok": amount_ok, "detail": amount_detail},
                    "receiver_account": {
                        "ok": False,
                        "detail": "No beneficiary/receiver account in prompt — conversational agent should pass it in [Payment context].",
                    },
                },
            }
        )
    acct_match = (expected_acct == recv) or (
        len(recv) >= 6
        and (expected_acct.endswith(recv) or recv.endswith(expected_acct))
    )
    acct_ok = acct_match
    acct_detail = "ok" if acct_ok else f"receipt {recv!r} vs business {expected_acct!r}"

    conv_d = _conversation_start_date_from_state(us)
    rd = _parse_iso_date((receipt_date or "").strip()[:10]) if (receipt_date or "").strip() else None
    if rd is None:
        date_ok = False
        date_detail = "receipt date missing (pass YYYY-MM-DD from receipt)"
    elif conv_d is not None and rd < conv_d:
        date_ok = False
        date_detail = f"receipt date {rd} before thread start {conv_d}"
    else:
        date_ok = True
        date_detail = (
            f"receipt {rd} on/after thread {conv_d}"
            if conv_d is not None
            else f"receipt {rd} (no conversation_started_at in state)"
        )

    rdt_utc = _parse_receipt_datetime_utc(
        (receipt_date or "").strip() or None, (receipt_time or "").strip() or None
    )
    now = datetime.now(timezone.utc)
    if rdt_utc is None or not (receipt_date or "").strip():
        time_ok, time_detail = False, "need receipt date (and time if possible) for recency"
    else:
        if rdt_utc > now:
            time_ok, time_detail = False, "receipt time is in the future"
        else:
            delta_h = (now - rdt_utc).total_seconds() / 3600.0
            time_ok = delta_h <= float(BANK_RECEIPT_MAX_AGE_HOURS)
            time_detail = (
                f"ok within {BANK_RECEIPT_MAX_AGE_HOURS}h"
                if time_ok
                else f"receipt is {delta_h:.1f}h old; max {BANK_RECEIPT_MAX_AGE_HOURS}h"
            )

    all_passed = bool(amount_ok and acct_ok and date_ok and time_ok)
    out: Dict[str, Any] = {
        "all_passed": all_passed,
        "checks": {
            "amount": {"ok": amount_ok, "detail": amount_detail},
            "receiver_account": {"ok": acct_ok, "detail": acct_detail},
            "receipt_on_or_after_conversation_start": {"ok": date_ok, "detail": date_detail},
            "receipt_recency": {"ok": time_ok, "detail": time_detail},
        },
    }
    if all_passed:
        pname = _product_name_for_notify(us, (ctx.deps.process_id or "").strip() or None)
        rdetail = (
            f"Auto checks passed: amount_paid={amount_paid} vs line={exp} "
            f"acct_ok date={receipt_date} time={receipt_time or 'n/a'}"
        )
        out["vendor_notification"] = await _run_notify_vendor_for_confirmation(
            ctx,
            product_name=pname,
            amount=float(amount_paid),
            process_id=ctx.deps.process_id,
            receipt_details=rdetail,
        )
    return _done(out)

@payment_verification_agent.tool
async def notify_payment_outcome(
    ctx: RunContext[PaymentVerificationDeps],
    product_name: str,
    amount: float,
    payment_confirmed: bool,
    process_id: Optional[str] = None,
    task_type: Optional[TaskType] = None,
    quantity: int = 1,
    delivery_address: Optional[str] = None,
    transaction_reference: Optional[str] = None,
    receipt_details: Optional[str] = None,
) -> Dict[str, Any]:
    """Single exit point after payment decision.

    Set `payment_confirmed=True` when payment is verified (Paystack success OR all
    `verify_bank_receipt_against_business` checks pass) — creates the order via central
    and alerts the vendor.

    Set `payment_confirmed=False` when you need the vendor to manually confirm an
    ambiguous or unverifiable payment — sends a verification request to the vendor
    with `receipt_details` and/or `transaction_reference`; the vendor replies through
    the business chat to finalise the order.
    """
    if payment_confirmed:
        us = await _pv_user_state(ctx)
        pid = ensure_central_process(
            us,
            task_type=task_type or TaskType.PAYMENT_VERIFICATION,
            customer_id=ctx.deps.user_id,
            vendor_id=ctx.deps.business_id,
            product_name=product_name,
            process_id=process_id,
        )
        proc = us.get("processes", {}).get(pid) or {}
        proc["amount"] = amount
        proc["quantity"] = quantity
        proc["delivery_address"] = delivery_address
        us.setdefault("processes", {})[pid] = proc
        await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, us)
        agent_input = await create_structured_input(
            sender=EntityType.AGENT,
            recipient=EntityType.AGENT,
            message=(
                f"Payment confirmed. Create order: product={product_name}, quantity={quantity}, "
                f"amount={amount}. Delivery address: {delivery_address or 'To be collected'}"
            ),
            customer=Customer(id=ctx.deps.user_id),
            business=Vendor(id=ctx.deps.business_id),
            product=Product(id="", name=product_name, quantity=quantity, price=amount),
            process_id=pid,
            task_type=task_type or TaskType.PAYMENT_VERIFICATION,
        )
        try:
            await run_central_agent(
                event_message=agent_input,
                user_state=us,
                caller_agent="payment_verification_agent.notify_payment_outcome",
            )
            return {"status": "order_created", "message": "Central agent notified. Order will be created."}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    else:
        return await _run_notify_vendor_for_confirmation(
            ctx,
            product_name=product_name,
            amount=amount,
            process_id=process_id,
            task_type=task_type,
            transaction_reference=transaction_reference,
            receipt_details=receipt_details,
        )


async def run_verification_agent(
    customer_message: str,
    user_id: str,
    business_id: str,
    product_name: Optional[str] = None,
    user_state: Optional[Dict[str, Any]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    receipt_data: Optional[str] = None,
    order_id: Optional[str] = None,
    debug: bool = False,
    append_chat_history: bool = True,
    instructions: Optional[str] = None,
    process_id: Optional[str] = None,
    quantity: Optional[float] = None,
) -> str:
    """
    Run payment verification agent with dynamic business and product details.

    Args:
        customer_message: Customer message with payment details
        user_id: User ID
        business_id: Business ID
        product_name: Product being verified
        user_state: Optional user state
        background_tasks: Background tasks
        receipt_data: Extracted receipt data from file processing
        order_id: Optional ongoing order UUID for prompt context
        debug: Debug mode

    Returns:
        Verification response message
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)

    proc = get_process_snapshot(user_state, process_id)
    if proc:
        if (not order_id or not str(order_id).strip()) and proc.get("order_id"):
            order_id = str(proc.get("order_id")).strip()
        if (not product_name or product_name.strip().upper() == "NONE") and proc.get("product_name"):
            product_name = str(proc.get("product_name") or "").strip()

    business_info = user_state.get("business_information", {})
    if not business_info:
        business_info = await get_business_info(business_id) or {}
        user_state["business_information"] = business_info

    products_cache = user_state.get("products", {})
    product_price = None
    product_currency: Optional[str] = None

    if product_name and product_name.strip().upper() != "NONE":
        for cache in products_cache.values():
            for p in cache.get("retrieved_results", []):
                pname = p.get("name") or p.get("product_name", "")
                if pname and pname.lower() == product_name.lower():
                    product_name = pname
                    product_price = p.get("price")
                    product_currency = str(p.get("currency") or "").strip() or None
                    break
            if product_price is not None:
                break

    if (not product_name or product_name.strip().upper() == "NONE") and products_cache:
        latest_product_key = max(
            products_cache,
            key=lambda k: products_cache[k].get("_ts", 0) if isinstance(products_cache[k], dict) else 0,
        )
        products = products_cache[latest_product_key].get("retrieved_results", [])
        if products:
            product_info = products[0]
            product_name = product_info.get("name") or product_info.get("product_name")
            product_price = product_info.get("price")
            product_currency = str(product_info.get("currency") or "").strip() or None

    line_qty: float = 1.0
    if quantity is not None:
        try:
            line_qty = max(0.01, float(quantity))
        except (TypeError, ValueError):
            line_qty = 1.0
    elif proc and proc.get("quantity") is not None:
        try:
            line_qty = max(0.01, float(proc.get("quantity")))
        except (TypeError, ValueError):
            line_qty = 1.0

    # Build dynamic prompt with business and product details
    dynamic_prompt_parts = []

    if proc and (process_id or "").strip():
        dynamic_prompt_parts.append(format_handoff_process_context(str(process_id).strip(), proc))

    if business_info:
        dynamic_prompt_parts.append("\n**BUSINESS ACCOUNT DETAILS:**")
        if business_info.get("bank_name"):
            dynamic_prompt_parts.append(f"Bank Name: {business_info['bank_name']}")
        if business_info.get("bank_account_name"):
            dynamic_prompt_parts.append(f"Account Name: {business_info['bank_account_name']}")
        if business_info.get("bank_account_number"):
            dynamic_prompt_parts.append(f"Account Number: {business_info['bank_account_number']}")

    if product_name:
        cur = (
            str(product_currency or "").strip()
            or str(business_info.get("currency") or "").strip()
            or "NGN"
        )
        dynamic_prompt_parts.append("\n**PRODUCT DETAILS:**")
        dynamic_prompt_parts.append(f"Product Name: {product_name}")
        if product_price is not None:
            dynamic_prompt_parts.append(f"Product Price (per unit): {product_price} {cur}")
        else:
            dynamic_prompt_parts.append("Product Price: Unknown")
        dynamic_prompt_parts.append(f"Intended quantity: {line_qty} (for verify_bank_receipt_against_business)")
        if product_price is not None:
            try:
                dynamic_prompt_parts.append(
                    f"Expected line total: {float(product_price) * line_qty} {cur}"
                )
            except (TypeError, ValueError):
                pass

    csa = user_state.get("conversation_started_at")
    if csa:
        dynamic_prompt_parts.append(
            f"\n**Thread started (receipt date must be on/after this, ISO):** {csa}"
        )

    if order_id and str(order_id).strip():
        dynamic_prompt_parts.append(f"\n**ORDER CONTEXT:** order_id={order_id.strip()}")

    dynamic_prompt = "\n".join(dynamic_prompt_parts)

    deps = PaymentVerificationDeps(
        user_id=user_id,
        business_id=business_id,
        user_state=user_state,
        process_id=(process_id or "").strip() or None,
    )

    prompt = f"{customer_message}\n{dynamic_prompt}" if dynamic_prompt else customer_message
    run_kw: Dict[str, Any] = {}
    if instructions and instructions.strip():
        run_kw["instructions"] = instructions.strip()
    result = await payment_verification_agent.run(prompt, deps=deps, **run_kw)
    response = result.output
    
    if append_chat_history:
        user_state.setdefault("chat_history", []).extend([
            ModelRequest(parts=[UserPromptPart(content=customer_message)]),
            ModelResponse(parts=[TextPart(content=response)]),
        ])

    if receipt_data:
        user_state["receipt_data"] = receipt_data

    await save_user_state(user_id, business_id, user_state)

    return response
