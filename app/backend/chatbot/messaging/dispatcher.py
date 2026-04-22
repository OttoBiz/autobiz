"""Channel-agnostic dispatch.

Agents emit plain text (`Reply`). The dispatcher decides how that text is
delivered per channel and per audience:

- `dispatch_to_customer`: simple text send. The customer-facing reply is always
  prose; the agent does not pick UI primitives.
- `dispatch_to_party`: outbound to a vendor/logistics party. On WhatsApp this
  wraps the text in a Flow whose `flow_token` is the outbound `task_key`, so
  the vendor's nfm_reply can be mapped back to the originating ticket without
  guesswork (a single party may have multiple open tickets at once).

If a Flow ID isn't configured, party dispatch falls back to text with a
`[Ref: <task_key>]` marker so the mapping path still exists.
"""

from __future__ import annotations

from backend.chatbot.channels.base import Channel, ChannelIdentity
from backend.chatbot.channels.whatsapp_messages import Flow
from backend.chatbot.messaging.reply import Reply
from backend.config import config


# WhatsApp text body cap. Long context still rides in `data["context"]` so the
# Flow screen template can render it in full.
_WHATSAPP_BODY_LIMIT = 1024


async def dispatch_to_customer(
    channel: Channel,
    identity: ChannelIdentity,
    reply: Reply,
) -> None:
    await channel.send(identity, reply.text)


async def dispatch_to_party(
    channel: Channel,
    identity: ChannelIdentity,
    reply: Reply,
    *,
    task_key: str,
) -> None:
    if channel.name == "whatsapp" and config.FLOW_OUTBOUND_TICKET_ID:
        flow = Flow(
            flow_id=config.FLOW_OUTBOUND_TICKET_ID,
            flow_token=task_key,
            flow_cta="Reply",
            body=reply.text[:_WHATSAPP_BODY_LIMIT],
            screen=config.FLOW_OUTBOUND_TICKET_SCREEN,
            data={"task_key": task_key, "context": reply.text},
        )
        await channel.send_flow(identity, flow)
        return

    await channel.send(identity, f"{reply.text}\n\n[Ref: {task_key}]")
