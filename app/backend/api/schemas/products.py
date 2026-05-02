"""Pydantic v2 schemas for the products API.

Money convention
----------------
Product prices (`price`, `floor_price`) are stored as ``DECIMAL(10,2)`` in
naira (the major currency unit, not kobo). To preserve precision across the
JSON boundary, money values are serialized as quantized 2-decimal *strings*
(e.g. ``"12000.00"``); JavaScript ``number`` cannot represent arbitrary
decimals safely, so emitting raw floats would silently corrupt amounts. On
input, both JSON strings and JSON numbers are accepted and quantized to two
decimals at validation time.

Note the asymmetry on bulk update: ``BulkUpdatePatch.price_delta`` is an
integer in *minor units* (kobo) per spec, even though the canonical money
representation elsewhere is decimal naira. See the field comment.

Input policy
------------
All request-body schemas set ``extra='forbid'`` so unknown fields produce a
422 instead of being silently dropped. PATCH semantics are implemented by
making every field ``Optional[...] = None`` and having the route handler use
``model.model_dump(exclude_unset=True)`` to distinguish "not provided" from
"set to null".
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProductStatus(str, Enum):
    """Derived status surfaced in serializers from is_active/stock/reorder_point."""

    in_stock = "in_stock"
    low_stock = "low_stock"
    out_of_stock = "out_of_stock"
    discontinued = "discontinued"


class StockMovementReason(str, Enum):
    restock = "restock"
    manual_set = "manual_set"
    correction = "correction"
    damage = "damage"
    sale = "sale"
    agent_decrement = "agent_decrement"


class StockChangeReason(str, Enum):
    """Subset of reasons allowed when PATCH changes stock_quantity."""

    manual_set = "manual_set"
    correction = "correction"


class OperatorAdjustReason(str, Enum):
    """Subset allowed for the operator-facing POST /adjust-stock endpoint.

    ``sale`` and ``agent_decrement`` are reserved for system/agent callers.
    """

    restock = "restock"
    correction = "correction"
    damage = "damage"
    manual_set = "manual_set"


class ActorType(str, Enum):
    operator = "operator"
    agent = "agent"
    system = "system"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_TWO_PLACES = Decimal("0.01")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Read schemas
# ---------------------------------------------------------------------------


class StockMovementRead(BaseModel):
    id: UUID
    delta: int
    reason: StockMovementReason
    note: Optional[str] = None
    actor_type: ActorType
    actor_id: Optional[UUID] = None
    created_at: datetime


class ProductRead(BaseModel):
    id: UUID
    sku: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price: Decimal
    stock_quantity: int
    reorder_point: int
    status: ProductStatus
    is_active: bool
    is_negotiable: bool
    floor_price: Optional[Decimal] = None
    image_url: Optional[str] = None
    last_restocked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Populated by the detail endpoint; lists omit this to keep payloads small.
    recent_movements: Optional[list[StockMovementRead]] = None

    @field_serializer("price")
    def _serialize_price(self, value: Decimal) -> str:
        return f"{_quantize_money(value):.2f}"

    @field_serializer("floor_price")
    def _serialize_floor_price(self, value: Optional[Decimal]) -> Optional[str]:
        if value is None:
            return None
        return f"{_quantize_money(value):.2f}"


# ---------------------------------------------------------------------------
# Write schemas
# ---------------------------------------------------------------------------


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,49}$")
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    price: Decimal = Field(ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    reorder_point: int = Field(default=0, ge=0)
    # Category allowlist is enforced at runtime by the handler against
    # tenant-configurable settings, not baked into the schema.
    category: Optional[str] = None
    image_url: Optional[str] = None
    is_negotiable: bool = False
    floor_price: Optional[Decimal] = Field(default=None, ge=0)

    @field_validator("price", "floor_price", mode="before")
    @classmethod
    def _coerce_money(cls, value: Any) -> Any:
        if value is None:
            return value
        # Accept strings or numbers; let pydantic raise on garbage.
        if isinstance(value, Decimal):
            dec = value
        else:
            dec = Decimal(str(value))
        return _quantize_money(dec)

    @model_validator(mode="after")
    def _floor_price_le_price(self) -> "ProductCreate":
        if self.floor_price is not None and self.floor_price > self.price:
            raise ValueError("floor_price must be less than or equal to price")
        return self


class ProductPatch(BaseModel):
    """Partial update. Use ``model_dump(exclude_unset=True)`` at the call site.

    Per spec, ``id``, ``business_id``, ``sku``, ``created_at``, and
    ``updated_at`` are not patchable; ``extra='forbid'`` rejects them.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(default=None, ge=0)
    category: Optional[str] = None
    reorder_point: Optional[int] = Field(default=None, ge=0)
    image_url: Optional[str] = None
    is_active: Optional[bool] = None
    is_negotiable: Optional[bool] = None
    floor_price: Optional[Decimal] = Field(default=None, ge=0)
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    stock_change_reason: Optional[StockChangeReason] = None

    @field_validator("price", "floor_price", mode="before")
    @classmethod
    def _coerce_money(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, Decimal):
            dec = value
        else:
            dec = Decimal(str(value))
        return _quantize_money(dec)

    @model_validator(mode="after")
    def _stock_change_requires_reason(self) -> "ProductPatch":
        # Use model_fields_set so explicit ``None`` still counts as "set".
        stock_set = "stock_quantity" in self.model_fields_set
        reason_set = "stock_change_reason" in self.model_fields_set
        if stock_set and not reason_set:
            raise ValueError(
                "stock_change_reason is required when stock_quantity is set"
            )
        if reason_set and not stock_set:
            raise ValueError(
                "stock_change_reason may only be set when stock_quantity is set"
            )
        return self


class StockAdjust(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delta: int
    reason: OperatorAdjustReason
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("delta")
    @classmethod
    def _delta_nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("delta must be non-zero")
        return value


class StockAdjustResponse(BaseModel):
    product: ProductRead
    movement: StockMovementRead


# ---------------------------------------------------------------------------
# Listing / pagination
# ---------------------------------------------------------------------------


class Pagination(BaseModel):
    next_cursor: Optional[str] = None


class ProductTotals(BaseModel):
    in_stock: int
    low_stock: int
    out_of_stock: int
    discontinued: int


class ProductListResponse(BaseModel):
    items: list[ProductRead]
    next_cursor: Optional[str] = None
    totals: ProductTotals


class StockMovementListResponse(BaseModel):
    items: list[StockMovementRead]
    next_cursor: Optional[str] = None


class CategoriesResponse(BaseModel):
    categories: list[str]


# ---------------------------------------------------------------------------
# Bulk update
# ---------------------------------------------------------------------------


class BulkUpdateFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Optional[str] = None
    is_active: Optional[bool] = None
    sku_in: Optional[list[str]] = None


class BulkUpdatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_multiplier: Optional[float] = Field(default=None, ge=0.1, le=10.0)
    # Spec asymmetry: price_delta is in integer *minor units* (kobo) on bulk
    # update, even though the canonical money type elsewhere is decimal naira.
    # Honor the spec; conversion happens in the handler.
    price_delta: Optional[int] = None
    reorder_point: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    # Category allowlist enforced by the handler at runtime.
    category: Optional[str] = None

    @model_validator(mode="after")
    def _validate_combination(self) -> "BulkUpdatePatch":
        provided = {
            name
            for name in (
                "price_multiplier",
                "price_delta",
                "reorder_point",
                "is_active",
                "category",
            )
            if getattr(self, name) is not None
        }
        if not provided:
            raise ValueError("at least one field must be set")
        if "price_multiplier" in provided and "price_delta" in provided:
            raise ValueError(
                "price_multiplier and price_delta cannot both be set"
            )
        return self


class BulkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: BulkUpdateFilter
    patch: BulkUpdatePatch
    confirm: bool = False


# ---------------------------------------------------------------------------
# Bulk import job
# ---------------------------------------------------------------------------


class BulkImportJobRead(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    total_rows: int
    processed: int
    created: int
    updated: int
    # Each error: {row, sku?, field?, message}
    errors: list[dict]


# ---------------------------------------------------------------------------
# Error envelope (for OpenAPI response docs)
# ---------------------------------------------------------------------------


class ApiError(BaseModel):
    code: str
    message: str
    fields: Optional[dict] = None
    details: Optional[dict] = None


class ApiErrorEnvelope(BaseModel):
    error: ApiError
