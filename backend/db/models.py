import enum
from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Text, Numeric,
    Enum as SAEnum, Index, UniqueConstraint, text, func
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

# Define a base for declarative models
Base = declarative_base()

# --- ENUM Definitions ---
class ChannelPlatformEnum(enum.Enum):
    whatsapp = "whatsapp"
    instagram = "instagram"

class ItemTypeEnum(enum.Enum):
    product = "product"
    service = "service"

class PaymentTypeEnum(enum.Enum):
    api_gateway = "api_gateway"
    manual_bank_transfer = "manual_bank_transfer"

# --- Model Definitions ---
class Business(Base):
    __tablename__ = "businesses"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(255), nullable=False)
    admin_contact_phone_number = Column(String(20), nullable=False, unique=True)
    email = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    channels = relationship("BusinessChannel", back_populates="business", cascade="all, delete-orphan")
    products_services = relationship("ProductService", back_populates="business", cascade="all, delete-orphan")
    logistic_subscriptions = relationship("BusinessLogisticPartnerSubscription", back_populates="business", cascade="all, delete-orphan")
    payment_subscriptions = relationship("BusinessPaymentPartnerSubscription", back_populates="business", cascade="all, delete-orphan")
    # transactions = relationship("Transaction", back_populates="business") # Transactions related to this business

    __table_args__ = (
        Index("idx_businesses_admin_contact_phone_number", "admin_contact_phone_number"),
    )

class BusinessChannel(Base):
    __tablename__ = "business_channels"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    business_id = Column(PG_UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    platform = Column(SAEnum(ChannelPlatformEnum), nullable=False)
    platform_identifier = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    api_credentials = Column(Text, nullable=True) # Store encrypted or use a vault
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    business = relationship("Business", back_populates="channels")
    # conversations = relationship("Conversation", back_populates="business_channel", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("platform", "platform_identifier", name="uq_business_channel_platform_identifier"),
        Index("idx_business_channels_business_id", "business_id"),
        Index("idx_business_channels_platform_identifier", "platform_identifier"),
    )

class ProductService(Base):
    __tablename__ = "products_services"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    business_id = Column(PG_UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    item_type = Column(SAEnum(ItemTypeEnum), nullable=False)
    base_price = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(3), default="USD", nullable=False)
    attributes = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    business = relationship("Business", back_populates="products_services")

    __table_args__ = (
        Index("idx_products_services_business_id", "business_id"),
        Index("idx_products_services_attributes", attributes, postgresql_using="gin"),
    )

class LogisticPartner(Base):
    __tablename__ = "logistic_partners"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(255), nullable=False)
    linked_business_id = Column(PG_UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, unique=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(20), nullable=True)
    api_endpoint = Column(String(255), nullable=True)
    api_key = Column(Text, nullable=True) # Store encrypted
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    linked_business = relationship("Business") # One-to-one if a business is a logistic partner
    business_subscriptions = relationship("BusinessLogisticPartnerSubscription", back_populates="logistic_partner", cascade="all, delete-orphan")

class BusinessLogisticPartnerSubscription(Base):
    __tablename__ = "business_logistic_partner_subscriptions"

    business_id = Column(PG_UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True)
    logistic_partner_id = Column(PG_UUID(as_uuid=True), ForeignKey("logistic_partners.id", ondelete="RESTRICT"), primary_key=True)
    configuration_details = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    business = relationship("Business", back_populates="logistic_subscriptions")
    logistic_partner = relationship("LogisticPartner", back_populates="business_subscriptions")

class PaymentPartner(Base):
    __tablename__ = "payment_partners"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(255), nullable=False, unique=True)
    type = Column(SAEnum(PaymentTypeEnum), nullable=False)
    configuration_schema = Column(JSONB, nullable=True) # Describes required keys for business_payment_partner_subscriptions.configuration_details
    webhook_secret = Column(Text, nullable=True) # Store encrypted
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    business_subscriptions = relationship("BusinessPaymentPartnerSubscription", back_populates="payment_partner", cascade="all, delete-orphan")
    # webhook_events = relationship("WebhookEvent", back_populates="payment_partner")

class BusinessPaymentPartnerSubscription(Base):
    __tablename__ = "business_payment_partner_subscriptions"

    # Added a surrogate primary key for easier referencing from transactions table
    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    business_id = Column(PG_UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    payment_partner_id = Column(PG_UUID(as_uuid=True), ForeignKey("payment_partners.id", ondelete="RESTRICT"), nullable=False)
    configuration_details = Column(JSONB, nullable=False) # Store encrypted if sensitive
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    business = relationship("Business", back_populates="payment_subscriptions")
    payment_partner = relationship("PaymentPartner", back_populates="business_subscriptions")
    # transactions = relationship("Transaction", back_populates="payment_subscription")

    __table_args__ = (
        UniqueConstraint("business_id", "payment_partner_id", name="uq_bpps_business_payment_partner"),
        Index("idx_bpps_business_id", "business_id"),
    )
