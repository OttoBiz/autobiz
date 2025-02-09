from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
import uuid

from sqlalchemy import Column, String, Integer, ForeignKey, Table, Numeric, DateTime, Enum as SQLAEnum
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship, mapped_column, Mapped

from backend.core.database import Base 

class AbstractModel(Base):
    __abstract__ = True
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

# Association table for many-to-many relationship
business_partner_link = Table(
    'business_partner_link',
    Base.metadata,
    Column('business_id', UUID(as_uuid=True), ForeignKey('business.id'), primary_key=True),
    Column('partner_id', UUID(as_uuid=True), ForeignKey('businesspartner.id'), primary_key=True)
)

class Business(AbstractModel):
    __tablename__ = 'business'

    name: Mapped[str] = mapped_column(String(100), index=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    website: Mapped[Optional[str]] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50), index=True)
    whatsapp_id: Mapped[Optional[str]] = mapped_column(String(50))
    facebook_page: Mapped[Optional[str]] = mapped_column(String(255))
    twitter_page: Mapped[Optional[str]] = mapped_column(String(255))
    tiktok: Mapped[Optional[str]] = mapped_column(String(255))
    instagram_page: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String))
    bank_name: Mapped[Optional[str]] = mapped_column(String(100))
    bank_account_number: Mapped[Optional[str]] = mapped_column(String(50))
    bank_account_name: Mapped[Optional[str]] = mapped_column(String(100))
    webhook_url: Mapped[Optional[str]] = mapped_column(String(255))

    partners: Mapped[list["BusinessPartner"]] = relationship(
        "BusinessPartner",
        secondary=business_partner_link,
        back_populates="businesses"
    )
    products: Mapped[list["Product"]] = relationship("Product", back_populates="business")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="business")

class BusinessPartner(AbstractModel):
    __tablename__ = 'businesspartner'

    name: Mapped[str] = mapped_column(String)
    phone_number: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    website: Mapped[str] = mapped_column(String)

    businesses: Mapped[list["Business"]] = relationship(
        "Business",
        secondary=business_partner_link,
        back_populates="partners"
    )

class TransactionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"

class Product(AbstractModel):
    __tablename__ = 'product'

    name: Mapped[str] = mapped_column(String(255), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3))  # ISO 4217 currency codes
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    items_in_stock: Mapped[int] = mapped_column(Integer)

    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("business.id"))
    business: Mapped["Business"] = relationship("Business", back_populates="products")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="product")

class Transaction(AbstractModel):
    __tablename__ = 'transaction'

    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[TransactionStatus] = mapped_column(SQLAEnum(TransactionStatus))

    business_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("business.id"))
    business: Mapped["Business"] = relationship("Business", back_populates="transactions")

    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("product.id"))
    product: Mapped["Product"] = relationship("Product", back_populates="transactions")

# Database connection setup (commented out as in original)
# sqlite_file_name = "database.db"
# sqlite_url = f"sqlite:///{sqlite_file_name}"
# connect_args = {"check_same_thread": False}
# engine = create_engine(sqlite_url, echo=True, connect_args=connect_args)