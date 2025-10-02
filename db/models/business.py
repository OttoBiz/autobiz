from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class Business(BaseModel):
    """Business model with subscription, company info, and settings."""

    id: UUID
    name: str
    slug: str
    owner_user_id: UUID

    # Subscription
    subscription_plan_id: UUID
    subscription_status: str  # "active", "trialing", "past_due", "canceled"
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None

    # Company Info
    description: str | None = None
    industry: str | None = None
    contact_email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    policies: dict = {}  # shipping, return, privacy policies

    # Branding
    logo_url: str | None = None
    primary_color: str | None = None  # hex color
    theme_config: dict = {}

    # Settings
    timezone: str = "UTC"
    currency: str = "USD"
    business_hours: dict = {}  # operating hours per day

    # Product Catalog Sync
    catalog_sync_source: str | None = None  # "shopify", "woocommerce", etc.
    catalog_sync_config: dict = {}

    created_at: datetime
    updated_at: datetime
