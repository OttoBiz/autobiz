"""Database interaction functions for WhatsApp AI Assistant."""

import logging
from typing import Optional, List, Any, Dict
from datetime import datetime, timezone
from contextlib import contextmanager

from sqlmodel import SQLModel, Session, create_engine, select, desc
import redis
from redis.exceptions import ConnectionError as RedisConnectionError

from config import settings
from models import (
    Business, Customer, Product, Order, OrderItem, Payment, Delivery,
    CentralMemory
)

logger = logging.getLogger(__name__)


# ============================================================================
# Database Connection Management
# ============================================================================

# PostgreSQL engine
postgres_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=settings.debug
)

# Redis connection
redis_client = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5
)


def create_tables() -> None:
    """Create all database tables."""
    try:
        SQLModel.metadata.create_all(postgres_engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        raise


@contextmanager
def get_db_session():
    """Context manager for database sessions."""
    session = Session(postgres_engine)
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {e}")
        raise
    finally:
        session.close()


def test_db_connection() -> bool:
    """Test PostgreSQL database connection."""
    try:
        with get_db_session() as session:
            session.exec(select(1))
        logger.info("PostgreSQL connection successful")
        return True
    except Exception as e:
        logger.error(f"PostgreSQL connection failed: {e}")
        return False


def test_redis_connection() -> bool:
    """Test Redis connection."""
    try:
        redis_client.ping()
        logger.info("Redis connection successful")
        return True
    except RedisConnectionError as e:
        logger.error(f"Redis connection failed: {e}")
        return False


# ============================================================================
# Redis Session Management
# ============================================================================

def save_memory(session_id: str, memory: CentralMemory) -> bool:
    """Save CentralMemory to Redis."""
    try:
        key = f"session:{session_id}"
        memory.updated_at = datetime.now(timezone.utc)
        redis_client.setex(
            key,
            settings.session_timeout_minutes * 60,
            memory.model_dump_json()
        )
        logger.debug(f"Saved memory for session {session_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save memory for session {session_id}: {e}")
        return False


def load_memory(session_id: str) -> Optional[CentralMemory]:
    """Load CentralMemory from Redis."""
    try:
        key = f"session:{session_id}"
        data = redis_client.get(key)
        if data and isinstance(data, str):
            memory = CentralMemory.model_validate_json(data)
            logger.debug(f"Loaded memory for session {session_id}")
            return memory
        logger.debug(f"No memory found for session {session_id}")
        return None
    except Exception as e:
        logger.error(f"Failed to load memory for session {session_id}: {e}")
        return None


def delete_memory(session_id: str) -> bool:
    """Delete CentralMemory from Redis."""
    try:
        key = f"session:{session_id}"
        result = redis_client.delete(key)
        logger.debug(f"Deleted memory for session {session_id}")
        return bool(result)
    except Exception as e:
        logger.error(f"Failed to delete memory for session {session_id}: {e}")
        return False


def extend_memory_ttl(session_id: str) -> bool:
    """Extend TTL for CentralMemory in Redis."""
    try:
        key = f"session:{session_id}"
        redis_client.expire(key, settings.session_timeout_minutes * 60)
        logger.debug(f"Extended TTL for session {session_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to extend TTL for session {session_id}: {e}")
        return False


# ============================================================================
# Business CRUD Operations
# ============================================================================

def create_business(
    name: str,
    whatsapp_number: str,
    owner_name: str,
    owner_contact: str
) -> Optional[Business]:
    """Create a new business."""
    try:
        with get_db_session() as session:
            business = Business(
                name=name,
                whatsapp_number=whatsapp_number,
                owner_name=owner_name,
                owner_contact=owner_contact
            )
            session.add(business)
            session.commit()
            session.refresh(business)
            logger.info(f"Created business: {business.name} (ID: {business.id})")
            return business
    except Exception as e:
        logger.error(f"Failed to create business: {e}")
        return None


def get_business_by_id(business_id: int) -> Optional[Business]:
    """Get business by ID."""
    try:
        with get_db_session() as session:
            business = session.get(Business, business_id)
            return business
    except Exception as e:
        logger.error(f"Failed to get business by ID {business_id}: {e}")
        return None


def get_business_by_whatsapp(whatsapp_number: str) -> Optional[Business]:
    """Get business by WhatsApp number."""
    try:
        with get_db_session() as session:
            statement = select(Business).where(Business.whatsapp_number == whatsapp_number)
            business = session.exec(statement).first()
            return business
    except Exception as e:
        logger.error(f"Failed to get business by WhatsApp number {whatsapp_number}: {e}")
        return None


def update_business(business_id: int, **kwargs) -> Optional[Business]:
    """Update business information."""
    try:
        with get_db_session() as session:
            business = session.get(Business, business_id)
            if not business:
                logger.warning(f"Business with ID {business_id} not found")
                return None
            
            for key, value in kwargs.items():
                if hasattr(business, key):
                    setattr(business, key, value)
            
            session.add(business)
            session.commit()
            session.refresh(business)
            logger.info(f"Updated business ID {business_id}")
            return business
    except Exception as e:
        logger.error(f"Failed to update business {business_id}: {e}")
        return None


def list_businesses(active_only: bool = True) -> List[Business]:
    """List all businesses."""
    try:
        with get_db_session() as session:
            statement = select(Business)
            if active_only:
                statement = statement.where(Business.is_active == True)
            businesses = session.exec(statement).all()
            return list(businesses)
    except Exception as e:
        logger.error(f"Failed to list businesses: {e}")
        return []


# ============================================================================
# Customer CRUD Operations
# ============================================================================

def create_customer(whatsapp_number: str, full_name: Optional[str] = None) -> Optional[Customer]:
    """Create a new customer."""
    try:
        with get_db_session() as session:
            customer = Customer(
                whatsapp_number=whatsapp_number,
                full_name=full_name
            )
            session.add(customer)
            session.commit()
            session.refresh(customer)
            logger.info(f"Created customer: {whatsapp_number} (ID: {customer.id})")
            return customer
    except Exception as e:
        logger.error(f"Failed to create customer: {e}")
        return None


def get_customer_by_id(customer_id: int) -> Optional[Customer]:
    """Get customer by ID."""
    try:
        with get_db_session() as session:
            customer = session.get(Customer, customer_id)
            return customer
    except Exception as e:
        logger.error(f"Failed to get customer by ID {customer_id}: {e}")
        return None


def get_customer_by_whatsapp(whatsapp_number: str) -> Optional[Customer]:
    """Get customer by WhatsApp number."""
    try:
        with get_db_session() as session:
            statement = select(Customer).where(Customer.whatsapp_number == whatsapp_number)
            customer = session.exec(statement).first()
            return customer
    except Exception as e:
        logger.error(f"Failed to get customer by WhatsApp number {whatsapp_number}: {e}")
        return None


def get_or_create_customer(whatsapp_number: str, full_name: Optional[str] = None) -> Optional[Customer]:
    """Get existing customer or create new one."""
    customer = get_customer_by_whatsapp(whatsapp_number)
    if customer:
        if full_name and not customer.full_name and customer.id:
            customer = update_customer(customer.id, full_name=full_name)
        return customer
    return create_customer(whatsapp_number, full_name)


def update_customer(customer_id: int, **kwargs) -> Optional[Customer]:
    """Update customer information."""
    try:
        with get_db_session() as session:
            customer = session.get(Customer, customer_id)
            if not customer:
                logger.warning(f"Customer with ID {customer_id} not found")
                return None
            
            for key, value in kwargs.items():
                if hasattr(customer, key):
                    setattr(customer, key, value)
            
            session.add(customer)
            session.commit()
            session.refresh(customer)
            logger.info(f"Updated customer ID {customer_id}")
            return customer
    except Exception as e:
        logger.error(f"Failed to update customer {customer_id}: {e}")
        return None


# ============================================================================
# Product CRUD Operations
# ============================================================================

def create_product(
    business_id: int,
    name: str,
    price: float,
    description: Optional[str] = None,
    stock: int = 0,
    currency: str = "NGN"
) -> Optional[Product]:
    """Create a new product."""
    try:
        with get_db_session() as session:
            product = Product(
                business_id=business_id,
                name=name,
                price=price,
                description=description,
                stock=stock,
                currency=currency
            )
            session.add(product)
            session.commit()
            session.refresh(product)
            logger.info(f"Created product: {product.name} (ID: {product.id})")
            return product
    except Exception as e:
        logger.error(f"Failed to create product: {e}")
        return None


def get_product_by_id(product_id: int) -> Optional[Product]:
    """Get product by ID."""
    try:
        with get_db_session() as session:
            product = session.get(Product, product_id)
            return product
    except Exception as e:
        logger.error(f"Failed to get product by ID {product_id}: {e}")
        return None


def list_products_by_business(business_id: int, active_only: bool = True) -> List[Product]:
    """List all products for a business."""
    try:
        with get_db_session() as session:
            statement = select(Product).where(Product.business_id == business_id)
            if active_only:
                statement = statement.where(Product.is_active == True)
            products = session.exec(statement).all()
            return list(products)
    except Exception as e:
        logger.error(f"Failed to list products for business {business_id}: {e}")
        return []


def search_products(business_id: int, query: str, active_only: bool = True) -> List[Product]:
    """Search products by name or description."""
    try:
        with get_db_session() as session:
            statement = select(Product).where(Product.business_id == business_id)
            if active_only:
                statement = statement.where(Product.is_active == True)
            
            # Simple text search (can be enhanced with full-text search)
            statement = statement.where(
                Product.name.contains(query) | 
                (Product.description.is_not(None) & Product.description.contains(query))
            )
            products = session.exec(statement).all()
            return list(products)
    except Exception as e:
        logger.error(f"Failed to search products: {e}")
        return []


def update_product(product_id: int, **kwargs) -> Optional[Product]:
    """Update product information."""
    try:
        with get_db_session() as session:
            product = session.get(Product, product_id)
            if not product:
                logger.warning(f"Product with ID {product_id} not found")
                return None
            
            for key, value in kwargs.items():
                if hasattr(product, key):
                    setattr(product, key, value)
            
            session.add(product)
            session.commit()
            session.refresh(product)
            logger.info(f"Updated product ID {product_id}")
            return product
    except Exception as e:
        logger.error(f"Failed to update product {product_id}: {e}")
        return None


def update_product_stock(product_id: int, quantity_change: int) -> Optional[Product]:
    """Update product stock (can be positive or negative)."""
    try:
        with get_db_session() as session:
            product = session.get(Product, product_id)
            if not product:
                logger.warning(f"Product with ID {product_id} not found")
                return None
            
            new_stock = product.stock + quantity_change
            if new_stock < 0:
                logger.warning(f"Insufficient stock for product {product_id}. Current: {product.stock}, Requested: {abs(quantity_change)}")
                return None
            
            product.stock = new_stock
            session.add(product)
            session.commit()
            session.refresh(product)
            logger.info(f"Updated stock for product {product_id}: {product.stock}")
            return product
    except Exception as e:
        logger.error(f"Failed to update product stock {product_id}: {e}")
        return None


# ============================================================================
# Order CRUD Operations
# ============================================================================

def create_order(
    business_id: int,
    customer_id: int,
    status: str = "pending",
    items: Optional[List[Dict[str, Any]]] = None
) -> Optional[Order]:
    """Create a new order with optional items."""
    try:
        with get_db_session() as session:
            order = Order(
                business_id=business_id,
                customer_id=customer_id,
                status=status,
                total_amount=0.0
            )
            session.add(order)
            session.flush()  # Get the order ID
            if not order.id:
                raise ValueError("Failed to get order ID after flush")
            
            total_amount = 0.0
            
            # Add order items if provided
            if items:
                for item_data in items:
                    product = session.get(Product, item_data["product_id"])
                    if not product:
                        logger.warning(f"Product {item_data['product_id']} not found")
                        continue
                    
                    order_item = OrderItem(
                        order_id=order.id,
                        product_id=item_data["product_id"],
                        quantity=item_data["quantity"],
                        price=item_data.get("price", product.price)
                    )
                    session.add(order_item)
                    total_amount += order_item.price * order_item.quantity
            
            order.total_amount = total_amount
            session.commit()
            session.refresh(order)
            logger.info(f"Created order ID {order.id} for customer {customer_id}")
            return order
    except Exception as e:
        logger.error(f"Failed to create order: {e}")
        return None


def get_order_by_id(order_id: int) -> Optional[Order]:
    """Get order by ID with all relationships."""
    try:
        with get_db_session() as session:
            order = session.get(Order, order_id)
            if order:
                # Load relationships
                session.refresh(order, ["items", "payment", "delivery", "customer", "business"])
            return order
    except Exception as e:
        logger.error(f"Failed to get order by ID {order_id}: {e}")
        return None


def list_orders_by_customer(customer_id: int, limit: int = 50) -> List[Order]:
    """List orders for a customer."""
    try:
        with get_db_session() as session:
            statement = select(Order).where(Order.customer_id == customer_id).order_by(desc(Order.created_at)).limit(limit)
            orders = session.exec(statement).all()
            return list(orders)
    except Exception as e:
        logger.error(f"Failed to list orders for customer {customer_id}: {e}")
        return []


def list_orders_by_business(business_id: int, status: Optional[str] = None, limit: int = 100) -> List[Order]:
    """List orders for a business."""
    try:
        with get_db_session() as session:
            statement = select(Order).where(Order.business_id == business_id)
            if status:
                statement = statement.where(Order.status == status)
            statement = statement.order_by(desc(Order.created_at)).limit(limit)
            orders = session.exec(statement).all()
            return list(orders)
    except Exception as e:
        logger.error(f"Failed to list orders for business {business_id}: {e}")
        return []


def update_order_status(order_id: int, status: str) -> Optional[Order]:
    """Update order status."""
    try:
        with get_db_session() as session:
            order = session.get(Order, order_id)
            if not order:
                logger.warning(f"Order with ID {order_id} not found")
                return None
            
            order.status = status
            order.updated_at = datetime.now(timezone.utc)
            session.add(order)
            session.commit()
            session.refresh(order)
            logger.info(f"Updated order {order_id} status to {status}")
            return order
    except Exception as e:
        logger.error(f"Failed to update order status {order_id}: {e}")
        return None


def add_order_item(order_id: int, product_id: int, quantity: int, price: Optional[float] = None) -> Optional[OrderItem]:
    """Add an item to an existing order."""
    try:
        with get_db_session() as session:
            order = session.get(Order, order_id)
            product = session.get(Product, product_id)
            
            if not order or not product:
                logger.warning(f"Order {order_id} or Product {product_id} not found")
                return None
            
            item_price = price or product.price
            order_item = OrderItem(
                order_id=order_id,
                product_id=product_id,
                quantity=quantity,
                price=item_price
            )
            session.add(order_item)
            
            # Update order total
            order.total_amount += item_price * quantity
            order.updated_at = datetime.now(timezone.utc)
            session.add(order)
            
            session.commit()
            session.refresh(order_item)
            logger.info(f"Added item to order {order_id}: Product {product_id}, Qty {quantity}")
            return order_item
    except Exception as e:
        logger.error(f"Failed to add item to order {order_id}: {e}")
        return None


# ============================================================================
# Payment CRUD Operations
# ============================================================================

def create_payment(order_id: int, amount: float, provider: str, status: str = "pending") -> Optional[Payment]:
    """Create a payment record for an order."""
    try:
        with get_db_session() as session:
            payment = Payment(
                order_id=order_id,
                amount=amount,
                provider=provider,
                status=status
            )
            session.add(payment)
            session.commit()
            session.refresh(payment)
            logger.info(f"Created payment record for order {order_id}")
            return payment
    except Exception as e:
        logger.error(f"Failed to create payment for order {order_id}: {e}")
        return None


def update_payment_status(payment_id: int, status: str, transaction_ref: Optional[str] = None) -> Optional[Payment]:
    """Update payment status."""
    try:
        with get_db_session() as session:
            payment = session.get(Payment, payment_id)
            if not payment:
                logger.warning(f"Payment with ID {payment_id} not found")
                return None
            
            payment.status = status
            if transaction_ref:
                payment.transaction_ref = transaction_ref
            if status == "verified":
                payment.verified_at = datetime.now(timezone.utc)
            
            session.add(payment)
            session.commit()
            session.refresh(payment)
            logger.info(f"Updated payment {payment_id} status to {status}")
            return payment
    except Exception as e:
        logger.error(f"Failed to update payment status {payment_id}: {e}")
        return None


# ============================================================================
# Delivery CRUD Operations
# ============================================================================

def create_delivery(order_id: int, address: str, status: str = "pending") -> Optional[Delivery]:
    """Create a delivery record for an order."""
    try:
        with get_db_session() as session:
            delivery = Delivery(
                order_id=order_id,
                address=address,
                status=status
            )
            session.add(delivery)
            session.commit()
            session.refresh(delivery)
            logger.info(f"Created delivery record for order {order_id}")
            return delivery
    except Exception as e:
        logger.error(f"Failed to create delivery for order {order_id}: {e}")
        return None


def update_delivery_status(delivery_id: int, status: str, tracking_info: Optional[str] = None) -> Optional[Delivery]:
    """Update delivery status."""
    try:
        with get_db_session() as session:
            delivery = session.get(Delivery, delivery_id)
            if not delivery:
                logger.warning(f"Delivery with ID {delivery_id} not found")
                return None
            
            delivery.status = status
            if tracking_info:
                delivery.tracking_info = tracking_info
            
            session.add(delivery)
            session.commit()
            session.refresh(delivery)
            logger.info(f"Updated delivery {delivery_id} status to {status}")
            return delivery
    except Exception as e:
        logger.error(f"Failed to update delivery status {delivery_id}: {e}")
        return None