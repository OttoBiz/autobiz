from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class SubscriptionPlan(BaseModel):
    """Subscription plan model with pricing and features."""

    id: UUID
    name: str  # e.g., "Starter", "Professional", "Enterprise"
    tier: str  # e.g., "starter", "pro", "enterprise"
    price_monthly: Decimal
    price_yearly: Decimal
    features: dict  # Feature flags: max_agents, max_products, channels, etc.
    created_at: datetime
    updated_at: datetime
