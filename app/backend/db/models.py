"""
Database models for Ottobiz
Enhanced schema to support all business operations
"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
    Text,
    JSON,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum
from .database import Base, engine


class BusinessTier(str, enum.Enum):
    """Business subscription tier"""
    FREE = "free"
    GOLD = "gold"
    PLATINUM = "platinum"


class BusinessType(str, enum.Enum):
    """Type of business"""
    VENDOR = "vendor"
    LOGISTICS = "logistics"
    SERVICE_PROVIDER = "service_provider"


class PaymentStatus(str, enum.Enum):
    """Payment status"""
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    REFUNDED = "refunded"


class OrderStatus(str, enum.Enum):
    """Order status"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class TicketStatus(str, enum.Enum):
    """Support ticket status"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class User(Base):
    """User/Customer model"""
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    phone_number = Column(String(20), unique=True, nullable=False)
    email = Column(String(100))
    full_name = Column(String(100))
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    country = Column(String(100))
    date_created = Column(DateTime, default=datetime.now)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    orders = relationship("Order", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    chat_history = relationship("ChatHistory", back_populates="user")
    tickets = relationship("Ticket", back_populates="user")


class Business(Base):
    """Business model (vendors, logistics, service providers)"""
    __tablename__ = "businesses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    business_name = Column(String(100), nullable=False)
    business_type = Column(SQLEnum(BusinessType), nullable=False, default=BusinessType.VENDOR)
    tier = Column(SQLEnum(BusinessTier), nullable=False, default=BusinessTier.FREE)
    
    # Contact information
    email = Column(String(100), nullable=False)
    phone_number = Column(String(20))
    ig_page = Column(String(100))
    facebook_page = Column(String(100))
    twitter_page = Column(String(100))
    tiktok = Column(String(100))
    website = Column(String(100))
    
    # Business details
    business_description = Column(Text)
    business_niche = Column(String(100))
    
    # Payment information
    bank_name = Column(String(100))
    bank_account_number = Column(String(50))
    bank_account_name = Column(String(50))
    paystack_public_key = Column(String(200))
    paystack_secret_key = Column(String(200))
    
    # Human agent contact (for customer service escalation)
    human_agent_phone = Column(String(20))
    human_agent_email = Column(String(100))
    
    # Metadata
    date_created = Column(DateTime, default=datetime.now)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    products = relationship("Product", back_populates="business", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="business", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="business")
    orders = relationship("Order", back_populates="business")
    inventory_items = relationship("InventoryItem", back_populates="business")
    tickets = relationship("Ticket", back_populates="business")
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": str(self.id),
            "business_name": self.business_name,
            "business_type": self.business_type.value if self.business_type else None,
            "tier": self.tier.value if self.tier else None,
            "email": self.email,
            "phone_number": self.phone_number,
            "business_description": self.business_description,
            "business_niche": self.business_niche,
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
        }


class Product(Base):
    """Product model"""
    __tablename__ = "products"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    product_name = Column(String(100), nullable=False)
    product_description = Column(Text)
    product_category = Column(String(100))
    price = Column(Float, nullable=False)
    items_in_stock = Column(Integer, default=0)
    tags = Column(String(200))
    image_urls = Column(JSON)  # List of image URLs for multimodal retrieval
    date_created = Column(DateTime, default=datetime.now)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    business = relationship("Business", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product")
    inventory_items = relationship("InventoryItem", back_populates="product")
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": str(self.id),
            "product_name": self.product_name,
            "price": self.price,
            "items_left_in_stock": self.items_in_stock,
            "tags": self.tags,
            "product_description": self.product_description,
            "product_category": self.product_category,
            "image_urls": self.image_urls or [],
        }


class Service(Base):
    """Service model (for businesses offering services like dry cleaning)"""
    __tablename__ = "services"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    service_name = Column(String(100), nullable=False)
    service_description = Column(Text)
    service_category = Column(String(100))
    price = Column(Float, nullable=False)
    duration_hours = Column(Integer)  # Estimated duration in hours
    tags = Column(String(200))
    date_created = Column(DateTime, default=datetime.now)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    business = relationship("Business", back_populates="services")
    order_items = relationship("OrderItem", back_populates="service")
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": str(self.id),
            "service_name": self.service_name,
            "price": self.price,
            "service_description": self.service_description,
            "service_category": self.service_category,
            "duration_hours": self.duration_hours,
            "tags": self.tags,
        }


class Order(Base):
    """Order model"""
    __tablename__ = "orders"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    logistic_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=True)
    
    order_number = Column(String(50), unique=True, nullable=False)
    status = Column(SQLEnum(OrderStatus), nullable=False, default=OrderStatus.PENDING)
    total_amount = Column(Float, nullable=False)
    
    # Delivery information
    delivery_address = Column(Text)
    delivery_city = Column(String(100))
    delivery_state = Column(String(100))
    delivery_country = Column(String(100))
    tracking_number = Column(String(100))
    
    # Metadata
    date_created = Column(DateTime, default=datetime.now)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="orders")
    business = relationship("Business", foreign_keys=[business_id], back_populates="orders")
    order_items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="order")
    invoices = relationship("Invoice", back_populates="order")
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": str(self.id),
            "order_number": self.order_number,
            "status": self.status.value if self.status else None,
            "total_amount": self.total_amount,
            "delivery_address": self.delivery_address,
            "tracking_number": self.tracking_number,
            "date_created": self.date_created.isoformat() if self.date_created else None,
        }


class OrderItem(Base):
    """Order items (products or services in an order)"""
    __tablename__ = "order_items"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id"), nullable=True)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=False)
    subtotal = Column(Float, nullable=False)
    
    # Relationships
    order = relationship("Order", back_populates="order_items")
    product = relationship("Product", back_populates="order_items")
    service = relationship("Service", back_populates="order_items")


class Transaction(Base):
    """Transaction/Payment model"""
    __tablename__ = "transactions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    
    payment_status = Column(SQLEnum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING)
    amount = Column(Float, nullable=False)
    payment_method = Column(String(50))  # bank_transfer, paystack, etc.
    
    # Payment verification details
    receipt_image_url = Column(String(500))
    bank_name = Column(String(100))
    bank_account_number = Column(String(50))
    bank_account_name = Column(String(50))
    transaction_reference = Column(String(100))
    
    # Metadata
    date = Column(DateTime, default=datetime.now)
    verified_at = Column(DateTime)
    
    # Relationships
    user = relationship("User", back_populates="transactions")
    business = relationship("Business", back_populates="transactions")
    order = relationship("Order", back_populates="transactions")


class Invoice(Base):
    """Invoice model"""
    __tablename__ = "invoices"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    invoice_number = Column(String(50), unique=True, nullable=False)
    invoice_url = Column(String(500))  # URL to generated invoice PDF
    date_created = Column(DateTime, default=datetime.now)
    
    # Relationships
    order = relationship("Order", back_populates="invoices")


class Ticket(Base):
    """Support ticket model"""
    __tablename__ = "tickets"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    
    ticket_number = Column(String(50), unique=True, nullable=False)
    status = Column(SQLEnum(TicketStatus), nullable=False, default=TicketStatus.OPEN)
    subject = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    resolution = Column(Text)
    
    # Metadata
    date_created = Column(DateTime, default=datetime.now)
    date_resolved = Column(DateTime)
    
    # Relationships
    user = relationship("User", back_populates="tickets")
    business = relationship("Business", back_populates="tickets")


class ChatHistory(Base):
    """Chat history model"""
    __tablename__ = "chat_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=True)
    session_id = Column(String(100), nullable=False)
    
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    agent_used = Column(String(50))  # Which agent generated this response
    metadata = Column(JSON)  # Additional metadata
    
    date_created = Column(DateTime, default=datetime.now)
    
    # Relationships
    user = relationship("User", back_populates="chat_history")
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            "role": self.role,
            "content": self.content,
            "agent_used": self.agent_used,
            "date_created": self.date_created.isoformat() if self.date_created else None,
        }


class InventoryItem(Base):
    """Inventory management model"""
    __tablename__ = "inventory_items"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    
    quantity = Column(Integer, nullable=False, default=0)
    reorder_level = Column(Integer, default=10)  # Alert when stock falls below this
    last_restocked = Column(DateTime)
    
    # Relationships
    business = relationship("Business", back_populates="inventory_items")
    product = relationship("Product", back_populates="inventory_items")


class SupplyChain(Base):
    """Supply chain tracking model"""
    __tablename__ = "supply_chain"
    
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    supplier_name = Column(String(100), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=True)
    
    quantity_ordered = Column(Integer, nullable=False)
    quantity_received = Column(Integer, default=0)
    expected_delivery_date = Column(DateTime)
    actual_delivery_date = Column(DateTime)
    status = Column(String(50), default="pending")  # pending, in_transit, delivered
    
    date_created = Column(DateTime, default=datetime.now)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# Create all tables
Base.metadata.create_all(bind=engine)
