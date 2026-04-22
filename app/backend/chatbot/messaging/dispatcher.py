"""Channel-agnostic dispatch.

Agents emit plain text (`Reply`). The dispatcher decides delivery per audience:

- `dispatch_to_customer`: simple text send.
- `dispatch_to_party`: outbound to a vendor/logistics party. Today: text + a
  `[Ref: <task_key>]` marker, since `task_key` is the routing key for the
  vendor's reply. Once the per-tenant credentials store lands, WhatsApp tenants
  with a published "outbound_ticket" Flow will get the text wrapped in a Flow
  whose `flow_token = task_key`, and other channels keep the text+ref form.
"""

from __future__ import annotations

from backend.chatbot.channels.base import Channel, ChannelIdentity
from backend.chatbot.messaging.reply import Reply


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
    await channel.send(identity, f"{reply.text}\n\n[Ref: {task_key}]")
