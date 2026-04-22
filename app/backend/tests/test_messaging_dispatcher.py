"""Tests for the channel-agnostic messaging dispatcher.

Each test exercises one branch of the precedence ladder
(flow > template > list > buttons > media > text). The channel is mocked so no
HTTP / WhatsApp Cloud API call happens.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.channels.whatsapp_messages import (
    ButtonMessage,
    Flow,
    ListMessage,
    Template,
)
from backend.chatbot.messaging import dispatcher
from backend.chatbot.messaging.reply import (
    Button,
    FlowRef,
    ListRow,
    ListSection,
    OutboundReply,
    TemplateRef,
)


def _identity() -> ChannelIdentity:
    return ChannelIdentity(
        business_id="biz",
        customer_id="cust",
        channel="whatsapp",
        channel_user_id="+15550001111",
        last_inbound_at=None,
    )


def _channel() -> SimpleNamespace:
    return SimpleNamespace(
        send=AsyncMock(),
        send_buttons=AsyncMock(),
        send_list=AsyncMock(),
        send_flow=AsyncMock(),
        send_template=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_text_only_falls_through_to_send():
    channel = _channel()
    reply = OutboundReply(text="hello vendor")

    await dispatcher.dispatch(channel, _identity(), reply)

    channel.send.assert_awaited_once()
    _identity_arg, text = channel.send.await_args.args
    assert text == "hello vendor"
    channel.send_buttons.assert_not_awaited()


@pytest.mark.asyncio
async def test_buttons_route_to_send_buttons():
    channel = _channel()
    reply = OutboundReply(
        text="Confirm pickup at 3pm?",
        buttons=[Button(id="yes", title="Yes"), Button(id="no", title="No")],
    )

    await dispatcher.dispatch(channel, _identity(), reply)

    channel.send_buttons.assert_awaited_once()
    _identity_arg, msg = channel.send_buttons.await_args.args
    assert isinstance(msg, ButtonMessage)
    assert msg.body == "Confirm pickup at 3pm?"
    assert [b.id for b in msg.buttons] == ["yes", "no"]


@pytest.mark.asyncio
async def test_buttons_truncated_to_three():
    channel = _channel()
    reply = OutboundReply(
        text="pick",
        buttons=[
            Button(id="a", title="A"),
            Button(id="b", title="B"),
            Button(id="c", title="C"),
            Button(id="d", title="D"),
            Button(id="e", title="E"),
        ],
    )

    await dispatcher.dispatch(channel, _identity(), reply)

    _identity_arg, msg = channel.send_buttons.await_args.args
    assert [b.id for b in msg.buttons] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_list_sections_route_to_send_list():
    channel = _channel()
    reply = OutboundReply(
        text="Pick a delivery slot",
        list_button_text="Choose",
        list_sections=[
            ListSection(
                title="Today",
                rows=[
                    ListRow(id="slot-1", title="2-3pm", description="Same-day"),
                    ListRow(id="slot-2", title="4-5pm"),
                ],
            )
        ],
    )

    await dispatcher.dispatch(channel, _identity(), reply)

    channel.send_list.assert_awaited_once()
    _identity_arg, msg = channel.send_list.await_args.args
    assert isinstance(msg, ListMessage)
    assert msg.body == "Pick a delivery slot"
    assert msg.button == "Choose"
    rows = msg.sections[0].rows
    assert [r.id for r in rows] == ["slot-1", "slot-2"]
    assert rows[0].description == "Same-day"


@pytest.mark.asyncio
async def test_flow_routes_to_send_flow():
    channel = _channel()
    reply = OutboundReply(
        flow=FlowRef(
            flow_id="FLOW_1",
            flow_token="tok",
            flow_cta="Provide info",
            body="When can you ship?",
            screen="REQUEST_INFO",
            data={"fields": ["ETA", "Quantity"]},
        )
    )

    await dispatcher.dispatch(channel, _identity(), reply)

    channel.send_flow.assert_awaited_once()
    _identity_arg, flow = channel.send_flow.await_args.args
    assert isinstance(flow, Flow)
    assert flow.flow_id == "FLOW_1"
    assert flow.data == {"fields": ["ETA", "Quantity"]}


@pytest.mark.asyncio
async def test_template_routes_to_send_template():
    channel = _channel()
    reply = OutboundReply(
        template=TemplateRef(
            name="vendor_intro_v1",
            language="es",
            components=[{"type": "body", "parameters": []}],
        )
    )

    await dispatcher.dispatch(channel, _identity(), reply)

    channel.send_template.assert_awaited_once()
    _identity_arg, template, vars_arg = channel.send_template.await_args.args
    assert isinstance(template, Template)
    assert template.name == "vendor_intro_v1"
    assert template.language == "es"
    assert vars_arg == {}


@pytest.mark.asyncio
async def test_media_url_falls_through_to_text_send():
    channel = _channel()
    reply = OutboundReply(text="See attached", media_url="https://example.com/x.png")

    await dispatcher.dispatch(channel, _identity(), reply)

    channel.send.assert_awaited_once()
    _identity_arg, text = channel.send.await_args.args
    assert text == "See attached"


@pytest.mark.asyncio
async def test_precedence_flow_beats_buttons_and_text():
    channel = _channel()
    reply = OutboundReply(
        text="ignored",
        buttons=[Button(id="a", title="A")],
        list_sections=[ListSection(title="x", rows=[ListRow(id="r", title="R")])],
        flow=FlowRef(
            flow_id="F", flow_token="t", flow_cta="Go", body="b", screen="S"
        ),
        template=TemplateRef(name="N"),
    )

    await dispatcher.dispatch(channel, _identity(), reply)

    channel.send_flow.assert_awaited_once()
    channel.send_template.assert_not_awaited()
    channel.send_list.assert_not_awaited()
    channel.send_buttons.assert_not_awaited()
    channel.send.assert_not_awaited()
