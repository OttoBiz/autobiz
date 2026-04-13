"""
Conversational agent — single orchestrator for the customer chat channel.
Delegates to specialists via tools. Session product cache is passed via `instructions` each run.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import RunContext

from backend.chatbot.agents.base_agent import BaseAgent
from backend.chatbot.utils.agent_trace_stdout import agent_stdout
from backend.db.db_utils import (
    browse_available_products as db_browse_available_products,
    get_conversation_uploaded_file,
    get_order_by_id,
)

from backend.chatbot.agents.product_agent import run_product_agent
from backend.chatbot.agents.payment_verification_agent import run_verification_agent
from backend.chatbot.agents.logistics_agent import run_logistics_agent
from backend.chatbot.agents.customer_complaint_agent import run_customer_complaint_agent
from backend.chatbot.agents.ads_marketing_agent import run_ads_marketing_agent
from backend.chatbot.agents.upselling_agent import run_upselling_agent


def _format_products_cache(products: Optional[Dict[str, Any]]) -> str:
    """Human-readable snapshot of user_state['products'] for model context."""
    if not products:
        return ""
    lines: List[str] = []
    for cache_key, blob in products.items():
        if not isinstance(blob, dict):
            continue
        results = blob.get("retrieved_results") or []
        if not results:
            lines.append(f"- query_key={cache_key!r}: (no rows cached)")
            continue
        bits = []
        for p in results[:8]:
            name = p.get("name") or p.get("product_name") or "?"
            price = p.get("price")
            cur = (p.get("currency") or "").strip() or "NGN"
            if str(cache_key).startswith("__browse_"):
                bits.append(f"{name} @ {price} {cur}")
            else:
                stock = p.get("stock_quantity", p.get("items_left_in_stock", "?"))
                bits.append(f"{name} @ {price} {cur} (stock {stock})")
        lines.append(f"- query_key={cache_key!r}: " + "; ".join(bits))
    return "\n".join(lines) if lines else ""


class ConversationalAgentDeps(BaseModel):
    """Mutable user_state is shared by reference across tool calls."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    business_id: str
    business_name: str = ""
    order_context_summary: str = Field(
        default="",
        description="Short text summary of active orders (product -> order_id) for the prompt.",
    )
    user_state: Dict[str, Any]
    receipt_data: Optional[str] = None
    background_tasks: Optional[Any] = None


CONVERSATIONAL_SYSTEM_PROMPT = """
You are the **primary store associate and professional salesperson** for this business—the only voice the customer hears. You are a highly persuasive, proactive, and charming human salesperson (do not sound like a robotic AI). Your ultimate goal is to **close the sale**. 

Replies must be **short, chatty messages** (strictly 1–3 sentences), not essays or bullet questionnaires. Take the initiative to drive the conversation forward—never leave the burden on the customer. Use your "sweet mouth," tap into psychology and emotions, and have honest, relatable discussions to discover their tastes and sell effectively.

**Customer journey (tools)**
1. **Discovery & Sales Pitch** — vague browse ("what do you have?", "surprise me") -> `browse_available_products`. **Any specific product, model, color, storage, or "do you have X"** -> `handoff_to_product_specialist` with that product name. (Do **not** answer from general knowledge or guess catalog contents). Once a product is identified, hype it up and confidently persuade the user to buy it!
2. **Unavailable / Wrong Item / Rejections** — after specialist -> `handoff_to_upsell_specialist`. If their desired product isn't available, or they reject an offer, handle it politely. Ask a quick question to gauge their preferences, and fiercely pitch a compelling alternative.
3. **Checkout / Pay** -> `handoff_to_payment_specialist`.
4. **Delivery / Tracking** -> `handoff_to_logistics_specialist` (use `get_order_and_process_details` if you need order facts first).
5. **Post-Purchase Complements (Cross-selling)** -> `handoff_to_ads_marketing_specialist`. Once a purchase and delivery are sorted, the selling doesn't stop. Proactively recommend and pitch complementary products based on what you've learned about the user.
6. **Complaints** -> `handoff_to_complaint_specialist`.

**Context**
- Instructions may include session product cache, active processes (with `order_id` / `order_number` when known), and an active-orders summary. That is your **internal context**—never tell the customer about it.

**Strict customer-facing rules**
- **Markdown requirement:** Always use **Markdown** (e.g., bullets, bold text) whenever you are listing or highlighting products.
- Never invent prices, stock, or tracking.
- Never tell the customer to visit an external website, email the store, or leave this chat for product help. Keep them in-app.
- Do not paste raw **product IDs**, **stock counts**, or **internal categories** unless the customer explicitly asks for technical detail.
- Do not present long "pick one of four options" menus. Instead, offer one clear next step or a brief, highly persuasive recommendation.
- One specialist handoff per turn (`handoff_to_*`). `browse_available_products` is not a handoff.
"""


conversational_agent_base = BaseAgent(
    system_prompt=CONVERSATIONAL_SYSTEM_PROMPT,
    deps_type=ConversationalAgentDeps,
    output_type=str,
)

conversational_agent = conversational_agent_base.agent


@conversational_agent.tool
async def browse_available_products(
    ctx: RunContext[ConversationalAgentDeps],
    n: int = 8,
    selection_mode: str = "top_stock",
    user_enquiry: str = "",
) -> str:
    """Fetch in-stock items for this store. `selection_mode`: `top_stock` (best availability) or `random`. Optional `user_enquiry` narrows by name/description/category. Returns **customer-safe** lines (name + price only)—tell the customer in chat style; do not add IDs or stock numbers."""
    mode = (selection_mode or "top_stock").strip().lower()
    if mode not in ("top_stock", "random"):
        mode = "top_stock"
    n_clamped = max(1, min(int(n), 20))
    q = (user_enquiry or "").strip() or None

    rows = await db_browse_available_products(
        ctx.deps.business_id,
        limit=n_clamped,
        mode=mode,
        search=q,
    )
    if not rows:
        hint = f" (narrower filter: {q!r})" if q else ""
        return (
            f"[For assistant] No in-stock matches{hint}. "
            f"Say briefly we don't have matches and offer `handoff_to_product_specialist` if they have a specific item in mind."
        )

    q_tag = hashlib.sha256(q.encode("utf-8")).hexdigest()[:12] if q else ""
    cache_key = f"__browse_{mode}__" + (f"_{q_tag}" if q_tag else "")
    ctx.deps.user_state.setdefault("products", {})[cache_key] = {
        "retrieved_results": rows,
        "db_queried": True,
        "_ts": time.time(),
    }

    customer_lines: List[str] = []
    for p in rows:
        name = p.get("name") or p.get("product_name") or "?"
        price = p.get("price")
        cur = (p.get("currency") or "").strip() or "NGN"
        customer_lines.append(f"• {name} — {price} {cur}")
        _track_product_discussed(ctx.deps.user_state, str(name))

    return (
        "[For assistant] Use the bullets below when talking to the customer—friendly, short. "
        "Do **not** read out categories, stock counts, or product IDs.\n\n"
        + "\n".join(customer_lines)
    )


@conversational_agent.tool
async def get_order_and_process_details(
    ctx: RunContext[ConversationalAgentDeps],
    product_name_hint: Optional[str] = None,
) -> str:
    """Orders in session (`processes`) plus DB rows when order_id is known."""
    st = ctx.deps.user_state
    processes = st.get("processes") or {}
    if not isinstance(processes, dict) or not processes:
        return "No orders in session yet. processes is empty."

    lines: List[str] = []
    for process_id, proc in processes.items():
        if not isinstance(proc, dict):
            continue
        if product_name_hint:
            ph = product_name_hint.lower()
            pnm = (proc.get("product_name") or "").lower()
            pid_s = str(process_id).lower()
            if ph not in pnm and ph not in pid_s and pnm not in ph and pid_s not in ph:
                continue
        oid = proc.get("order_id")
        chunk = (
            f"process_id={process_id!r}; task_type={proc.get('task_type')!r}; "
            f"product={proc.get('product_name')!r}; order_id={oid}; order_number={proc.get('order_number')}; "
            f"status={proc.get('status')}; quantity={proc.get('quantity')}; "
            f"customer_address={proc.get('customer_address')}"
        )
        lines.append(chunk)
        if oid:
            try:
                order = await get_order_by_id(str(oid))
                if order:
                    lines.append(
                        f"  [DB] order_number={order.get('order_number')}; status={order.get('status')}; "
                        f"tracking_number={order.get('tracking_number')}; "
                        f"delivery_address={order.get('delivery_address')}"
                    )
            except Exception as e:
                lines.append(f"  [DB] lookup failed: {e}")

    if not lines:
        return "No matching processes for that product hint, or processes empty."
    return "\n".join(lines)


@conversational_agent.tool
async def list_session_uploads(ctx: RunContext[ConversationalAgentDeps]) -> str:
    """Summarize files attached this session (file_id, filename, type, description)."""
    refs = ctx.deps.user_state.get("uploaded_files") or []
    if not refs:
        return "No files recorded for this session."
    lines = []
    for r in refs:
        lines.append(
            f"id={r.get('file_id')} name={r.get('filename')} type={r.get('file_content_type')} — {r.get('description', '')[:120]}"
        )
    return "\n".join(lines)


@conversational_agent.tool
async def get_uploaded_file_content(
    ctx: RunContext[ConversationalAgentDeps], file_id: str
) -> str:
    """Load full extracted text for an upload: session cache first, else database."""
    if not file_id.strip():
        return "file_id required."
    cache = (ctx.deps.user_state.get("file_text_cache") or {}).get(file_id)
    if cache:
        return str(cache)
    row = await get_conversation_uploaded_file(
        file_id, ctx.deps.user_id, ctx.deps.business_id
    )
    if not row:
        return "File not found or not accessible for this customer/store."
    return row.get("text_content") or ""


def _track_product_discussed(user_state: Dict[str, Any], name: str) -> None:
    n = (name or "").strip()
    if not n or n.upper() == "NONE":
        return
    lst: List[str] = user_state.setdefault("products_discussed", [])
    low = {x.lower() for x in lst}
    if n.lower() not in low:
        lst.append(n)


@conversational_agent.tool
async def handoff_to_product_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    product_name: str,
    product_category: str = "",
    intent: str = "enquiry",
    sales_context: str = "",
    product_attributes: str = "",
) -> str:
    """Delegate to the product specialist for **specific** items: availability, price, specs, purchase. They query the real catalog and notify the vendor when something is missing—use this whenever the customer names a product or model."""
    msg = customer_message
    if sales_context:
        msg = f"{customer_message}\n\n[Sales context for specialist]\n{sales_context}"
    pa = product_attributes.strip() or None
    out, ctx.deps.user_state = await run_product_agent(
        customer_message=msg,
        product_name=product_name or "NONE",
        product_category=product_category or "",
        intent=intent if intent in ("enquiry", "purchase") else "enquiry",
        user_id=ctx.deps.user_id,
        business_id=ctx.deps.business_id,
        user_state=ctx.deps.user_state,
        product_attributes_json=pa,
        append_chat_history=False,
    )
    _track_product_discussed(ctx.deps.user_state, product_name)
    if pa:
        try:
            blob = json.loads(pa)
            if isinstance(blob, dict):
                guess = blob.get("product_name") or blob.get("name")
                if guess:
                    _track_product_discussed(ctx.deps.user_state, str(guess))
        except json.JSONDecodeError:
            pass
    return out


@conversational_agent.tool
async def handoff_to_payment_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    product_name: Optional[str] = None,
    order_id: Optional[str] = None,
    notes: str = "",
) -> str:
    """Delegate to the payment specialist for payment inquiries & verification. They verify the payment and notify the vendor when something is missing—use this whenever the customer names a product or model."""
    msg = customer_message
    if notes:
        msg = f"{customer_message}\n\n[Payment context]\n{notes}"
    return await run_verification_agent(
        customer_message=msg,
        user_id=ctx.deps.user_id,
        business_id=ctx.deps.business_id,
        product_name=product_name,
        user_state=ctx.deps.user_state,
        background_tasks=ctx.deps.background_tasks,
        receipt_data=ctx.deps.receipt_data,
        order_id=order_id,
        append_chat_history=False,
    )


@conversational_agent.tool
async def handoff_to_logistics_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    product_name: Optional[str] = None,
    order_id: Optional[str] = None,
    notes: str = "",
) -> str:
    """Delegate to the logistics specialist for delivery and tracking inquiries. They query the real catalog and notify the vendor when something is missing—use this whenever the customer names a product or model."""
    msg = customer_message
    if notes:
        msg = f"{customer_message}\n\n[Logistics context]\n{notes}"
    return await run_logistics_agent(
        customer_message=msg,
        user_id=ctx.deps.user_id,
        business_id=ctx.deps.business_id,
        product_name=product_name,
        user_state=ctx.deps.user_state,
        background_tasks=ctx.deps.background_tasks,
        order_id=order_id,
        append_chat_history=False,
    )


@conversational_agent.tool
async def handoff_to_complaint_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    product_name: str = "",
    issue_summary: str = "",
) -> str:
    """Delegate to the complaint specialist for complaints and issues. They handle complaints and issues and notify the vendor when something is missing—use this whenever the customer names a product or model."""
    msg = customer_message
    if issue_summary:
        msg = f"{customer_message}\n\n[Issue summary]\n{issue_summary}"
    out, ctx.deps.user_state = await run_customer_complaint_agent(
        customer_message=msg,
        product_name=product_name or "",
        user_id=ctx.deps.user_id,
        business_id=ctx.deps.business_id,
        user_state=ctx.deps.user_state,
        background_tasks=ctx.deps.background_tasks,
        append_chat_history=False,
    )
    return out


@conversational_agent.tool
async def handoff_to_ads_marketing_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    purchased_product: str,
    logistics_context: str = "",
) -> str:
    """Post-purchase: complements after logistics sorted. Not for unavailable-product substitution. upsell complimentary products"""
    return await run_ads_marketing_agent(
        customer_message=customer_message,
        purchased_product=purchased_product,
        business_id=ctx.deps.business_id,
        user_state=ctx.deps.user_state,
        logistics_summary=logistics_context,
    )


@conversational_agent.tool
async def handoff_to_upsell_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    product: str,
    situation_summary: str = "",
    product_attributes: str = "",
) -> str:
    """When the enquired item is unavailable: upsell alternatives / complements from tools."""
    hist = ctx.deps.user_state.get("chat_history") or []
    situ = (situation_summary or "").strip()
    if product_attributes.strip():
        situ = f"{situ}\n[Product attribute hints]\n{product_attributes.strip()}".strip()
    _track_product_discussed(ctx.deps.user_state, product)
    return await run_upselling_agent(
        product=product,
        conversation_messages=hist,
        business_id=ctx.deps.business_id,
        situation_summary=situ,
        user_state=ctx.deps.user_state,
    )


async def run_conversational_agent(
    user_message: str,
    chat_history: list,
    user_id: str,
    business_id: str,
    user_state: Dict[str, Any],
    business_name: Optional[str] = None,
    order_context_summary: Optional[str] = None,
    receipt_data: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    debug: bool = False,
    polish_only: bool = False,
) -> str:
    """
    Run conversational orchestrator; caller appends one user + one assistant turn to chat_history.
    Product cache is injected via `instructions` (dynamic adjunct to system context).
    """
    deps = ConversationalAgentDeps(
        user_id=user_id,
        business_id=business_id,
        business_name=business_name or "",
        order_context_summary=order_context_summary or "",
        user_state=user_state,
        receipt_data=receipt_data,
        background_tasks=background_tasks,
    )

    header = []
    bi = user_state.get("business_information") or {}
    display_name = business_name or (bi.get("name") or "")
    if display_name:
        header.append(f"Business name: {display_name}")
    biz_bits = []
    if bi.get("business_type"):
        biz_bits.append(f"type={bi['business_type']}")
    if bi.get("tier") is not None and bi.get("tier") != "":
        biz_bits.append(f"tier={bi['tier']}")
    phone = bi.get("phone_number") or bi.get("human_agent_phone")
    if phone:
        biz_bits.append(f"phone={phone}")
    if bi.get("email"):
        biz_bits.append(f"email={bi['email']}")
    if biz_bits:
        header.append("Business: " + "; ".join(biz_bits))
    if order_context_summary:
        header.append(f"Active orders (summary): {order_context_summary}")

    procs = user_state.get("processes") or {}
    proc_lines: List[str] = []
    if isinstance(procs, dict):
        for pid, pr in procs.items():
            if isinstance(pr, dict):
                oid = pr.get("order_id")
                onum = pr.get("order_number")
                proc_lines.append(
                    f"- process_id={pid} order_id={oid or '—'} order_number={onum or '—'} "
                    f"product={pr.get('product_name') or '?'} task_type={pr.get('task_type') or '?'}"
                )
    if proc_lines:
        header.append("Active processes:\n" + "\n".join(proc_lines))

    prefix = "\n".join(header)

    cache_text = _format_products_cache(user_state.get("products"))
    pd = user_state.get("products_discussed") or []
    pd_line = (
        ("\n## products_discussed (canonical names for this session)\n" + ", ".join(pd))
        if pd
        else ""
    )
    cache_section = (
        ("## Session product cache: \n" + cache_text)
        if cache_text
        else ""
    )
    polish_block = ""
    if polish_only:
        polish_block = (
            "\n## Mode: draft polish only\n"
            "Rewrite the provided message for the customer channel (customers use and understanding). Keep every fact (amounts, order numbers, dates, next steps). "
            "At most 3–4 short sentences. **Do not use tools.** Output only the polished text.\n"
        )
    dynamic_instructions =  prefix + "\n" + cache_section + pd_line + polish_block

    agent_stdout("conversational_agent input", user_message)
    result = await conversational_agent.run(
        user_message,
        deps=deps,
        message_history=chat_history,
        instructions=dynamic_instructions,
    )
    out = result.output
    agent_stdout("conversational_agent output", str(out))
    if debug:
        print(f"conversational_agent | raw_output_type={type(out)}")
    return out
