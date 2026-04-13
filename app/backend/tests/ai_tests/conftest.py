import os

import pytest
import pytest_asyncio

from .api_client import AutobizApiClient


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "ai_e2e: HTTP + multi-LLM tests against deployed Autobiz (requires MODEL_API_KEY)"
    )


@pytest_asyncio.fixture
async def api_client():
    client = AutobizApiClient()
    yield client
    await client.aclose()


def pytest_collection_modifyitems(config, items):
    if os.getenv("MODEL_API_KEY"):
        return
    skip_ai = pytest.mark.skip(reason="Set MODEL_API_KEY to run ai_e2e tests")
    for item in items:
        if "ai_e2e" in item.keywords:
            item.add_marker(skip_ai)
