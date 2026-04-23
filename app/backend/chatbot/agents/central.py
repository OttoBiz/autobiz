import asyncio
from typing import Any, Awaitable, Callable, Literal, NamedTuple

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from backend.chatbot import inbox
from backend.chatbot.agents.deps import AgentDeps
from backend.chatbot.messaging.reply import Reply
from backend.config import MODEL_NAME
from backend.db import outbound_ledger

SUBAGENT_TIMEOUT_SECONDS = 30


class Task(BaseModel):
    agent_name: Literal[
        "product", "payment", "logistics", "outbound"
    ] = Field(description="Which subagent to call.")
    # NOTE: "customer_relation" temporarily disabled — it was being invoked
    # for greetings/small-talk and looping the central agent. Re-enable by
    # adding it back to this Literal and uncommenting the registry entry below.
    prompt: str = Field(
        description="Detailed query for the subagent. Include all relevant context (product name, order id, amounts, etc)."
    )
    party_type: Literal["vendor", "logistics"] | None = Field(
        default=None,
        description=(
            "For agent_name='outbound' only: which external party to contact "
            "('vendor' for stock/restock/payment confirmation, 'logistics' for "
            "delivery/pickup coordination). Required when calling outbound; "
            "ignored otherwise."
        ),
    )


class SubagentDef(NamedTuple):
    description: str
    # outbound takes an extra `party_type` arg; product/payment/etc. don't.
    # _dispatch_task handles the per-handler call signature.
    handler: Callable[..., Awaitable[dict[str, Any]]]


async def _run_with_timeout(name: str, coro: Awaitable[Any]) -> dict[str, Any]:
    # Timeout fallback so a single hung subagent can't block the central reply;
    # the error dict surfaces to central so it can decide what to tell the customer.
    try:
        result = await asyncio.wait_for(coro, timeout=SUBAGENT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return {"error": "subagent_timeout", "subagent": name}
    return {"response": result.output}


async def _handle_product(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    from backend.chatbot.agents.product import product_agent

    return await _run_with_timeout("product", product_agent.run(prompt, deps=deps))


async def _handle_payment(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    from backend.chatbot.agents.payment import payment_verification_agent

    return await _run_with_timeout(
        "payment", payment_verification_agent.run(prompt, deps=deps)
    )


async def _handle_logistics(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    from backend.chatbot.agents.logistics import logistics_agent

    return await _run_with_timeout("logistics", logistics_agent.run(prompt, deps=deps))


async def _handle_customer_relation(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    from backend.chatbot.agents.customer_relation import customer_complaint_agent

    return await _run_with_timeout(
        "customer_relation", customer_complaint_agent.run(prompt, deps=deps)
    )


async def _handle_outbound(
    deps: AgentDeps, prompt: str, party_type: str | None = None
) -> dict[str, Any]:
    from backend.chatbot.agents.outbound import dispatch
    from backend.db.db_utils import get_business_info

    if party_type not in ("vendor", "logistics"):
        return {
            "error": "missing_party_type",
            "detail": (
                "outbound tasks require party_type='vendor' or 'logistics'. "
                "Re-issue the task with the correct party_type."
            ),
        }

    business_info = await get_business_info(str(deps.business_id))
    business_name = business_info.get("name", "") if business_info else None
    task_key = await dispatch(
        business_id=deps.business_id,
        customer_id=deps.customer_id,
        party=party_type,
        initiated_by="customer",
        dispatch_prompt=prompt,
        business_name=business_name,
        parent_depth=deps.current_depth,
    )
    return {"status": "pending", "task_key": task_key, "party": party_type}


def _register_handlers() -> dict[str, SubagentDef]:
    return {
        "product": SubagentDef(
            description="Look up product info, pricing, availability, and payment links for this business.",
            handler=_handle_product,
        ),
        "payment": SubagentDef(
            description="Verify a payment via receipt or payment link. Match amounts against known products.",
            handler=_handle_payment,
        ),
        "logistics": SubagentDef(
            description="Track orders, get delivery status, collect delivery addresses.",
            handler=_handle_logistics,
        ),
        # Temporarily disabled — was being called for greetings and looping.
        # "customer_relation": SubagentDef(
        #     description="Handle complaints, feedback, and escalation decisions.",
        #     handler=_handle_customer_relation,
        # ),
        "outbound": SubagentDef(
            description="Contact vendor or logistics. Returns immediately — runs in background. Use when you need human confirmation or info the system doesn't have.",
            handler=_handle_outbound,
        ),
    }


_SUBAGENTS: dict[str, SubagentDef] | None = None


def _get_subagents() -> dict[str, SubagentDef]:
    global _SUBAGENTS
    if _SUBAGENTS is None:
        _SUBAGENTS = _register_handlers()
    return _SUBAGENTS


model = MODEL_NAME

instructions = """
You are an AI sales assistant for a business. You help customers with product enquiries, purchases, payments, delivery, and complaints.

You have full conversation history and customer state. Use it to give contextual replies.

DECIDE FIRST — DO YOU NEED A SUBAGENT?

Reply DIRECTLY (no subagent) when the customer:
- Greets you ("hi", "hello", "good morning", "how are you")
- Says thanks, goodbye, or other small talk
- Asks who you are or what you do
- Asks something you can answer from general knowledge
- Sends a vague message — ask a clarifying question instead of guessing a subagent

Use a SUBAGENT only when you need data the system holds or external action:
{subagents}

PROCESS:
1. Read the customer's message and the conversation history.
2. If you need data, call `query_subagent` ONCE with every task you need bundled in the same call.
3. Take the subagent result, write your final reply, and STOP. Do NOT call `query_subagent` again about the same topic — pick the best wording from the result, do not "double-check" with another subagent call.
4. Never forward raw subagent output to the customer. Synthesize it in your own voice.

OUTBOUND:
- Use the "outbound" subagent when you need vendor or logistics input (stock check, payment confirmation, delivery coordination).
- ALWAYS set `party_type` on outbound tasks: "vendor" or "logistics".
- It returns immediately. Tell the customer you're on it ("checking with the vendor, one moment").
- Call `get_outbound_status` ONCE per turn (only if relevant) to fetch pending/resolved outbound tasks for this customer. Relay any newly-resolved outcomes in your reply.

RESPONSE FORMAT:
Plain prose only. No JSON, no markdown structure, no UI hints — the channel layer owns formatting.
"""


agent = Agent(
    model=model,
    deps_type=AgentDeps,
    output_type=Reply,
)


@agent.tool
async def query_subagent(
    ctx: RunContext[AgentDeps], tasks: list[Task]
) -> list[dict[str, Any]]:
    """Call one or more subagents in parallel. Each task specifies the subagent name and a detailed prompt."""
    results = await asyncio.gather(
        *(_dispatch_task(ctx.deps, task) for task in tasks),
        return_exceptions=True,
    )
    return [r if isinstance(r, dict) else {"error": str(r)} for r in results]


async def _dispatch_task(deps: AgentDeps, task: Task) -> dict[str, Any]:
    handler = _get_subagents()[task.agent_name].handler
    if task.agent_name == "outbound":
        return await handler(deps, task.prompt, task.party_type)
    return await handler(deps, task.prompt)


async def _fetch_outbound_status(
    business_id: Any, customer_id: Any
) -> dict[str, list[dict[str, str | None]]]:
    """Read pending + resolved-since-cursor for this customer; advance the cursor.

    Extracted from the tool body so it can be exercised directly in tests
    without standing up a full pydantic_ai RunContext.
    """
    biz_str = str(business_id)
    cust_str = str(customer_id)

    cursor = inbox.get_cursor(biz_str, cust_str)
    pending = await outbound_ledger.get_pending_for_customer(business_id, customer_id)
    resolved = await outbound_ledger.get_resolved_since(
        business_id, customer_id, cursor
    )

    if resolved:
        resolved_times = [r.resolved_at for r in resolved if r.resolved_at]
        if resolved_times:
            inbox.set_cursor(biz_str, cust_str, max(resolved_times))

    return {
        "pending": [{"party": t.party, "request": t.dispatch_prompt} for t in pending],
        "resolved": [
            {"party": t.party, "outcome": t.customer_context} for t in resolved
        ],
    }


@agent.tool
async def get_outbound_status(
    ctx: RunContext[AgentDeps],
) -> dict[str, list[dict[str, str | None]]]:
    """Fetch outbound vendor/logistics tasks for this customer.

    Returns:
    - pending: tasks still in progress (queued or running). Always shown.
    - resolved: tasks finished since the last call. Calling this tool advances
      a per-customer cursor, so each resolution is returned at most once —
      relay anything new in your current reply.
    """
    return await _fetch_outbound_status(ctx.deps.business_id, ctx.deps.customer_id)


@agent.instructions
def build_instructions(ctx: RunContext[AgentDeps]) -> str:
    subagent_list = "\n".join(
        f"- {name}: {sub.description}" for name, sub in _get_subagents().items()
    )
    return instructions.replace("{subagents}", subagent_list)
