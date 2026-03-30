import asyncio
from typing import Any, Awaitable, Callable, List, Literal, NamedTuple, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import KnownModelName

from backend.chatbot.agents.outbound import OutboundDeps


class AgentDeps(BaseModel):
    user_id: str
    business_id: str
    chat_history: Optional[List[Any]] = None
    state: dict[str, Any] = Field(default_factory=dict)
    outbound: List[OutboundDeps] = Field(default_factory=list)


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


def _register_handlers() -> dict[str, SubagentDef]:
    from backend.chatbot.agents.handlers import (
        handle_customer_relation,
        handle_logistics,
        handle_outbound,
        handle_payment,
        handle_product,
    )

    return {
        "product": SubagentDef(
            description="Look up product info, pricing, availability, and payment links for this business.",
            handler=handle_product,
        ),
        "payment": SubagentDef(
            description="Verify a payment via receipt or payment link. Match amounts against known products.",
            handler=handle_payment,
        ),
        "logistics": SubagentDef(
            description="Track orders, get delivery status, collect delivery addresses.",
            handler=handle_logistics,
        ),
        "customer_relation": SubagentDef(
            description="Handle complaints, feedback, and escalation decisions.",
            handler=handle_customer_relation,
        ),
        "outbound": SubagentDef(
            description="Contact vendor or logistics. Returns immediately — runs in background. Use when you need human confirmation or info the system doesn't have.",
            handler=handle_outbound,
        ),
    }


SUBAGENTS: dict[str, SubagentDef] = _register_handlers()


model: KnownModelName = "openai:gpt-5.2-chat-latest"

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
"""


agent = Agent(
    model=model,
    deps_type=AgentDeps,
)


@agent.tool
async def query_subagent(
    ctx: RunContext[AgentDeps], tasks: list[Task]
) -> list[dict[str, Any]]:
    """Call one or more subagents in parallel. Each task specifies the subagent name and a detailed prompt."""
    results = await asyncio.gather(
        *(SUBAGENTS[task.agent_name].handler(ctx.deps, task.prompt) for task in tasks),
        return_exceptions=True,
    )
    return [r if isinstance(r, dict) else {"error": str(r)} for r in results]


@agent.instructions
def build_instructions(ctx: RunContext[AgentDeps]) -> str:
    subagent_list = "\n".join(
        f"- {name}: {sub.description}" for name, sub in SUBAGENTS.items()
    )
    return instructions.replace("{subagents}", subagent_list)
