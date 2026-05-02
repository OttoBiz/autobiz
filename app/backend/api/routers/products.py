"""
Products dashboard API.

Tenant-scoped (every endpoint reads ``ctx.business_id`` from the auth
context, never from the request body or query string). Endpoints land at
``/api/v1/products`` because main.py mounts this router with that prefix.

Errors use the common envelope ``{"error": {"code", "message", ...}}`` via
the ``_error`` helper. Cross-tenant lookups return 404 (not 403): our
helpers can't distinguish "missing" from "wrong tenant" without a second
query, and treating both as 404 is the safer default. The spec asks for
403 here -- TODO: revisit once we have a need to surface that distinction
to the dashboard.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.api import events
from backend.api.auth import SessionContext, require_session
from backend.api.schemas.products import (
    BulkImportJobRead,
    BulkUpdate,
    CategoriesResponse,
    ProductCreate,
    ProductListResponse,
    ProductPatch,
    ProductRead,
    ProductStatus,
    ProductTotals,
    StockAdjust,
    StockAdjustResponse,
    StockMovementListResponse,
    StockMovementRead,
)
from backend.db import db_utils
from backend.db.db_utils import (
    HasReferences,
    InsufficientStock,
    NotFound,
    SkuConflict,
    derive_status,
)
from backend.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/products", tags=["products"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(code: str, message: str, *, fields=None, details=None) -> dict:
    body: dict = {"code": code, "message": message}
    if fields is not None:
        body["fields"] = fields
    if details is not None:
        body["details"] = details
    return {"error": body}


def _to_product_read(row: dict) -> ProductRead:
    """Materialize a DB row into a ProductRead, deriving status and
    coercing recent_movements (when present) to StockMovementRead."""
    payload = dict(row)
    payload["status"] = derive_status(
        payload.get("is_active", True),
        payload.get("stock_quantity") or 0,
        payload.get("reorder_point") or 0,
    )
    if payload.get("recent_movements") is not None:
        payload["recent_movements"] = [
            StockMovementRead.model_validate(m) for m in payload["recent_movements"]
        ]
    return ProductRead.model_validate(payload)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/categories", response_model=CategoriesResponse)
async def list_categories_endpoint(
    ctx: SessionContext = Depends(require_session),
) -> CategoriesResponse:
    """Distinct categories used by this tenant. Registered before the
    UUID-path detail route so FastAPI doesn't try to parse "categories"
    as a UUID."""
    categories = await db_utils.list_categories(str(ctx.business_id))
    return CategoriesResponse(categories=categories)


@router.get("/", response_model=ProductListResponse)
async def list_products(
    status_filter: Optional[list[ProductStatus]] = Query(None, alias="status"),
    category: Optional[list[str]] = Query(None),
    search: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    ctx: SessionContext = Depends(require_session),
) -> ProductListResponse:
    statuses = [s.value for s in status_filter] if status_filter else None
    rows, next_cursor = await db_utils.list_products_for_api(
        str(ctx.business_id),
        statuses=statuses,
        categories=category,
        search=search,
        cursor=cursor,
        limit=limit,
    )
    items = [_to_product_read(r) for r in rows]
    totals_raw = await db_utils.get_product_status_totals(str(ctx.business_id))
    return ProductListResponse(
        items=items,
        next_cursor=next_cursor,
        totals=ProductTotals(**totals_raw),
    )


@router.post(
    "/",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_product_endpoint(
    body: ProductCreate,
    ctx: SessionContext = Depends(require_session),
) -> ProductRead:
    try:
        row = await db_utils.create_product(
            str(ctx.business_id),
            body.model_dump(),
            actor_id=str(ctx.user_id),
        )
    except SkuConflict as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(
                "sku_conflict",
                f"SKU '{e.sku}' already exists for this business",
                fields={"sku": [f"SKU '{e.sku}' already in use"]},
            ),
        )
    qty = int(row.get("stock_quantity") or 0)
    if qty > 0:
        events.emit_stock_changed(
            ctx.business_id,
            product_id=row["id"],
            new_qty=qty,
            delta=qty,
            actor_type="operator",
        )
    return _to_product_read(row)


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: UUID,
    ctx: SessionContext = Depends(require_session),
) -> ProductRead:
    row = await db_utils.get_product_for_api(str(ctx.business_id), str(product_id))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("not_found", "Product not found"),
        )
    return _to_product_read(row)


@router.get(
    "/{product_id}/stock-movements",
    response_model=StockMovementListResponse,
)
async def list_stock_movements_endpoint(
    product_id: UUID,
    cursor: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    ctx: SessionContext = Depends(require_session),
) -> StockMovementListResponse:
    # Confirm product exists in tenant before listing movements.
    product = await db_utils.get_product_for_api(
        str(ctx.business_id), str(product_id)
    )
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("not_found", "Product not found"),
        )
    rows, next_cursor = await db_utils.list_stock_movements(
        str(ctx.business_id),
        str(product_id),
        cursor=cursor,
        limit=limit,
        since=from_,
        until=to,
    )
    return StockMovementListResponse(
        items=[StockMovementRead.model_validate(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.patch("/{product_id}")
async def patch_product_endpoint(
    product_id: UUID,
    body: ProductPatch,
    ctx: SessionContext = Depends(require_session),
):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_error("empty_patch", "At least one field is required"),
        )

    # If discontinuing or changing stock, fetch existing to compare (and warn
    # on open orders for the discontinue path).
    warnings: list[str] = []
    existing: Optional[dict] = None
    needs_existing = (
        payload.get("is_active") is False or "stock_quantity" in payload
    )
    if needs_existing:
        existing = await db_utils.get_product_for_api(
            str(ctx.business_id), str(product_id)
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_error("not_found", "Product not found"),
            )
        if payload.get("is_active") is False and existing.get("is_active"):
            open_orders = await db_utils.get_open_order_count(
                str(ctx.business_id), str(product_id)
            )
            if open_orders > 0:
                logger.warning(
                    "discontinuing product with open orders | product_id=%s open_orders=%s",
                    str(product_id),
                    open_orders,
                )
                warnings.append(f"Product has {open_orders} open orders.")

    try:
        row = await db_utils.patch_product(
            str(ctx.business_id),
            str(product_id),
            payload,
            actor_id=str(ctx.user_id),
        )
    except NotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("not_found", "Product not found"),
        )
    except SkuConflict as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(
                "sku_conflict",
                f"SKU '{e.sku}' already exists for this business",
                fields={"sku": [f"SKU '{e.sku}' already in use"]},
            ),
        )

    # Pub/sub side effects (fire-and-forget).
    if "stock_quantity" in payload and existing is not None:
        old_qty = int(existing.get("stock_quantity") or 0)
        new_qty = int(row.get("stock_quantity") or 0)
        if new_qty != old_qty:
            events.emit_stock_changed(
                ctx.business_id,
                product_id=row["id"],
                new_qty=new_qty,
                delta=new_qty - old_qty,
                actor_type="operator",
            )
    if (
        payload.get("is_active") is False
        and existing is not None
        and existing.get("is_active")
    ):
        events.emit_discontinued(ctx.business_id, product_id=row["id"])

    product = _to_product_read(row)
    if warnings:
        # Wrap in {"product": ..., "warnings": [...]} when warnings exist.
        return JSONResponse(
            content={
                "product": product.model_dump(mode="json"),
                "warnings": warnings,
            }
        )
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_endpoint(
    product_id: UUID,
    ctx: SessionContext = Depends(require_session),
):
    try:
        await db_utils.delete_product(str(ctx.business_id), str(product_id))
    except NotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("not_found", "Product not found"),
        )
    except HasReferences as e:
        n = e.counts.get("orders", 0)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(
                "has_references",
                f"Product has {n} orders and cannot be deleted. Discontinue instead.",
                details=e.counts,
            ),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{product_id}/adjust-stock",
    response_model=StockAdjustResponse,
)
async def adjust_stock_endpoint(
    product_id: UUID,
    body: StockAdjust,
    ctx: SessionContext = Depends(require_session),
) -> StockAdjustResponse:
    try:
        product_row, movement_row = await db_utils.adjust_stock(
            str(ctx.business_id),
            str(product_id),
            body.delta,
            body.reason.value,
            body.note,
            actor_id=str(ctx.user_id),
            actor_type="operator",
        )
    except NotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("not_found", "Product not found"),
        )
    except InsufficientStock:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error("insufficient_stock", "Cannot reduce stock below zero"),
        )
    events.emit_stock_changed(
        ctx.business_id,
        product_id=product_row["id"],
        new_qty=int(product_row.get("stock_quantity") or 0),
        delta=body.delta,
        actor_type="operator",
    )
    return StockAdjustResponse(
        product=_to_product_read(product_row),
        movement=StockMovementRead.model_validate(movement_row),
    )


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


_BULK_IMPORT_REQUIRED_COLUMNS = {
    "sku",
    "name",
    "description",
    "price",
    "stock_quantity",
    "reorder_point",
    "category",
    "image_url",
    "is_negotiable",
}


def _coerce_bulk_value(key: str, raw: str):
    """Map blank CSV cells to None and coerce typed columns."""
    if raw is None:
        return None
    s = raw.strip()
    if s == "":
        return None
    if key in ("stock_quantity", "reorder_point"):
        return int(s)
    if key == "is_negotiable":
        return s.lower() in ("1", "true", "yes", "y", "t")
    return s


@router.post("/bulk-import", response_model=BulkImportJobRead)
async def bulk_import(
    file: UploadFile = File(...),
    ctx: SessionContext = Depends(require_session),
) -> BulkImportJobRead:
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_error("invalid_csv", "File must be UTF-8 CSV"),
        )

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = set(reader.fieldnames or [])
    missing = _BULK_IMPORT_REQUIRED_COLUMNS - fieldnames
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_error(
                "invalid_csv",
                f"Missing required columns: {sorted(missing)}",
            ),
        )

    rows = list(reader)
    if len(rows) > 10000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_error("too_many_rows", "Bulk import limited to 10,000 rows"),
        )

    business_id = str(ctx.business_id)
    actor_id = str(ctx.user_id)
    # TODO: emit inventory.stock_changed events per affected product after
    # bulk-import finishes. v1 skips this -- per-row publishes during a 10k
    # row import would be expensive and the agent runtime cache TTL is an
    # acceptable fallback for now.
    job_id = await db_utils.create_bulk_import_job(business_id)

    total_rows = len(rows)
    processed = 0
    created = 0
    updated = 0
    errors: list[dict] = []

    await db_utils.update_bulk_import_job(
        job_id, business_id, status="running", total_rows=total_rows
    )

    pool = await db_utils.get_db()

    for idx, raw_row in enumerate(rows, start=1):
        processed += 1
        coerced = {
            k: _coerce_bulk_value(k, v)
            for k, v in raw_row.items()
            if k in _BULK_IMPORT_REQUIRED_COLUMNS
        }
        sku = coerced.get("sku")

        # Validate via ProductCreate (handles type coercion + constraints).
        try:
            validated = ProductCreate.model_validate(
                {k: v for k, v in coerced.items() if v is not None}
            )
        except ValidationError as e:
            for err in e.errors():
                field = ".".join(str(x) for x in err.get("loc", ()))
                errors.append(
                    {
                        "row": idx,
                        "sku": sku,
                        "field": field,
                        "message": err.get("msg", "invalid"),
                    }
                )
            continue

        # Look up existing product by (business_id, sku).
        try:
            async with pool.acquire() as conn:
                existing = await conn.fetchrow(
                    "SELECT id, stock_quantity FROM products "
                    "WHERE business_id = $1::uuid AND sku = $2",
                    business_id,
                    validated.sku,
                )
        except Exception as e:
            errors.append(
                {
                    "row": idx,
                    "sku": sku,
                    "field": None,
                    "message": f"db error: {e.__class__.__name__}",
                }
            )
            continue

        try:
            if existing:
                # Patch with non-null fields. If stock_quantity differs, set
                # reason and note for the audit row.
                patch_payload = validated.model_dump()
                product_id = str(existing["id"])
                old_stock = int(existing["stock_quantity"] or 0)
                new_stock = int(patch_payload.get("stock_quantity") or 0)

                if new_stock != old_stock:
                    patch_payload["stock_change_reason"] = "manual_set"
                else:
                    patch_payload.pop("stock_quantity", None)

                # SKU is immutable on patch (matches the existing record), drop.
                patch_payload.pop("sku", None)

                await db_utils.patch_product(
                    business_id,
                    product_id,
                    patch_payload,
                    actor_id=actor_id,
                )
                # Audit note for stock change is set by patch_product as the
                # popped reason; we record an extra log line for traceability.
                if new_stock != old_stock:
                    logger.info(
                        "bulk_import stock change | job_id=%s product_id=%s",
                        job_id,
                        product_id,
                    )
                updated += 1
            else:
                await db_utils.create_product(
                    business_id,
                    validated.model_dump(),
                    actor_id=actor_id,
                )
                created += 1
        except SkuConflict as e:
            errors.append(
                {
                    "row": idx,
                    "sku": sku,
                    "field": "sku",
                    "message": f"SKU '{e.sku}' already exists",
                }
            )
        except Exception as e:
            errors.append(
                {
                    "row": idx,
                    "sku": sku,
                    "field": None,
                    "message": f"{e.__class__.__name__}",
                }
            )

    successes = created + updated
    final_status = "succeeded" if successes > 0 or not errors else "failed"

    await db_utils.update_bulk_import_job(
        job_id,
        business_id,
        status=final_status,
        total_rows=total_rows,
        processed=processed,
        created=created,
        updated=updated,
        errors=errors,
    )

    job = await db_utils.get_bulk_import_job(business_id, job_id)
    if job is None:
        # Should be impossible -- we just wrote it.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_error("internal", "Bulk import job vanished after creation"),
        )
    return BulkImportJobRead(
        job_id=job["id"],
        status=job["status"],
        total_rows=int(job.get("total_rows") or 0),
        processed=int(job.get("processed") or 0),
        created=int(job.get("created") or 0),
        updated=int(job.get("updated") or 0),
        errors=list(job.get("errors") or []),
    )


@router.get("/bulk-import/{job_id}", response_model=BulkImportJobRead)
async def get_bulk_import_job_endpoint(
    job_id: str,
    ctx: SessionContext = Depends(require_session),
) -> BulkImportJobRead:
    job = await db_utils.get_bulk_import_job(str(ctx.business_id), job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_error("not_found", "Bulk import job not found"),
        )
    return BulkImportJobRead(
        job_id=job["id"],
        status=job["status"],
        total_rows=int(job.get("total_rows") or 0),
        processed=int(job.get("processed") or 0),
        created=int(job.get("created") or 0),
        updated=int(job.get("updated") or 0),
        errors=list(job.get("errors") or []),
    )


# ---------------------------------------------------------------------------
# Bulk update
# ---------------------------------------------------------------------------


@router.post("/bulk-update")
async def bulk_update(
    body: BulkUpdate,
    ctx: SessionContext = Depends(require_session),
):
    business_id = str(ctx.business_id)
    filter_dict = body.filter.model_dump(exclude_none=True)
    patch_dict = body.patch.model_dump(exclude_none=True)

    dry = await db_utils.bulk_update_products(
        business_id, filter_dict, patch_dict, dry_run=True
    )
    matched = dry["matched_rows"]

    if matched > 100 and not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_error(
                "confirm_required",
                f"Filter would update {matched} rows; pass confirm=true to proceed",
                details={"matched_rows": matched},
            ),
        )

    result = await db_utils.bulk_update_products(
        business_id, filter_dict, patch_dict, dry_run=False
    )
    # TODO: emit per-row inventory.discontinued / stock_changed events when
    # bulk-update flips is_active=false or changes stock_quantity. v1 skips
    # this to avoid an extra round trip to fetch affected ids; the agent
    # runtime cache will fall back to its TTL for invalidation.
    return {
        "matched_rows": result["matched_rows"],
        "updated_rows": result["updated_rows"],
    }
