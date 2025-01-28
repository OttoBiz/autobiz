from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
import uuid
from sqlalchemy import Numeric
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Column, Field, Relationship, SQLModel, String


class BaseModel(SQLModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Business(BaseModel, table=True):
    name: str = Field(max_length=100, index=True)
    phone_number: str = Field(index=True, max_length=20)
    email: str = Field(max_length=255, index=True)
    website: Optional[str] = Field(max_length=255, default=None)
    category: str = Field(max_length=50, index=True)
    whatsapp_id: Optional[str] = Field(max_length=50, default=None)
    facebook_page: Optional[str] = Field(max_length=255, default=None)
    twitter_page: Optional[str] = Field(max_length=255, default=None)
    tiktok: Optional[str] = Field(max_length=255, default=None)
    instagram_page: Optional[str] = Field(max_length=255, default=None)
    description: Optional[str] = Field(max_length=1000, default=None)
    tags: list[str] = Field(sa_column=Column(ARRAY(String())))
    bank_name: Optional[str] = Field(max_length=100, default=None)
    bank_account_number: Optional[str] = Field(max_length=50, default=None)
    bank_account_name: Optional[str] = Field(max_length=100, default=None)
    partners: list["BusinessPartner"] = Relationship(back_populates="businesses", link_model="BusinessPartnerLink")
    products: list["Product"] = Relationship(back_populates="business")
    transactions: list["Transaction"] = Relationship(back_populates="business")

class BusinessPartner(BaseModel, table=True):
    name: str
    phone_number: str
    email: str
    website: str
    businesses: list["Business"] = Relationship(back_populates="partners", link_model="BusinessPartnerLink")


class BusinessPartnerLink(SQLModel, table=True):
    business_id: uuid.UUID = Field(foreign_key="business.id", primary_key=True)
    partner_id: uuid.UUID = Field(foreign_key="businesspartner.id", primary_key=True)


class Product(BaseModel, table=True):
    name: str = Field(max_length=255, index=True)
    price: Decimal = Field(sa_column=Column(Numeric(10, 2)))
    currency: str = Field(max_length=3)  # ISO 4217 currency codes
    description: Optional[str] = Field(max_length=1000, default=None)
    items_in_stock: int = Field(ge=0)
    
    business_id: uuid.UUID = Field(foreign_key="business.id")
    business: Business = Relationship(back_populates="products")
    transactions: list["Transaction"] = Relationship(back_populates="product")

class TransactionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class Transaction(BaseModel, table=True):
    amount: Decimal = Field(sa_column=Column(Numeric(10, 2)))
    status: TransactionStatus
    
    business_id: uuid.UUID = Field(foreign_key="business.id")
    business: Business = Relationship(back_populates="transactions")
    
    product_id: uuid.UUID = Field(foreign_key="product.id")
    product: Product = Relationship(back_populates="transactions")

