"""Smoke test for the products dashboard API.

Exercises the spec's required lifecycle:
    create -> patch -> adjust-stock -> audit history ->
    discontinue -> reactivate -> delete-blocked-by-orders -> delete

Runs entirely against an in-memory fake repo. The router's
``backend.db.db_utils`` references are monkey-patched so we don't need a
real Postgres, and ``require_session`` is overridden so we don't need a
JWKS server. Redis is stubbed before import time because
``backend.db.cache_utils`` constructs a client at module load.
"""

from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timezone
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# Pre-import stubs.
# ---------------------------------------------------------------------------
#
# The router transitively imports ``backend.db.cache_utils`` (via
# ``backend.api.events``). Importing that module instantiates a Redis
# client, which fails when no redis server is around. Replace the module
# in ``sys.modules`` with a no-op shim *before* importing the router.

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REDIS_SERVER_HOST", "localhost")
os.environ.setdefault("REDIS_SERVER_PORT", "6379")
os.environ.setdefault("REDIS_SERVER_PASSWORD", "")


class _NopRedis:
    class _Client:
        def publish(self, *_a, **_kw):  # pragma: no cover - trivial shim
            return None

    _client = _Client()

    def get(self, *_a, **_kw):
        return None

    def set(self, *_a, **_kw):
        return None

    def delete(self, *_a, **_kw):
        return None

    def push_to_list(self, *_a, **_kw):
        return None

    def pop_all_from_list(self, *_a, **_kw):
        return []


_cache_stub = types.ModuleType("backend.db.cache_utils")
_cache_stub.redis_conn = _NopRedis()
sys.modules["backend.db.cache_utils"] = _cache_stub


import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api.auth import SessionContext, require_session  # noqa: E402
from backend.api.routers import products as products_router  # noqa: E402
from backend.db.db_utils import (  # noqa: E402
    HasReferences,
    InsufficientStock,
    NotFound,
)


FAKE_USER_ID = uuid4()
FAKE_BIZ_ID = uuid4()


def _fake_session() -> SessionContext:
    return SessionContext(user_id=FAKE_USER_ID, business_id=FAKE_BIZ_ID)


# ---------------------------------------------------------------------------
# In-memory fake repo
# ---------------------------------------------------------------------------


class FakeStore:
    def __init__(self) -> None:
        self.products: dict[str, dict] = {}
        # Movements newest-last; reverse when serving the history endpoint.
        self.movements: list[dict] = []
        self.orders_by_product: dict[str, int] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_movement(
    *,
    product_id: str,
    delta: int,
    reason: str,
    note: str | None,
    actor_id: str,
    actor_type: str = "operator",
) -> dict:
    return {
        "id": uuid4(),
        "product_id": UUID(product_id),
        "delta": delta,
        "reason": reason,
        "note": note,
        "actor_type": actor_type,
        "actor_id": UUID(actor_id) if actor_id else None,
        "created_at": _now(),
    }


def _build_fakes(store: FakeStore):
    """Return a dict of helper-name -> async function patching the repo."""

    async def create_product(business_id, payload, *, actor_id, actor_type="operator"):
        pid = uuid4()
        now = _now()
        qty = int(payload.get("stock_quantity") or 0)
        row = {
            "id": pid,
            "business_id": UUID(business_id),
            "sku": payload["sku"],
            "name": payload["name"],
            "description": payload.get("description"),
            "category": payload.get("category"),
            "price": payload["price"],
            "stock_quantity": qty,
            "reorder_point": int(payload.get("reorder_point") or 0),
            "is_active": True,
            "is_negotiable": bool(payload.get("is_negotiable") or False),
            "floor_price": payload.get("floor_price"),
            "image_url": payload.get("image_url"),
            "last_restocked_at": now if qty > 0 else None,
            "created_at": now,
            "updated_at": now,
        }
        store.products[str(pid)] = row
        if qty > 0:
            store.movements.append(
                _make_movement(
                    product_id=str(pid),
                    delta=qty,
                    reason="restock",
                    note="initial stock",
                    actor_id=actor_id,
                    actor_type=actor_type,
                )
            )
        return dict(row)

    async def patch_product(business_id, product_id, payload, *, actor_id):
        row = store.products.get(str(product_id))
        if row is None:
            raise NotFound()
        old_qty = int(row.get("stock_quantity") or 0)
        # Drop bookkeeping field that lives outside the row schema.
        reason = payload.pop("stock_change_reason", None)
        for k, v in payload.items():
            row[k] = v
        new_qty = int(row.get("stock_quantity") or 0)
        if "stock_quantity" in payload and new_qty != old_qty:
            store.movements.append(
                _make_movement(
                    product_id=str(product_id),
                    delta=new_qty - old_qty,
                    reason=reason or "manual_set",
                    note=None,
                    actor_id=actor_id,
                )
            )
            if new_qty > old_qty:
                row["last_restocked_at"] = _now()
        row["updated_at"] = _now()
        return dict(row)

    async def adjust_stock(
        business_id,
        product_id,
        delta,
        reason,
        note,
        *,
        actor_id,
        actor_type="operator",
    ):
        row = store.products.get(str(product_id))
        if row is None:
            raise NotFound()
        new_qty = int(row.get("stock_quantity") or 0) + int(delta)
        if new_qty < 0:
            raise InsufficientStock()
        row["stock_quantity"] = new_qty
        row["updated_at"] = _now()
        if delta > 0:
            row["last_restocked_at"] = _now()
        movement = _make_movement(
            product_id=str(product_id),
            delta=int(delta),
            reason=reason,
            note=note,
            actor_id=actor_id,
            actor_type=actor_type,
        )
        store.movements.append(movement)
        return dict(row), dict(movement)

    async def delete_product(business_id, product_id):
        if str(product_id) not in store.products:
            raise NotFound()
        n = store.orders_by_product.get(str(product_id), 0)
        if n > 0:
            raise HasReferences(orders=n, transactions=0)
        store.products.pop(str(product_id), None)
        return {"deleted": True}

    async def get_product_for_api(business_id, product_id):
        row = store.products.get(str(product_id))
        if row is None:
            return None
        out = dict(row)
        recent = [
            m for m in store.movements if str(m["product_id"]) == str(product_id)
        ]
        recent.sort(key=lambda m: m["created_at"], reverse=True)
        out["recent_movements"] = [dict(m) for m in recent[:10]]
        return out

    async def list_stock_movements(
        business_id, product_id, *, cursor=None, limit=50, since=None, until=None
    ):
        rows = [
            dict(m) for m in store.movements
            if str(m["product_id"]) == str(product_id)
        ]
        rows.sort(key=lambda m: m["created_at"], reverse=True)
        return rows, None

    async def get_open_order_count(business_id, product_id):
        return store.orders_by_product.get(str(product_id), 0)

    async def list_products_for_api(business_id, **kwargs):
        return [], None

    async def list_categories(business_id):
        return []

    async def get_product_status_totals(business_id):
        return {
            "in_stock": 0,
            "low_stock": 0,
            "out_of_stock": 0,
            "discontinued": 0,
        }

    return {
        "create_product": create_product,
        "patch_product": patch_product,
        "adjust_stock": adjust_stock,
        "delete_product": delete_product,
        "get_product_for_api": get_product_for_api,
        "list_stock_movements": list_stock_movements,
        "get_open_order_count": get_open_order_count,
        "list_products_for_api": list_products_for_api,
        "list_categories": list_categories,
        "get_product_status_totals": get_product_status_totals,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store_and_client(monkeypatch):
    store = FakeStore()
    fakes = _build_fakes(store)

    # The router calls ``db_utils.<helper>``; patch the imported module
    # attribute so the router sees our fake.
    for name, fn in fakes.items():
        monkeypatch.setattr(products_router.db_utils, name, fn)

    app = FastAPI()
    app.include_router(products_router.router, prefix="/api/v1")
    app.dependency_overrides[require_session] = _fake_session
    client = TestClient(app)
    try:
        yield store, client
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# The smoke flow
# ---------------------------------------------------------------------------


def test_product_lifecycle(store_and_client):
    store, client = store_and_client

    # --- Create -----------------------------------------------------------
    r = client.post(
        "/api/v1/products/",
        json={
            "sku": "BW-001",
            "name": "Brazilian Weave",
            "price": "45000.00",
            "stock_quantity": 10,
            "reorder_point": 3,
            "category": "beauty",
            "is_negotiable": False,
        },
    )
    assert r.status_code == 201, r.text
    product = r.json()
    pid = product["id"]
    assert product["stock_quantity"] == 10
    assert product["status"] == "in_stock"
    assert product["price"] == "45000.00"

    # --- Patch (price + reorder_point) -----------------------------------
    r = client.patch(
        f"/api/v1/products/{pid}",
        json={"price": "47000.00", "reorder_point": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["price"] == "47000.00"
    assert body["reorder_point"] == 5

    # --- Adjust-stock (negative delta with reason) ------------------------
    r = client.post(
        f"/api/v1/products/{pid}/adjust-stock",
        json={"delta": -3, "reason": "damage", "note": "Water damage"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["product"]["stock_quantity"] == 7
    assert body["movement"]["delta"] == -3
    assert body["movement"]["reason"] == "damage"

    # --- Audit history ----------------------------------------------------
    r = client.get(f"/api/v1/products/{pid}/stock-movements")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) >= 2  # initial restock + damage adjust
    assert items[0]["reason"] == "damage"  # newest first

    # --- Discontinue (no open orders -> no warnings) ----------------------
    r = client.patch(f"/api/v1/products/{pid}", json={"is_active": False})
    assert r.status_code == 200, r.text
    body = r.json()
    p = body.get("product", body)  # warnings shape vs ProductRead shape
    assert p["status"] == "discontinued"
    assert p["is_active"] is False

    # --- Reactivate -------------------------------------------------------
    r = client.patch(f"/api/v1/products/{pid}", json={"is_active": True})
    assert r.status_code == 200, r.text
    body = r.json()
    p = body.get("product", body)
    assert p["is_active"] is True
    # Stock is 7 with reorder_point 5 -> in_stock.
    assert p["status"] == "in_stock"

    # --- Delete blocked by orders ----------------------------------------
    store.orders_by_product[pid] = 3
    r = client.delete(f"/api/v1/products/{pid}")
    assert r.status_code == 409, r.text
    err = r.json()["detail"]["error"]
    assert err["code"] == "has_references"
    assert err["details"]["orders"] == 3

    # --- Clear refs and delete succeeds ----------------------------------
    store.orders_by_product[pid] = 0
    r = client.delete(f"/api/v1/products/{pid}")
    assert r.status_code == 204, r.text
    assert pid not in store.products
