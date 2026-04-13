"""Simulation / dev helpers: clear Redis state for selected personas."""

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.db.cache_utils import delete_inbox_key, delete_party_state, delete_user_state

router = APIRouter(prefix="/session", tags=["session"])


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
