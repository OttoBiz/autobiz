from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class Product(BaseModel):
    id: UUID
    business_id: UUID

    # Product Info
    sku: str
    name: str
    description: str | None = None
    price: Decimal
    currency: str
    category: str | None = None

    # Inventory
    inventory_count: int
    low_stock_threshold: int

    # Media & Variants
    images: list
    variants: dict

    # Metadata
    metadata: dict
    status: str

    created_at: datetime
    updated_at: datetime
