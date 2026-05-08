import asyncio
from typing import Any, Awaitable, Callable, Literal, NamedTuple
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from backend.chatbot.agents.deps import AgentDeps
from backend.config import MODEL_NAME
from backend.db import contacts

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
    contact_id: UUID | None = Field(
        default=None,
        description=(
            "For agent_name='outbound' only: the UUID of the contact to reach "
            "out to, picked from `list_contacts`. Required when calling outbound; "
            "ignored otherwise."
        ),
    )


class SubagentDef(NamedTuple):
    description: str
    # outbound takes an extra `contact_id` arg; product/payment/etc. don't.
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
    deps: AgentDeps,
    prompt: str,
    contact_id: UUID | None = None,
) -> dict[str, Any]:
    from backend.chatbot.agents.outbound import dispatch
    from backend.db.db_utils import get_business_info

    if contact_id is None:
        return {
            "error": "missing_contact_id",
            "detail": (
                "outbound tasks require a contact_id picked from list_contacts. "
                "Call list_contacts first, then re-issue the outbound task with "
                "the chosen contact's id."
            ),
        }

    contact = await contacts.get_by_id(contact_id)
    if contact is None or contact.business_id != deps.business_id:
        # Hard-fail on cross-tenant or stale id rather than silently dispatching
        # to nobody — the agent will get a structured error and can retry.
        return {
            "error": "unknown_contact_id",
            "detail": (
                f"contact {contact_id} not found in this business's address "
                "book. Call list_contacts to get current ids."
            ),
        }

    business_info = await get_business_info(str(deps.business_id))
    business_name = business_info.get("name", "") if business_info else None
    task_key = await dispatch(
        business_id=deps.business_id,
        customer_id=deps.customer_id,
        contact_id=contact.id,
        initiated_by="customer",
        dispatch_prompt=prompt,
        business_name=business_name,
        parent_depth=deps.current_depth,
    )
    return {
        "status": "pending",
        "task_key": task_key,
        "contact_id": str(contact.id),
        "contact_name": contact.name,
        "contact_role": contact.role,
    }


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
            description="Look up the customer's existing orders and their tracking/delivery status from our DB. READ-ONLY — does not contact any external partner.",
            handler=_handle_logistics,
        ),
        # Temporarily disabled — was being called for greetings and looping.
        # "customer_relation": SubagentDef(
        #     description="Handle complaints, feedback, and escalation decisions.",
        #     handler=_handle_customer_relation,
        # ),
        "outbound": SubagentDef(
            description="Reach out to a vendor or logistics partner externally (async). Use for anything that needs a human at the other end — stock checks, payment confirmation, dispatch scheduling, pickup coordination, address changes. Returns immediately with status=pending; the reply comes back as a (system) item next turn.",
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

NEVER CLAIM AN ACTION YOU DID NOT TAKE THIS TURN.
- Any past or future-tense claim of contact, lookup, follow-up, or
  back-office work requires the matching tool call to have fired in this
  same turn. Promising the action without calling the tool is a hard
  failure.
- The only acceptable "I'll do X" reply with no tool call is when X has
  already been performed earlier in this same turn.

ROUTING:
- Customer asks the business to contact, message, follow up with, or
  remind a vendor / supplier / logistics partner → outbound.
- Customer asks about stock, availability, pricing, or product info →
  product.
- Customer asks about an existing order, tracking, or delivery status →
  logistics.
- Customer reports a payment, receipt, or transfer → payment.
- A follow-up / reminder request always re-dispatches a fresh outbound
  task to the same contact, even if one is already open.

DECIDE — DO YOU NEED A SUBAGENT?

Use a SUBAGENT — this is the default for anything actionable:
{subagents}

Reply DIRECTLY only for: greetings, thanks, goodbye, who-you-are
questions. Anything else that even hints at vendor contact, stock,
orders, payments, or delivery → subagent. When in doubt, dispatch the
subagent rather than asking the customer to clarify — the subagent's
result will tell you whether you have enough info, and if not you can
ask THEN with concrete options.

PROCESS:
1. Read the customer's message and the conversation history.
2. If the message matches a trigger phrase or hints at any actionable
   intent, call `query_subagent` ONCE with every task you need bundled
   in the same call. For outbound tasks, call `list_contacts` first to
   pick a contact_id.
3. Take the subagent result, write your final reply, and STOP. Do NOT call `query_subagent` again about the same topic — pick the best wording from the result, do not "double-check" with another subagent call.
4. Never forward raw subagent output to the customer. Synthesize it in your own voice.

PURCHASE FLOW — hold the state, move it forward.
A purchase moves through implicit phases: discover → identify → verify
availability → quote → pay → confirm receipt → fulfill (pickup/delivery)
→ track. The customer rarely names the phase; you carry the state. The
next phase is yours to start, not theirs to authorize.

Standing rules:
- Adjacent phases close together. When one phase resolves, dispatch the
  next in the same turn. Don't gate with "if you want, I can…" between
  phases the customer has already implicitly committed to. Their intent
  to buy is in force from the moment they ask about a product — they
  shouldn't re-authorize each step.
- Partial vendor reply → re-dispatch same-turn for the gap. If the
  vendor answered part of a question and a known field is still blank
  (delivery free but no timeline; payment received but no pickup info),
  call outbound again immediately. Relay only what's complete.
- Receipt arrives → payment + outbound, same turn. Customer sends a
  receipt → bundle a `payment` task (verify) and an `outbound` task
  (vendor confirmation) in one `query_subagent` call. Don't ask "shall
  I contact the vendor now?"
- Address arrives → outbound, same turn. Customer provides a delivery
  address → dispatch to vendor with the address. Don't reply "noted,
  tell me when to share."
- Re-checks are allowed on cue. No polling on a clock. But: customer
  revisits a stalled topic, expresses urgency, asks "any update?", or
  banking-rail lag (~5-15 min for a transfer to settle) is the relevant
  explanation — those are cues to dispatch a status-check task, not
  reasons to tell the customer to wait.
- Don't re-derive context every turn. Vendor list, business info, and
  product catalog don't change between turns. Reuse them; don't re-call
  `list_contacts` or `get_product_info` for things you already saw this
  conversation.
- State you carry, not phrases you parse. Decide the next dispatch from
  the order's current phase and open items, not from the literal
  wording of the customer's last message.

DON'T ASK FOR DATA WE ALREADY HAVE:
- The customer's identity (customer_id, name, prior orders, contact
  channel) is in the system. Subagents can look up orders via
  customer_id without asking. Do NOT ask the customer for their order
  number, account number, or email "to look it up" — call the right
  subagent instead and let it use customer_id.
- Only ask the customer for things only they know: preferences,
  choices between options, free-form descriptions, transaction
  references they're holding from a payment they made.

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
- Use the "outbound" subagent when you need vendor or logistics input (stock check, payment confirmation, delivery coordination, restock timing, pickup scheduling, follow-up nudges).
- Two-step chain (BOTH calls in the SAME turn — never stop after step 1):
  1. Call `list_contacts(role=<role>)` — use "vendor" / "logistics" /
     whatever role applies, or None to see everyone. Pick the right
     contact by name and notes.
  2. Call `query_subagent(agent_name="outbound", contact_id=<id>,
     prompt=<detailed brief>, summary=<≤80-char headline>)`.
- If `list_contacts` returns no exact match for the customer's domain,
  pick the closest general vendor and dispatch anyway. Do NOT tell the
  customer no vendor exists — try the contacts you have first.
- "Send a reminder / resend / follow up" from the customer means:
  re-dispatch a fresh outbound task to the same contact with a
  reminder-shaped prompt. Don't ask the customer to confirm — they
  already asked.
- The "logistics" subagent and outbound-to-a-logistics-contact are NOT
  interchangeable. "logistics" only reads our DB (where's order #X,
  what's its tracking number). If the customer wants the partner to
  ACT — schedule a pickup, reschedule a delivery, change a drop-off
  address, confirm dispatch — that's outbound, NOT logistics. Don't
  send these to the logistics subagent; it has no way to message the
  partner and will leave the customer waiting.
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


@agent.tool
async def list_contacts(
    ctx: RunContext[AgentDeps], role: str | None = None
) -> list[dict[str, Any]]:
    """List the business's address book. Optionally filter by role.

    Returns the rows the agent needs to pick a contact for an outbound task —
    id (pass to outbound's contact_id), name, role, and free-text notes
    describing what each contact specializes in. Pass role=None to see
    everyone, or a specific role string ("vendor", "logistics", or whatever
    the tenant filed) to narrow the list.
    """
    rows = await contacts.list_by_business(ctx.deps.business_id, role=role)
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "role": c.role,
            "notes": c.notes,
        }
        for c in rows
    ]


@agent.tool
async def find_tasks(
    ctx: RunContext[AgentDeps],
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search this customer's outbound task history by content.

    Returns matched tasks with full markdown logs. Use when the customer
    references past work that isn't fresh in conversation — "any update on
    my Oxford order?", "did you ever hear back about the refund?", or when
    you need to follow up on something the customer mentioned earlier and
    you want the canonical record of what was said + done.

    Scoped to this customer: only their tasks compete for ranking. Returns
    open and closed tasks (closed within the last 180 days). Read-only —
    central agent doesn't write to task logs; outbound agent does.
    """
    from backend.db import outbound_ledger

    rows = await outbound_ledger.find_tasks(
        ctx.deps.business_id,
        query,
        customer_id=ctx.deps.customer_id,
        limit=limit,
    )
    return [
        {
            "task_key": r.task_key,
            "contact_name": r.contact_name,
            "contact_role": r.contact_role,
            "log": r.log,
            "dispatched_at": r.dispatched_at.isoformat(),
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        }
        for r in rows
    ]


async def _dispatch_task(deps: AgentDeps, task: Task) -> dict[str, Any]:
    handler = _get_subagents()[task.agent_name].handler
    if task.agent_name == "outbound":
        return await handler(deps, task.prompt, task.contact_id)
    return await handler(deps, task.prompt)


@agent.instructions
def build_instructions(ctx: RunContext[AgentDeps]) -> str:
    subagent_list = "\n".join(
        f"- {name}: {sub.description}" for name, sub in _get_subagents().items()
    )
    return instructions.replace("{subagents}", subagent_list)
