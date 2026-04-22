"""Channel handler — pushes or holds customer-facing resolutions.

Decides, per channel policy, whether to send a resolution now (free-form or
template) or wait for the customer's next message.
"""

from datetime import datetime, timedelta, timezone

from backend.chatbot.channels.base import Channel, ChannelIdentity, WindowPolicy
from backend.db import channel_identities
from backend.db.outbound_ledger import OutboundTaskRow

_DEFAULT_TEMPLATE = "status_update"


async def handle_resolution(task: OutboundTaskRow, channel: Channel) -> None:
    identity = await channel_identities.get_identity(
        task.business_id, task.customer_id, channel.name
    )
    if identity is None:
        return

    policy = channel.window_policy()
    text = task.customer_context or ""

    if not policy.has_window:
        await channel.send(identity, text)
        return

    if _within_window(identity, policy):
        # central_agent reads the resolution from the ledger on the
        # customer's next inbound message — no push needed.
        return

    if policy.out_of_window_behavior == "template":
        await channel.send_template(
            identity, template=_DEFAULT_TEMPLATE, vars={"summary": text}
        )


def _within_window(identity: ChannelIdentity, policy: WindowPolicy) -> bool:
    if identity.last_inbound_at is None:
        return False
    window = timedelta(hours=policy.window_hours or 0)
    return datetime.now(timezone.utc) - identity.last_inbound_at < window
