from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import KnownModelName


class OutboundDeps(BaseModel):
    task_key: str = Field(
        description="Unique key for this outbound task in shared state."
    )
    customer_id: str = Field(
        description="ID of the customer who triggered this outbound request."
    )
    business_name: str = Field(default="")
    resolution: dict[str, Any] = Field(
        default_factory=dict,
        description="Written by mark_completed tool. Read by handler after agent finishes.",
    )


model: KnownModelName = "openai:gpt-5.2-chat-latest"

instructions = """
You are an outbound agent for {business_name}. You handle exactly ONE issue per conversation.
This request was triggered by customer {customer_id}.

RULES:
- You are talking to a vendor/logistics partner, NOT a customer.
- Be professional and direct. State what you need clearly.
- When you get the information or confirmation you need, call mark_completed immediately.
- Do NOT end the conversation without calling mark_completed.
- If the vendor declines or cannot help, still call mark_completed with the negative outcome.
"""

outbound_agent = Agent(
    instructions=instructions,
    model=model,
    deps_type=OutboundDeps,
)


@outbound_agent.instructions
def build_instructions(ctx: RunContext[OutboundDeps]) -> str:
    return instructions.format(
        business_name=ctx.deps.business_name or "the business",
        customer_id=ctx.deps.customer_id,
    )


@outbound_agent.tool
async def mark_completed(
    ctx: RunContext[OutboundDeps],
    result: str = Field(description="Outcome of the vendor interaction."),
    vendor_note: str = Field(
        description="Internal note with actionable instructions for the system — e.g. update inventory, adjust pricing, modify order. Not shown to the customer."
    ),
) -> str:
    """Mark this outbound task as resolved. Call this when the vendor has responded with a definitive answer."""
    ctx.deps.resolution = {
        "status": "resolved",
        "result": result,
        "vendor_note": vendor_note,
    }
    return f"Outbound task {ctx.deps.task_key} marked as resolved."
