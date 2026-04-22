import asyncio
from typing import Any, Awaitable, Callable, Literal, NamedTuple

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from backend.chatbot.agents.deps import AgentDeps
from backend.chatbot.messaging.reply import Reply
from backend.config import MODEL_NAME


SUBAGENT_TIMEOUT_SECONDS = 30


class Task(BaseModel):
    agent_name: Literal[
        "product", "payment", "logistics", "customer_relation", "outbound"
    ] = Field(description="Which subagent to call.")
    prompt: str = Field(
        description="Detailed query for the subagent. Include all relevant context (product name, order id, amounts, etc)."
    )


class SubagentDef(NamedTuple):
    description: str
    handler: Callable[[AgentDeps, str], Awaitable[dict[str, Any]]]


async def _run_with_timeout(
    name: str, coro: Awaitable[Any]
) -> dict[str, Any]:
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

    return await _run_with_timeout(
        "logistics", logistics_agent.run(prompt, deps=deps)
    )


async def _handle_customer_relation(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    from backend.chatbot.agents.customer_relation import customer_complaint_agent

    return await _run_with_timeout(
        "customer_relation", customer_complaint_agent.run(prompt, deps=deps)
    )


async def _handle_outbound(deps: AgentDeps, prompt: str) -> dict[str, Any]:
    from backend.chatbot.agents.outbound import dispatch
    from backend.db.db_utils import get_business_info

    business_info = await get_business_info(str(deps.business_id))
    business_name = business_info.get("name", "") if business_info else None
    task_key = await dispatch(
        business_id=deps.business_id,
        customer_id=deps.customer_id,
        party="vendor",
        initiated_by="customer",
        dispatch_prompt=prompt,
        business_name=business_name,
        parent_depth=deps.current_depth,
    )
    return {"status": "pending", "task_key": task_key}


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
        "customer_relation": SubagentDef(
            description="Handle complaints, feedback, and escalation decisions.",
            handler=_handle_customer_relation,
        ),
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

RULES:
- You are the ONLY one who talks to the customer. Subagents return data to you — you craft the final response.
- If a query spans multiple topics, call multiple subagents in one query_subagent call and combine their results into ONE response.
- Never forward raw subagent output to the customer. Synthesize it naturally.
- When an outbound task is pending, mention it if relevant ("Still waiting on vendor confirmation").
- When an outbound task resolves, inform the customer proactively.

SUBAGENTS (use via query_subagent):
{subagents}

OUTBOUND:
- Call the "outbound" subagent when you need vendor/logistics input (payment confirmation, stock checks, delivery coordination).
- It returns immediately. Tell the customer you're on it.
- When its result appears in your state, relay it to the customer.

RESPONSE FORMAT:
Reply with `Reply.text` only — plain prose. Do not return JSON, markdown structure, or
any UI hint; the channel layer owns formatting.
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
        *(_get_subagents()[task.agent_name].handler(ctx.deps, task.prompt) for task in tasks),
        return_exceptions=True,
    )
    return [r if isinstance(r, dict) else {"error": str(r)} for r in results]


@agent.instructions
def build_instructions(ctx: RunContext[AgentDeps]) -> str:
    subagent_list = "\n".join(
        f"- {name}: {sub.description}" for name, sub in _get_subagents().items()
    )
    return instructions.replace("{subagents}", subagent_list)
