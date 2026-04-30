"""Tests for `whatsapp_messages` builders + `WhatsappChannel` interactive sends.

Fixtures mirror the JSON shapes documented at:
- https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
- https://developers.facebook.com/docs/whatsapp/flows/reference/flowsapi
- https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
"""
import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from backend.chatbot.channels.base import ChannelIdentity
from backend.chatbot.channels.whatsapp_messages import (
    ButtonMessage,
    Flow,
    ListMessage,
    ListRow,
    ListSection,
    ReplyButton,
    Template,
    confirm_request,
    pick_option,
)


def _reload_whatsapp_channel():
    from backend.chatbot.channels import whatsapp as whatsapp_module

    return importlib.reload(whatsapp_module)


@pytest.fixture
def identity() -> ChannelIdentity:
    return ChannelIdentity(
        business_id="00000000-0000-0000-0000-000000000001",
        customer_id="00000000-0000-0000-0000-000000000002",
        channel="whatsapp",
        channel_user_id="2348012345678",
        channel_business_id="PHONE_NUMBER_ID_123",
        last_inbound_at=None,
    )


# ---------------------------------------------------------------------------
# Builder payload shape tests
# ---------------------------------------------------------------------------


def test_button_message_payload_matches_docs_shape() -> None:
    msg = ButtonMessage(
        body="Confirm your order?",
        buttons=[
            ReplyButton(id="yes", title="Yes"),
            ReplyButton(id="no", title="No"),
        ],
        header="Order Confirmation",
        footer="Tap a button below",
    )

    payload = msg.to_whatsapp_payload()

    assert payload["messaging_product"] == "whatsapp"
    assert payload["recipient_type"] == "individual"
    assert payload["type"] == "interactive"
    assert payload["interactive"] == {
        "type": "button",
        "header": {"type": "text", "text": "Order Confirmation"},
        "body": {"text": "Confirm your order?"},
        "footer": {"text": "Tap a button below"},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "yes", "title": "Yes"}},
                {"type": "reply", "reply": {"id": "no", "title": "No"}},
            ]
        },
    }


def test_button_message_payload_omits_optional_fields() -> None:
    msg = ButtonMessage(
        body="Pick one", buttons=[ReplyButton(id="a", title="A")]
    )
    payload = msg.to_whatsapp_payload()
    assert "header" not in payload["interactive"]
    assert "footer" not in payload["interactive"]


def test_list_message_payload_matches_docs_shape() -> None:
    msg = ListMessage(
        body="Pick a product",
        button="Browse",
        sections=[
            ListSection(
                title="Drinks",
                rows=[
                    ListRow(id="coke", title="Coke", description="Classic"),
                    ListRow(id="water", title="Water"),
                ],
            )
        ],
    )

    payload = msg.to_whatsapp_payload()

    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "list"
    assert payload["interactive"]["action"] == {
        "button": "Browse",
        "sections": [
            {
                "title": "Drinks",
                "rows": [
                    {"id": "coke", "title": "Coke", "description": "Classic"},
                    {"id": "water", "title": "Water"},
                ],
            }
        ],
    }


def test_flow_payload_matches_docs_shape() -> None:
    flow = Flow(
        flow_id="123456",
        flow_token="AQAAAAACS5FpgQ_cAAAAAD0QI3s",
        flow_cta="Book!",
        body="Tap below to book",
        screen="SCREEN_NAME",
        data={"product_name": "name", "product_price": 100},
        mode="published",
    )

    payload = flow.to_whatsapp_payload()
    interactive = payload["interactive"]

    assert interactive["type"] == "flow"
    parameters = interactive["action"]["parameters"]
    assert interactive["action"]["name"] == "flow"
    assert parameters["flow_message_version"] == "3"
    assert parameters["flow_token"] == "AQAAAAACS5FpgQ_cAAAAAD0QI3s"
    assert parameters["flow_id"] == "123456"
    assert parameters["flow_cta"] == "Book!"
    assert parameters["flow_action"] == "navigate"
    assert parameters["mode"] == "published"
    assert parameters["flow_action_payload"]["screen"] == "SCREEN_NAME"
    # Cloud API requires `data` as a JSON-encoded string, not an object.
    data_str = parameters["flow_action_payload"]["data"]
    assert isinstance(data_str, str)
    assert json.loads(data_str) == {"product_name": "name", "product_price": 100}


def test_flow_payload_omits_data_when_not_provided() -> None:
    flow = Flow(
        flow_id="1",
        flow_token="t",
        flow_cta="Go",
        body="b",
        screen="S",
    )
    payload = flow.to_whatsapp_payload()
    payload_action = payload["interactive"]["action"]["parameters"][
        "flow_action_payload"
    ]
    assert payload_action == {"screen": "S"}


def test_template_payload_matches_docs_shape() -> None:
    template = Template(
        name="hello_world",
        language="en_US",
        components=[
            {
                "type": "body",
                "parameters": [{"type": "text", "text": "Alice"}],
            }
        ],
    )
    payload = template.to_whatsapp_payload()
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "hello_world"
    assert payload["template"]["language"] == {"code": "en_US"}
    assert payload["template"]["components"][0]["parameters"][0]["text"] == "Alice"


# ---------------------------------------------------------------------------
# Channel send_* tests (mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_buttons_posts_to_graph(identity: ChannelIdentity) -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    msg = confirm_request("Proceed?")

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"messages": [{"id": "wamid.X"}]}
    with patch.object(module.requests, "post", return_value=mock_response) as mock_post:
        result = await channel.send_buttons(identity, msg)

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://graph.facebook.com/v18.0/PHONE_NUMBER_ID_123/messages"
    body = kwargs["json"]
    assert body["to"] == "2348012345678"
    assert body["type"] == "interactive"
    assert body["interactive"]["type"] == "button"
    assert result == {"messages": [{"id": "wamid.X"}]}


@pytest.mark.asyncio
async def test_send_list_posts_to_graph(identity: ChannelIdentity) -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    msg = pick_option("Pick", [("a", "Apples"), ("b", "Bananas")])

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"messages": [{"id": "wamid.Y"}]}
    with patch.object(module.requests, "post", return_value=mock_response) as mock_post:
        await channel.send_list(identity, msg)

    args, kwargs = mock_post.call_args
    assert args[0] == "https://graph.facebook.com/v18.0/PHONE_NUMBER_ID_123/messages"
    body = kwargs["json"]
    assert body["to"] == "2348012345678"
    assert body["interactive"]["type"] == "list"
    assert body["interactive"]["action"]["sections"][0]["rows"][0]["id"] == "a"


@pytest.mark.asyncio
async def test_send_flow_posts_to_graph(identity: ChannelIdentity) -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    flow = Flow(
        flow_id="999",
        flow_token="tok",
        flow_cta="Open",
        body="Form",
        screen="START",
    )

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"messages": [{"id": "wamid.Z"}]}
    with patch.object(module.requests, "post", return_value=mock_response) as mock_post:
        await channel.send_flow(identity, flow)

    args, kwargs = mock_post.call_args
    assert args[0] == "https://graph.facebook.com/v18.0/PHONE_NUMBER_ID_123/messages"
    body = kwargs["json"]
    assert body["to"] == "2348012345678"
    assert body["interactive"]["type"] == "flow"
    assert body["interactive"]["action"]["parameters"]["flow_id"] == "999"


@pytest.mark.asyncio
async def test_send_template_accepts_template_model(
    identity: ChannelIdentity,
) -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    template = Template(name="order_update", language="en_US", components=[])

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"messages": [{"id": "wamid.T"}]}
    with patch.object(module.requests, "post", return_value=mock_response) as mock_post:
        await channel.send_template(identity, template)

    args, kwargs = mock_post.call_args
    body = kwargs["json"]
    assert body["type"] == "template"
    assert body["template"]["name"] == "order_update"
    assert body["to"] == "2348012345678"


# ---------------------------------------------------------------------------
# parse_inbound — interactive types
# ---------------------------------------------------------------------------


def _wrap_message(message: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "PHONE_NUMBER_ID_123",
                            },
                            "messages": [message],
                        }
                    }
                ]
            }
        ]
    }


def test_parse_inbound_button_reply() -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    raw = _wrap_message(
        {
            "from": "2348012345678",
            "id": "wamid.MSG",
            "timestamp": "1700000000",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "yes", "title": "Yes"},
            },
        }
    )

    msg = channel.parse_inbound(raw)

    assert msg.text == "Yes"
    assert msg.interactive == {
        "type": "button_reply",
        "id": "yes",
        "title": "Yes",
    }
    assert msg.raw == raw


def test_parse_inbound_list_reply() -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    raw = _wrap_message(
        {
            "from": "2348012345678",
            "id": "wamid.MSG",
            "timestamp": "1700000000",
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {
                    "id": "row_1",
                    "title": "Apples",
                    "description": "Fresh",
                },
            },
        }
    )

    msg = channel.parse_inbound(raw)

    assert msg.text == "Apples"
    assert msg.interactive == {
        "type": "list_reply",
        "id": "row_1",
        "title": "Apples",
        "description": "Fresh",
    }


def test_parse_inbound_nfm_reply_parses_response_json() -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    raw = _wrap_message(
        {
            "from": "2348012345678",
            "id": "wamid.MSG",
            "timestamp": "1700000000",
            "type": "interactive",
            "interactive": {
                "type": "nfm_reply",
                "nfm_reply": {
                    "response_json": '{"screen_0_email_0":"a@b.com","flow_token":"tok"}',
                    "body": "Sent",
                    "name": "flow",
                },
            },
        }
    )

    msg = channel.parse_inbound(raw)

    assert msg.text == "flow_response"
    assert msg.interactive is not None
    assert msg.interactive["type"] == "nfm_reply"
    assert msg.interactive["body"] == "Sent"
    assert msg.interactive["name"] == "flow"
    assert msg.interactive["payload"] == {
        "screen_0_email_0": "a@b.com",
        "flow_token": "tok",
    }


# ---------------------------------------------------------------------------
# Component helpers round-trip through to_whatsapp_payload()
# ---------------------------------------------------------------------------


def test_confirm_request_round_trips() -> None:
    msg = confirm_request("Are you sure?")
    assert isinstance(msg, ButtonMessage)
    payload = msg.to_whatsapp_payload()
    buttons = payload["interactive"]["action"]["buttons"]
    assert [b["reply"]["id"] for b in buttons] == ["yes", "no"]
    assert payload["interactive"]["body"]["text"] == "Are you sure?"


def test_confirm_request_custom_ids_round_trip() -> None:
    msg = confirm_request("Confirm payment?", yes_id="confirm", no_id="cancel")
    payload = msg.to_whatsapp_payload()
    ids = [
        b["reply"]["id"] for b in payload["interactive"]["action"]["buttons"]
    ]
    assert ids == ["confirm", "cancel"]


def test_pick_option_round_trips() -> None:
    msg = pick_option("Pick a color", [("r", "Red"), ("b", "Blue")])
    assert isinstance(msg, ListMessage)
    payload = msg.to_whatsapp_payload()
    rows = payload["interactive"]["action"]["sections"][0]["rows"]
    assert rows == [{"id": "r", "title": "Red"}, {"id": "b", "title": "Blue"}]


