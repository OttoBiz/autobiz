"""Channel-agnostic dispatcher.

Resolves an `OutboundReply` (channel-agnostic) into one channel-bound primitive
and dispatches it via the supplied `Channel`. Precedence is fixed and explicit:

    flow > template > list_sections > buttons > media_url > text

Only one branch fires per call. Agents pick the richest field they need; the
dispatcher does not try to combine them.
"""

from __future__ import annotations

from backend.chatbot.channels.base import Channel, ChannelIdentity
from backend.chatbot.channels.whatsapp_messages import (
    ButtonMessage,
    Flow,
    ListMessage,
    ListRow as WhatsAppListRow,
    ListSection as WhatsAppListSection,
    ReplyButton,
    Template,
)
from backend.chatbot.messaging.reply import OutboundReply


async def dispatch(
    channel: Channel,
    identity: ChannelIdentity,
    reply: OutboundReply,
) -> None:
    if reply.flow is not None:
        flow = Flow(
            flow_id=reply.flow.flow_id,
            flow_token=reply.flow.flow_token,
            flow_cta=reply.flow.flow_cta,
            body=reply.flow.body,
            screen=reply.flow.screen,
            data=reply.flow.data,
        )
        await channel.send_flow(identity, flow)
        return

    if reply.template is not None:
        template = Template(
            name=reply.template.name,
            language=reply.template.language,
            components=reply.template.components,
        )
        await channel.send_template(identity, template, {})
        return

    if reply.list_sections is not None:
        msg = ListMessage(
            body=reply.text or "",
            button=reply.list_button_text or "Choose",
            sections=[
                WhatsAppListSection(
                    title=s.title,
                    rows=[
                        WhatsAppListRow(
                            id=r.id, title=r.title, description=r.description
                        )
                        for r in s.rows
                    ],
                )
                for s in reply.list_sections
            ],
        )
        await channel.send_list(identity, msg)
        return

    if reply.buttons is not None:
        # WhatsApp caps interactive buttons at 3 — enforced here, not at agent boundary.
        msg = ButtonMessage(
            body=reply.text or "",
            buttons=[ReplyButton(id=b.id, title=b.title) for b in reply.buttons[:3]],
        )
        await channel.send_buttons(identity, msg)
        return

    if reply.media_url is not None:
        # TODO: no `Channel.send_media` exists yet; for now fall through to a
        # text send carrying the URL as caption-style content.
        await channel.send(identity, reply.text or reply.media_url)
        return

    await channel.send(identity, reply.text or "")
