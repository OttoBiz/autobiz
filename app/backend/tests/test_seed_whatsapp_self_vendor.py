"""Verify SEED_SELF_VENDOR env wiring on the WhatsApp seeder.

Mocks the inner `seed_whatsapp_business` and asserts the env-driven wrapper
forwards the self-vendor flag and overrides correctly.
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.db import seed_whatsapp


@pytest.mark.asyncio
async def test_self_vendor_flag_disabled_by_default(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id-1")
    monkeypatch.delenv("SEED_SELF_VENDOR", raising=False)

    with patch.object(
        seed_whatsapp, "seed_whatsapp_business", new=AsyncMock(return_value={
            "business_id": "b", "name": "n", "phone_number": "p",
            "whatsapp_phone_number_id": "x", "products": 0,
            "products_csv": "", "contacts": 0,
        })
    ) as inner:
        await seed_whatsapp.seed_whatsapp_business_from_env(pool=object())

    kwargs = inner.call_args.kwargs
    assert kwargs["seed_self_vendor"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes"])
async def test_self_vendor_flag_truthy_variants(monkeypatch, value):
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id-1")
    monkeypatch.setenv("SEED_SELF_VENDOR", value)
    monkeypatch.setenv("SEED_SELF_VENDOR_NAME", "Operator")
    monkeypatch.setenv("SEED_SELF_VENDOR_ROLE", "tailor")
    monkeypatch.setenv("SEED_SELF_VENDOR_NOTES", "single-person tenant")

    with patch.object(
        seed_whatsapp, "seed_whatsapp_business", new=AsyncMock(return_value={
            "business_id": "b", "name": "n", "phone_number": "p",
            "whatsapp_phone_number_id": "x", "products": 0,
            "products_csv": "", "contacts": 1,
        })
    ) as inner:
        await seed_whatsapp.seed_whatsapp_business_from_env(pool=object())

    kwargs = inner.call_args.kwargs
    assert kwargs["seed_self_vendor"] is True
    assert kwargs["self_vendor_name"] == "Operator"
    assert kwargs["self_vendor_role"] == "tailor"
    assert kwargs["self_vendor_notes"] == "single-person tenant"


@pytest.mark.asyncio
async def test_self_vendor_flag_falsy_string(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id-1")
    monkeypatch.setenv("SEED_SELF_VENDOR", "0")

    with patch.object(
        seed_whatsapp, "seed_whatsapp_business", new=AsyncMock(return_value={
            "business_id": "b", "name": "n", "phone_number": "p",
            "whatsapp_phone_number_id": "x", "products": 0,
            "products_csv": "", "contacts": 0,
        })
    ) as inner:
        await seed_whatsapp.seed_whatsapp_business_from_env(pool=object())

    assert inner.call_args.kwargs["seed_self_vendor"] is False
