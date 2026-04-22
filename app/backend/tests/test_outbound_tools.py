"""Tests for the outbound agent's send-side tools.

Each tool resolves a channel via `_resolve_party_channel` and dispatches to the
matching `Channel.send_*` method. We mock the channel + registry so no HTTP or
WhatsApp Cloud API calls happen.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from backend.chatbot.agents import outbound
from backend.chatbot.channels import registry
from backend.chatbot.channels.whatsapp_messages import (
    ButtonMessage,
    ListMessage,
    Template,
)


def _make_ctx(party: str = "+15551234567") -> Any:
    deps = outbound.OutboundDeps(
        task_key="tk-tools",
        business_id=uuid4(),
        customer_id=uuid4(),
        party=party,
        initiated_by="customer",
        dispatch_prompt="hi",
    )
    return SimpleNamespace(deps=deps)


@pytest.fixture
def mock_channel(monkeypatch):
    """Replace the WhatsApp channel in the registry with an AsyncMock-backed stub."""
    fake = SimpleNamespace(
        send=AsyncMock(return_value=None),
        send_buttons=AsyncMock(return_value={"messages": [{"id": "wamid.xxx"}]}),
        send_list=AsyncMock(return_value={"messages": [{"id": "wamid.xxx"}]}),
        send_flow=AsyncMock(return_value={"messages": [{"id": "wamid.xxx"}]}),
        send_template=AsyncMock(return_value={"messages": [{"id": "wamid.xxx"}]}),
    )
    monkeypatch.setattr(registry, "get", lambda name: fake)
    return fake


@pytest.mark.asyncio
async def test_send_text_to_party_calls_channel_send(mock_channel):
    ctx = _make_ctx(party="+15550001111")
    result = await outbound.send_text_to_party(ctx, "Do you have stock of SKU-9?")

    assert result == {"sent": True}
    mock_channel.send.assert_awaited_once()
    identity, text = mock_channel.send.await_args.args
    assert identity.channel == "whatsapp"
    assert identity.channel_user_id == "+15550001111"
    assert text == "Do you have stock of SKU-9?"


@pytest.mark.asyncio
async def test_send_buttons_to_party_builds_button_message(mock_channel):
    ctx = _make_ctx()
    result = await outbound.send_buttons_to_party(
        ctx,
        body="Confirm pickup at 3pm?",
        buttons=[
            {"id": "yes", "title": "Yes"},
            {"id": "no", "title": "No"},
        ],
    )

    assert result == {"sent": True, "buttons": ["yes", "no"]}
    mock_channel.send_buttons.assert_awaited_once()
    _identity, msg = mock_channel.send_buttons.await_args.args
    assert isinstance(msg, ButtonMessage)
    assert msg.body == "Confirm pickup at 3pm?"
    assert [b.id for b in msg.buttons] == ["yes", "no"]
    assert [b.title for b in msg.buttons] == ["Yes", "No"]


@pytest.mark.asyncio
async def test_send_list_to_party_builds_list_message(mock_channel):
    ctx = _make_ctx()
    result = await outbound.send_list_to_party(
        ctx,
        body="Pick a delivery slot",
        button_text="Choose",
        sections=[
            {
                "title": "Today",
                "rows": [
                    {"id": "slot-1", "title": "2-3pm", "description": "Same-day"},
                    {"id": "slot-2", "title": "4-5pm", "description": None},
                ],
            },
        ],
    )

    assert result == {"sent": True}
    mock_channel.send_list.assert_awaited_once()
    _identity, msg = mock_channel.send_list.await_args.args
    assert isinstance(msg, ListMessage)
    assert msg.body == "Pick a delivery slot"
    assert msg.button == "Choose"
    assert len(msg.sections) == 1
    rows = msg.sections[0].rows
    assert [r.id for r in rows] == ["slot-1", "slot-2"]
    assert rows[0].description == "Same-day"
    assert rows[1].description is None


@pytest.mark.asyncio
async def test_request_structured_info_uses_request_info_flow_id(
    mock_channel, monkeypatch
):
    from backend import config as config_module

    monkeypatch.setattr(config_module.config, "FLOW_REQUEST_INFO_ID", "FLOW_99")

    ctx = _make_ctx()
    result = await outbound.request_structured_info(
        ctx,
        prompt="When can you ship?",
        fields=[
            {"name": "eta", "label": "Estimated ship date", "type": "date"},
            {"name": "qty", "label": "Quantity available", "type": "number"},
        ],
    )

    assert result == {"sent": True, "flow_id": "FLOW_99"}
    mock_channel.send_flow.assert_awaited_once()
    _identity, flow = mock_channel.send_flow.await_args.args
    assert flow.flow_id == "FLOW_99"
    # Labels (not names) drive the form display + token.
    assert flow.data == {
        "fields": ["Estimated ship date", "Quantity available"]
    }


@pytest.mark.asyncio
async def test_send_template_to_party_builds_template_with_defaults(mock_channel):
    ctx = _make_ctx()
    result = await outbound.send_template_to_party(
        ctx,
        template_name="vendor_intro_v1",
    )

    assert result == {"sent": True}
    mock_channel.send_template.assert_awaited_once()
    _identity, template, vars_arg = mock_channel.send_template.await_args.args
    assert isinstance(template, Template)
    assert template.name == "vendor_intro_v1"
    assert template.language == "en"
    assert template.components == []
    assert vars_arg == {}


@pytest.mark.asyncio
async def test_send_template_to_party_passes_vars_through(mock_channel):
    ctx = _make_ctx()
    vars_payload = {
        "language": "es",
        "components": [
            {"type": "body", "parameters": [{"type": "text", "text": "Acme"}]}
        ],
    }
    await outbound.send_template_to_party(
        ctx, template_name="vendor_followup", vars=vars_payload
    )

    _identity, template, vars_arg = mock_channel.send_template.await_args.args
    assert template.language == "es"
    assert template.components == vars_payload["components"]
    assert vars_arg == vars_payload


@pytest.mark.asyncio
async def test_resolve_party_channel_targets_party_phone(mock_channel):
    deps = outbound.OutboundDeps(
        task_key="tk-x",
        business_id=uuid4(),
        customer_id=uuid4(),
        party="+447700900111",
        initiated_by="system",
        dispatch_prompt="ignored",
    )
    channel, identity = await outbound._resolve_party_channel(deps)

    assert channel is mock_channel
    assert identity.channel == "whatsapp"
    assert identity.channel_user_id == "+447700900111"
    assert identity.business_id == str(deps.business_id)
    assert identity.customer_id == str(deps.customer_id)
