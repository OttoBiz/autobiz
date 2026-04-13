"""
Payment Verification Agent - Verifies customer payments
Converted to pydantic_ai with media processing support
"""

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
from backend.chatbot.utils.agent_utils import get_or_create_user_state, save_user_state
from backend.db.db_utils import get_business_info
from backend.payments.paystack_client import kobo_to_major, verify_transaction

from .base_agent import BaseAgent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)


class PaymentVerificationDeps(BaseModel):
    """Dependencies for payment verification agent"""

    user_id: str
    business_id: str
    user_state: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None


# Initialize payment verification agent
payment_verification_agent_base = BaseAgent(
    system_prompt="""You are the **payment specialist**. Calm, precise, fraud-aware.

**Workflow**
1. **Online payment (Paystack)**: call `verify_payment_link` with the transaction reference (customer may paste it after paying, or webhook may have already confirmed). On success → `notify_central_payment_confirmed`.
2. **Bank transfer / receipt**: compare receipt details (amount, account) against the BUSINESS ACCOUNT DETAILS and PRODUCT DETAILS injected in the prompt. If they plausibly match → `notify_vendor_for_confirmation` so the vendor can verify. Only call `notify_central_payment_confirmed` after vendor confirms or policy rules are met.
3. **Ambiguous**: ask the customer for the missing detail (amount, reference, or screenshot).

**Rules**
- Never claim payment verified without tool confirmation.
- you must confirm that account details and product details are correct in the receipt and match the product the customer is purchasing and business account details.
- Reassure with realistic timelines ("the vendor typically reviews within a few hours").""",
    deps_type=PaymentVerificationDeps
)

payment_verification_agent = payment_verification_agent_base.agent


@payment_verification_agent.tool
async def verify_payment_link(
    ctx: RunContext[PaymentVerificationDeps],
    transaction_reference: str,
) -> Dict[str, Any]:
    """Verify payment status via Paystack (vendor secret key). Returns verified=True if payment succeeded."""
    ref = (transaction_reference or "").strip()
    if not ref:
        return {"verified": False, "message": "Missing transaction reference."}

    us = (
        ctx.deps.user_state
        if ctx.deps.user_state is not None
        else (await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {})
    )
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
async def notify_central_payment_confirmed(
    ctx: RunContext[PaymentVerificationDeps],
    product_name: str,
    amount: float,
    quantity: int = 1,
    delivery_address: Optional[str] = None,
) -> Dict[str, Any]:
    """Notify central agent that payment is confirmed. Central agent will create order in DB."""
    us = (
        ctx.deps.user_state
        if ctx.deps.user_state is not None
        else (await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {})
    )
    pid = ensure_central_process(
        us,
        task_type=TaskType.PAYMENT_VERIFICATION,
        customer_id=ctx.deps.user_id,
        vendor_id=ctx.deps.business_id,
        product_name=product_name,
    )
    await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, us)
    agent_input = await create_structured_input(
        sender=EntityType.AGENT,
        recipient=EntityType.AGENT,
        message=f"Payment confirmed. Create order: product={product_name}, quantity={quantity}, amount=${amount}. "
        f"Delivery address: {delivery_address or 'To be collected'}",
        customer=Customer(id=ctx.deps.user_id),
        business=Vendor(id=ctx.deps.business_id),
        product=Product(id="", name=product_name, quantity=quantity, price=amount),
        process_id=pid,
        task_type=TaskType.PAYMENT_VERIFICATION,
    )
    try:
        await run_central_agent(
            event_message=agent_input,
            user_state=us,
            caller_agent="payment_verification_agent.notify_central_payment_confirmed",
        )
        return {"status": "sent", "message": "Central agent notified. Order will be created."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@payment_verification_agent.tool
async def notify_vendor_for_confirmation(
    ctx: RunContext[PaymentVerificationDeps],
    product_name: str,
    amount: float,
    transaction_reference: Optional[Dict[Any, str]] = None,
    receipt_details: Optional[str] = None
) -> Dict[str, Any]:
    """Use this function to notify vendor to confirm payment verification"""
    us = (
        ctx.deps.user_state
        if ctx.deps.user_state is not None
        else (await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {})
    )
    pid = ensure_central_process(
        us,
        task_type=TaskType.PAYMENT_VERIFICATION,
        customer_id=ctx.deps.user_id,
        vendor_id=ctx.deps.business_id,
        product_name=product_name,
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
        task_type=TaskType.PAYMENT_VERIFICATION,
    )

    try:
        await run_central_agent(
            event_message=agent_input,
            user_state=us,
            caller_agent="payment_verification_agent.notify_vendor_for_confirmation",
        )
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error notifying vendor: {e}"
        }
    
    return {
        "status": "vendor_notified",
        "message": "Vendor notified. When vendor confirms payment, call notify_central_payment_confirmed to create order.",
    }


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
                    product_currency = (p.get("currency") or "").strip() or None
                    break
            if product_price is not None:
                break

    if (not product_name or product_name.strip().upper() == "NONE") and products_cache:
        latest_product_key = list(products_cache.keys())[0]
        latest_product_data = products_cache[latest_product_key]
        products = latest_product_data.get("retrieved_results", [])
        if products:
            product_info = products[0]
            product_name = product_info.get("name") or product_info.get("product_name")
            product_price = product_info.get("price")
            product_currency = (product_info.get("currency") or "").strip() or None

    # Build dynamic prompt with business and product details
    dynamic_prompt_parts = []

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
            (product_currency or "").strip()
            or (business_info.get("currency") or "").strip()
            or "NGN"
        )
        dynamic_prompt_parts.append("\n**PRODUCT DETAILS:**")
        dynamic_prompt_parts.append(f"Product Name: {product_name}")
        if product_price is not None:
            dynamic_prompt_parts.append(f"Product Price: {product_price} {cur}")
        else:
            dynamic_prompt_parts.append("Product Price: Unknown")

    if order_id and str(order_id).strip():
        dynamic_prompt_parts.append(f"\n**ORDER CONTEXT:** order_id={order_id.strip()}")

    dynamic_prompt = "\n".join(dynamic_prompt_parts)

    deps = PaymentVerificationDeps(
        user_id=user_id,
        business_id=business_id,
        user_state=user_state
    )

    prompt = f"{customer_message}\n{dynamic_prompt}" if dynamic_prompt else customer_message
    result = await payment_verification_agent.run(prompt, deps=deps)
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
