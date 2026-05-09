"""
Pydantic models/schemas for Ottobiz.

These models define the shape of data for validation and serialization.
They correspond to the database tables created in migrations but don't
use SQLAlchemy ORM - we use asyncpg with raw SQL instead.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import UUID4, BaseModel, Field


# Enums
class BusinessTier(str, Enum):
    """Business subscription tier"""

    FREE = "free"
    GOLD = "gold"
    PLATINUM = "platinum"


class PaymentStatus(str, Enum):
    """Payment status"""

    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class OrderStatus(str, Enum):
    """Order status"""

    PENDING = "pending"
    PAYMENT_VERIFIED = "payment_verified"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# Core Schemas
class UserBase(BaseModel):
    """Base user schema"""

    phone_number: str = Field(..., max_length=20)
    full_name: Optional[str] = Field(None, max_length=100)
    delivery_address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)


class UserCreate(UserBase):
    """Schema for creating a user"""

    pass


class UserUpdate(BaseModel):
    """Schema for updating a user"""

    full_name: Optional[str] = None
    delivery_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None


class User(UserBase):
    """Complete user schema with database fields"""

    id: UUID4
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BusinessBase(BaseModel):
    """Base business schema"""

    name: str = Field(..., max_length=100)
    tier: BusinessTier = BusinessTier.FREE
    phone_number: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=100)

    # Social media
    ig_page: Optional[str] = None
    facebook_page: Optional[str] = None
    twitter_page: Optional[str] = None
    tiktok: Optional[str] = None

    # Payment information
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_account_name: Optional[str] = None
    paystack_public_key: Optional[str] = None
    paystack_secret_key: Optional[str] = None

    # Fulfillment: subset of {'delivery','pickup'}, at least one. Pickup
    # tenants must populate physical_* at the app layer (not enforced in SQL
    # so a tenant can be created before the operator fills them in).
    fulfillment_modes: List[str] = Field(default_factory=lambda: ["delivery"])
    physical_address: Optional[str] = None
    physical_city: Optional[str] = None
    physical_state: Optional[str] = None


class BusinessCreate(BusinessBase):
    """Schema for creating a business"""

    pass


class BusinessUpdate(BaseModel):
    """Schema for updating a business"""

    name: Optional[str] = None
    tier: Optional[BusinessTier] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_account_name: Optional[str] = None
    paystack_public_key: Optional[str] = None


class Business(BusinessBase):
    """Complete business schema with database fields"""

    id: UUID4
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductBase(BaseModel):
    """Base product schema"""

    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    sku: Optional[str] = Field(None, max_length=50)
    category: Optional[str] = Field(None, max_length=100)
    attributes: Optional[Dict[str, Any]] = None
    is_active: bool = True
    is_negotiable: bool = False
    floor_price: Optional[float] = Field(default=None, ge=0)


class ProductCreate(ProductBase):
    """Schema for creating a product"""

    business_id: UUID4


class ProductUpdate(BaseModel):
    """Schema for updating a product"""

    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    stock_quantity: Optional[int] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None
    is_negotiable: Optional[bool] = None
    floor_price: Optional[float] = Field(default=None, ge=0)


class Product(ProductBase):
    """Complete product schema with database fields"""

    id: UUID4
    business_id: UUID4
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OrderBase(BaseModel):
    """Base order schema"""

    total_amount: float = Field(..., ge=0)
    delivery_address: Optional[str] = None
    delivery_city: Optional[str] = None
    delivery_state: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class OrderCreate(OrderBase):
    """Schema for creating an order"""

    user_id: UUID4
    business_id: UUID4


class OrderUpdate(BaseModel):
    """Schema for updating an order"""

    status: Optional[OrderStatus] = None
    tracking_number: Optional[str] = None


class Order(OrderBase):
    """Complete order schema with database fields"""

    id: UUID4
    order_number: str
    user_id: UUID4
    business_id: UUID4
    status: OrderStatus
    tracking_number: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TransactionBase(BaseModel):
    """Base transaction schema"""

    amount: float = Field(..., ge=0)
    payment_method: Optional[str] = None
    receipt_image_url: Optional[str] = None
    transaction_reference: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TransactionCreate(TransactionBase):
    """Schema for creating a transaction"""

    user_id: UUID4
    business_id: UUID4
    order_id: Optional[UUID4] = None


class TransactionUpdate(BaseModel):
    """Schema for updating a transaction"""

    status: Optional[PaymentStatus] = None


class Transaction(TransactionBase):
    """Complete transaction schema with database fields"""

    id: UUID4
    order_id: Optional[UUID4] = None
    user_id: UUID4
    business_id: UUID4
    status: PaymentStatus
    created_at: datetime
    verified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Response models for API endpoints
class OrderWithDetails(Order):
    """Order with related user and business information"""

    user: Optional[User] = None
    business: Optional[Business] = None


class TransactionWithDetails(Transaction):
    """Transaction with related user and business information"""

    user: Optional[User] = None
    business: Optional[Business] = None
    order: Optional[Order] = None


# Legacy compatibility - keep these for backward compatibility with existing code
class ChatMessage(BaseModel):
    """Legacy chat message schema (now using file storage)"""

    role: str
    name: str
    content: str
    timestamp: Optional[datetime] = None
