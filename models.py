"""SQLModel database models for WhatsApp AI Assistant."""

from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
import datetime as dt


class Business(SQLModel, table=True):
    """Business entity representing a company using the WhatsApp assistant."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    whatsapp_number: str = Field(unique=True, index=True)
    owner_name: str
    owner_contact: str
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    is_active: bool = Field(default=True)

    # Relationships
    products: List["Product"] = Relationship(back_populates="business")
    orders: List["Order"] = Relationship(back_populates="business")


class Customer(SQLModel, table=True):
    """Customer entity representing WhatsApp users interacting with the assistant."""

    id: Optional[int] = Field(default=None, primary_key=True)
    whatsapp_number: str = Field(unique=True, index=True)
    full_name: Optional[str] = None
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    # Relationships
    orders: List["Order"] = Relationship(back_populates="customer")


class Product(SQLModel, table=True):
    """Product entity representing items available for purchase."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    price: float = Field(ge=0)
    currency: str = Field(default="NGN")
    stock: int = Field(default=0, ge=0)
    is_active: bool = Field(default=True)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    # Relationships
    business: Optional[Business] = Relationship(back_populates="products")
    order_items: List["OrderItem"] = Relationship(back_populates="product")


class Order(SQLModel, table=True):
    """Order entity representing customer purchases."""

    id: Optional[int] = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    customer_id: int = Field(foreign_key="customer.id", index=True)
    status: str = Field(index=True)
    total_amount: float = Field(ge=0)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    updated_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    # Relationships
    business: Optional[Business] = Relationship(back_populates="orders")
    customer: Optional[Customer] = Relationship(back_populates="orders")
    items: List["OrderItem"] = Relationship(back_populates="order")
    payment: Optional["Payment"] = Relationship(back_populates="order")
    delivery: Optional["Delivery"] = Relationship(back_populates="order")


class OrderItem(SQLModel, table=True):
    """OrderItem entity representing individual products within an order."""

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    quantity: int = Field(ge=1)
    price: float = Field(ge=0)

    # Relationships
    order: Optional[Order] = Relationship(back_populates="items")
    product: Optional[Product] = Relationship(back_populates="order_items")


class Payment(SQLModel, table=True):
    """Payment entity representing payment transactions for orders."""

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", unique=True, index=True)
    status: str = Field(index=True)
    amount: float = Field(ge=0)
    provider: str
    transaction_ref: Optional[str] = Field(default=None, unique=True)
    verified_at: Optional[dt.datetime] = None
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    # Relationships
    order: Optional[Order] = Relationship(back_populates="payment")


class Delivery(SQLModel, table=True):
    """Delivery entity representing delivery information for orders."""

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", unique=True, index=True)
    address: str
    scheduled_date: Optional[dt.datetime] = None
    status: str = Field(index=True)
    tracking_info: Optional[str] = None
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    # Relationships
    order: Optional[Order] = Relationship(back_populates="delivery")
