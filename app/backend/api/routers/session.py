"""Simulation / dev helpers: clear Redis state for selected personas."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.db.cache_utils import delete_inbox_key, delete_party_state, delete_user_state, get_user_state
from backend.db.db_utils import list_orders_for_customer_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/session", tags=["session"])


def _agent_context_from_state(state: Optional[dict]) -> Dict[str, Any]:
    """Lean snapshot of Redis user_state for agent-debug UI (no chat_history)."""
    if not state:
        return {"products_discussed": [], "processes": []}

    discussed: List[Dict[str, Any]] = []
    seen: set = set()
    raw_products = state.get("products") or {}
    if isinstance(raw_products, dict):
        for cache_key, entry in raw_products.items():
            if not isinstance(entry, dict):
                continue
            for p in entry.get("retrieved_results") or []:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("id") or "").strip()
                name = (p.get("name") or p.get("product_name") or "").strip()
                dedupe = pid or name.lower() or str(cache_key)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                try:
                    price = float(p.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0.0
                try:
                    stock = int(p.get("stock_quantity") or 0)
                except (TypeError, ValueError):
                    stock = 0
                discussed.append(
                    {
                        "id": pid or None,
                        "name": name or None,
                        "price": price,
                        "stock_quantity": stock,
                        "currency": p.get("currency"),
                        "cache_key": str(cache_key),
                    }
                )

    # Conversational agent also maintains `products_discussed` (list) on the same Redis key.
    raw_pd = state.get("products_discussed")
    if isinstance(raw_pd, list):
        for i, p in enumerate(raw_pd):
            if isinstance(p, dict):
                pid = str(p.get("id") or "").strip()
                name = (p.get("name") or p.get("product_name") or "").strip()
                dedupe = pid or name.lower() or f"pd:{i}"
                if dedupe in seen or not name:
                    continue
                seen.add(dedupe)
                try:
                    price = float(p.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0.0
                try:
                    stock = int(p.get("stock_quantity") or 0)
                except (TypeError, ValueError):
                    stock = 0
                discussed.append(
                    {
                        "id": pid or None,
                        "name": name or None,
                        "price": price,
                        "stock_quantity": stock,
                        "currency": p.get("currency"),
                        "cache_key": f"products_discussed:{i}",
                    }
                )
            elif isinstance(p, str) and p.strip():
                name = p.strip()
                dedupe = name.lower()
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                discussed.append(
                    {
                        "id": None,
                        "name": name,
                        "price": 0.0,
                        "stock_quantity": 0,
                        "currency": None,
                        "cache_key": "products_discussed:str",
                    }
                )

    processes_out: List[Dict[str, Any]] = []
    raw_proc = state.get("processes") or {}
    if isinstance(raw_proc, dict):
        for pid, proc in sorted(raw_proc.items(), key=lambda x: str(x[0])):
            if not isinstance(proc, dict):
                continue
            processes_out.append(
                {
                    "process_id": str(pid),
                    "task_type": proc.get("task_type"),
                    "product_name": proc.get("product_name"),
                    "order_id": proc.get("order_id"),
                    "order_number": proc.get("order_number"),
                    "status": proc.get("status"),
                    "quantity": proc.get("quantity"),
                    "tracking_number": proc.get("tracking_number"),
                    "logistic_id": str(proc.get("logistic_id"))
                    if proc.get("logistic_id")
                    else None,
                    "customer_address": proc.get("customer_address"),
                    "completed": bool(proc.get("completed", False)),
                }
            )

    return {"products_discussed": discussed, "processes": processes_out}


class SessionClearRequest(BaseModel):
    """IDs from the simulation UI. Omitted keys are skipped."""

    user_id: Optional[str] = None
    vendor_id: Optional[str] = None
    logistic_id: Optional[str] = None


@router.post("/clear")
async def clear_simulation_session(body: SessionClearRequest):
    """
    Delete Redis user_state and inbox lists for the given personas.
    Safe for local/simulation; does not flush the entire Redis DB.
    """
    cleared: List[str] = []

    if body.user_id and body.vendor_id:
        await delete_user_state(body.user_id, body.vendor_id)
        await delete_inbox_key(body.user_id)
        cleared.append(f"customer_state:{body.user_id}:{body.vendor_id}")
        cleared.append(f"inbox:{body.user_id}")

    if body.vendor_id:
        await delete_party_state(body.vendor_id)
        await delete_inbox_key(body.vendor_id)
        cleared.append(f"vendor_state:{body.vendor_id}")
        cleared.append(f"inbox:{body.vendor_id}")

    if body.logistic_id:
        await delete_party_state(body.logistic_id)
        await delete_inbox_key(body.logistic_id)
        cleared.append(f"logistics_state:{body.logistic_id}")
        cleared.append(f"inbox:{body.logistic_id}")

    return {"ok": True, "cleared": cleared}


_TERMINAL_ORDER_STATUSES = frozenset({"delivered", "cancelled"})


def _order_row_for_api(row: Dict[str, Any]) -> Dict[str, Any]:
    """JSON-serializable order row for dev UI."""
    o: Dict[str, Any] = {}
    for k, v in dict(row).items():
        if v is None:
            o[k] = None
        elif hasattr(v, "isoformat"):
            o[k] = v.isoformat()
        elif k in ("id", "user_id", "business_id", "logistic_id"):
            o[k] = str(v)
        elif k in ("product_attributes", "metadata") and not isinstance(v, dict):
            o[k] = v if isinstance(v, (str, int, float, bool)) else None
        else:
            o[k] = v
    return o


@router.get("/active-orders")
async def get_session_active_orders(
    user_id: str = Query(..., min_length=1),
    vendor_id: str = Query(..., min_length=1),
    limit: int = 25,
):
    """
    DB orders for this customer–vendor pair, excluding terminal statuses (delivered, cancelled).
    For simulation sidebar; same scope as Redis session key user_id:vendor_id.
    """
    lim = max(1, min(int(limit), 50))
    try:
        rows = await list_orders_for_customer_store(
            user_id,
            vendor_id,
            limit=lim * 2,
        )
    except Exception:
        logger.exception("active_orders list failed")
        raise HTTPException(status_code=500, detail="Failed to list orders.")

    active: List[Dict[str, Any]] = []
    for r in rows:
        st = str(r.get("status") or "").strip().lower()
        if st in _TERMINAL_ORDER_STATUSES:
            continue
        active.append(_order_row_for_api(dict(r)))
        if len(active) >= lim:
            break

    return JSONResponse(
        content={
            "user_id": user_id,
            "vendor_id": vendor_id,
            "count": len(active),
            "orders": active,
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/agent-context")
async def get_agent_context(
    user_id: str = Query(..., min_length=1),
    vendor_id: str = Query(..., min_length=1),
):
    """
    Redis session snapshot: products touched in chat retrieval cache and open/closed processes.
    """
    try:
        state = await get_user_state(user_id, vendor_id)
    except Exception:
        logger.exception("agent_context get_user_state failed")
        raise HTTPException(status_code=500, detail="Failed to load session state.")
    snap = _agent_context_from_state(state)
    body = {
        "user_id": user_id,
        "vendor_id": vendor_id,
        **snap,
        "process_count": len(snap["processes"]),
        "products_discussed_count": len(snap["products_discussed"]),
    }
    return JSONResponse(
        content=body,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )
