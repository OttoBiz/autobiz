from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class Customer(BaseModel):
    id: UUID
    business_id: UUID

    # Basic Info
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None

    # CRM fields
    tags: list[str]
    segments: list[str]
    lifecycle_stage: str | None = None
    customer_value_score: int | None = None
    notes: str | None = None

    # Metadata
    custom_fields: dict
    preferences: dict

    created_at: datetime
    updated_at: datetime
