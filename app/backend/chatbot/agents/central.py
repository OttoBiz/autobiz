import asyncio
from typing import Any, Awaitable, Callable, Literal, NamedTuple

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from backend.chatbot.agents.deps import AgentDeps
from backend.config import MODEL_NAME

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

THE INBOX PROMPT:
- Every turn's prompt lists the items in this customer's inbox queue in order.
  Items are either:
    - "- <text>" (a customer message), or
    - "- (system) <summary>" (a system event — most commonly an outbound
      reply from a vendor or logistics partner that just came back).
- Treat system events as first-class inputs. If a system event says the
  vendor confirmed stock / gave a price / quoted a lead time, relay that to
  the customer in your own words — you do NOT need to call any subagent to
  look it up, the info is already in the prompt.
- If the same information appears in both a customer message and a system
  event, say it once. Never repeat the same sentence to the customer twice.

OUTBOUND:
- Use the "outbound" subagent when you need vendor or logistics input (stock check, payment confirmation, delivery coordination).
- ALWAYS set `party_type` on outbound tasks: "vendor" or "logistics".
- The outbound subagent returns IMMEDIATELY with `status: pending`. The actual conversation with the vendor/logistics partner runs in the background and may take minutes. Tell the customer you're on it ("checking with the vendor, one moment") and STOP — write your final reply and end the turn.
- You do NOT poll for vendor replies. When the vendor responds the system will wake you up with a new turn whose prompt contains the vendor's outcome as a "(system)" item. Just relay it then.
- If the customer asks "any update?" while a task is still pending, tell them you're still waiting on the vendor / logistics partner and will share the moment you hear back.

RESPONSE FORMAT:
Plain prose only. No JSON, no markdown structure, no UI hints — the channel layer owns formatting.
"""


agent = Agent(
    model=model,
    deps_type=AgentDeps,
    output_type=str,
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


@agent.instructions
def build_instructions(ctx: RunContext[AgentDeps]) -> str:
    subagent_list = "\n".join(
        f"- {name}: {sub.description}" for name, sub in _get_subagents().items()
    )
    return instructions.replace("{subagents}", subagent_list)
