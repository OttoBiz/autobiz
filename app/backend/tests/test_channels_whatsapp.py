import importlib
from unittest.mock import MagicMock, patch

import pytest

from backend.chatbot.channels import registry
from backend.chatbot.channels.base import (
    ChannelIdentity,
    InboundMessage,
    WindowPolicy,
)


@pytest.fixture
def webhook_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "ENTRY_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "PHONE_NUMBER_ID_123",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test User"},
                                    "wa_id": "2348012345678",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "2348012345678",
                                    "id": "wamid.MSG_ID",
                                    "timestamp": "1700000000",
                                    "text": {"body": "hello there"},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


@pytest.fixture
def image_webhook_payload() -> dict:
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
                            "messages": [
                                {
                                    "from": "2348012345678",
                                    "id": "wamid.MSG_ID",
                                    "timestamp": "1700000000",
                                    "type": "image",
                                    "image": {
                                        "id": "IMG_ID",
                                        "mime_type": "image/jpeg",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


@pytest.fixture
def status_webhook_payload() -> dict:
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
                            "statuses": [{"id": "wamid.STATUS"}],
                        }
                    },
                    {
                        "value": {
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "PHONE_NUMBER_ID_123",
                            },
                            "messages": [
                                {
                                    "from": "2348012345678",
                                    "id": "wamid.MSG_ID",
                                    "timestamp": "1700000000",
                                    "text": {"body": "real message"},
                                    "type": "text",
                                }
                            ],
                        }
                    },
                ]
            }
        ]
    }


def _reload_whatsapp_channel():
    from backend.chatbot.channels import whatsapp as whatsapp_module

    return importlib.reload(whatsapp_module)


def test_parse_inbound_text(webhook_payload: dict) -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    msg = channel.parse_inbound(webhook_payload)

    assert isinstance(msg, InboundMessage)
    assert msg.text == "hello there"
    assert msg.media == []
    assert msg.raw == webhook_payload
    assert msg.identity.channel == "whatsapp"
    assert msg.identity.business_id == "PHONE_NUMBER_ID_123"
    assert msg.identity.customer_id == "2348012345678"
    assert msg.identity.channel_user_id == "2348012345678"


def test_parse_inbound_image_attachment(image_webhook_payload: dict) -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    msg = channel.parse_inbound(image_webhook_payload)

    assert msg.text is None
    assert len(msg.media) == 1
    attachment = msg.media[0]
    assert attachment.kind == "image"
    assert attachment.mime_type == "image/jpeg"


def test_parse_inbound_skips_status_events(status_webhook_payload: dict) -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    msg = channel.parse_inbound(status_webhook_payload)

    assert msg.text == "real message"


@pytest.mark.asyncio
async def test_send_delegates_to_whatsapp_bot() -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    identity = ChannelIdentity(
        business_id="PHONE_NUMBER_ID_123",
        customer_id="2348012345678",
        channel="whatsapp",
        channel_user_id="2348012345678",
        last_inbound_at=None,
    )

    with patch.object(module._whatsapp_bot, "send_message") as mock_send:
        mock_send.return_value = True
        await channel.send(identity, "hi there")

    mock_send.assert_called_once_with(
        "PHONE_NUMBER_ID_123", "2348012345678", "hi there"
    )


@pytest.mark.asyncio
async def test_send_template_posts_template_payload() -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    identity = ChannelIdentity(
        business_id="PHONE_NUMBER_ID_123",
        customer_id="2348012345678",
        channel="whatsapp",
        channel_user_id="2348012345678",
        last_inbound_at=None,
    )

    mock_response = MagicMock(status_code=200)
    with patch.object(module.requests, "post", return_value=mock_response) as mock_post:
        await channel.send_template(
            identity,
            "hello_world",
            {"language": "en_US", "components": [{"type": "body"}]},
        )

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == (
        "https://graph.facebook.com/v18.0/PHONE_NUMBER_ID_123/messages"
    )
    payload = kwargs["json"]
    assert payload["type"] == "template"
    assert payload["to"] == "2348012345678"
    assert payload["template"]["name"] == "hello_world"
    assert payload["template"]["language"]["code"] == "en_US"
    assert payload["template"]["components"] == [{"type": "body"}]


def test_window_policy_values() -> None:
    module = _reload_whatsapp_channel()
    channel = module.WhatsappChannel()
    policy = channel.window_policy()

    assert isinstance(policy, WindowPolicy)
    assert policy.has_window is True
    assert policy.window_hours == 24
    assert policy.out_of_window_behavior == "template"


def test_module_import_registers_channel() -> None:
    module = _reload_whatsapp_channel()
    channel = registry.get("whatsapp")
    assert isinstance(channel, module.WhatsappChannel)
