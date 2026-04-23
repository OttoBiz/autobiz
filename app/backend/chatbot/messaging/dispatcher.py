"""Channel-agnostic dispatch.

Agents emit plain text. The dispatcher decides delivery per audience:

- `dispatch_to_customer`: simple text send.
- `dispatch_to_party`: outbound to a vendor/logistics party. Today: text + a
  `[Ref: <task_key>]` marker, since `task_key` is the routing key for the
  vendor's reply. Once the per-tenant credentials store lands, WhatsApp tenants
  with a published "outbound_ticket" Flow will get the text wrapped in a Flow
  whose `flow_token = task_key`, and other channels keep the text+ref form.
"""

from __future__ import annotations

from backend.chatbot.channels.base import Channel, ChannelIdentity


async def dispatch_to_customer(
    channel: Channel,
    identity: ChannelIdentity,
    text: str,
) -> None:
    await channel.send(identity, text)


async def dispatch_to_party(
    channel: Channel,
    identity: ChannelIdentity,
    text: str,
    *,
    task_key: str,
) -> None:
    await channel.send(identity, f"{text}\n\n[Ref: {task_key}]")
