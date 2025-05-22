import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .database import Base, engine
from .models import (
    Business,
    BusinessChannel,
    BusinessLogisticPartnerSubscription,
    BusinessPaymentPartnerSubscription,
    ChannelPlatformEnum,
    ItemTypeEnum,
    LogisticPartner,
    PaymentPartner,
    PaymentTypeEnum,
    ProductService,
)

## POSTGRES DATABASE FUNCTIONS

# --- Business Functions ---

def create_business(db: Session, name: str, admin_contact_phone_number: str, email: str) -> Business:
    """Creates a new business."""
    new_business = Business(
        name=name,
        admin_contact_phone_number=admin_contact_phone_number,
        email=email
    )
    db.add(new_business)
    # db.flush() # Optional: to get ID before commit if needed within the session block
    return new_business

def get_business_by_id(db: Session, business_id: uuid.UUID) -> Business | None:
    """Retrieves a business by its ID."""
    return db.query(Business).filter(Business.id == business_id).first()

def get_business_by_admin_phone(db: Session, phone_number: str) -> Business | None:
    """Retrieves a business by its admin contact phone number."""
    return db.query(Business).filter(Business.admin_contact_phone_number == phone_number).first()

def get_business_by_email(db: Session, email: str) -> Business | None:
    """Retrieves a business by its email address."""
    return db.query(Business).filter(Business.email == email).first()

def list_businesses(db: Session, skip: int = 0, limit: int = 100) -> list[Business]:
    """Lists all businesses with pagination."""
    return db.query(Business).offset(skip).limit(limit).all()

def update_business_details(db: Session, business_id: uuid.UUID, name: str = None, admin_contact_phone_number: str = None, email: str = None) -> Business | None:
    """Updates a business's details."""
    business = get_business_by_id(db, business_id)
    if business:
        if name is not None:
            business.name = name
        if admin_contact_phone_number is not None:
            business.admin_contact_phone_number = admin_contact_phone_number
        if email is not None:
            business.email = email
    return business

# --- BusinessChannel Functions ---

def add_business_channel(db: Session, business_id: uuid.UUID, platform: ChannelPlatformEnum,
                         platform_identifier: str, api_credentials: str = None) -> BusinessChannel | None:
    """Adds a new channel to a business."""
    business = get_business_by_id(db, business_id)
    if not business:
        # Consider raising an error or a specific exception for business not found
        return None

    new_channel = BusinessChannel(
        business_id=business_id,
        platform=platform,
        platform_identifier=platform_identifier,
        api_credentials=api_credentials # IMPORTANT: Ensure this is securely handled/encrypted if provided
    )
    db.add(new_channel)
    return new_channel

def get_business_channel_by_platform_identifier(db: Session, platform: ChannelPlatformEnum, platform_identifier: str) -> BusinessChannel | None:
    """Retrieves a business channel by its platform and platform identifier."""
    return db.query(BusinessChannel).filter(
        BusinessChannel.platform == platform,
        BusinessChannel.platform_identifier == platform_identifier
    ).first()

def get_business_channels_for_business(db: Session, business_id: uuid.UUID) -> list[BusinessChannel]:
    """Retrieves all channels for a given business."""
    return db.query(BusinessChannel).filter(BusinessChannel.business_id == business_id).all()

def update_business_channel_credentials(db: Session, channel_id: uuid.UUID, api_credentials: str) -> BusinessChannel | None:
    """Updates the API credentials for a business channel."""
    channel = db.query(BusinessChannel).filter(BusinessChannel.id == channel_id).first()
    if channel:
        channel.api_credentials = api_credentials # IMPORTANT: Remember to encrypt sensitive credentials
        channel.updated_at = func.now()
    return channel

def set_business_channel_active_status(db: Session, channel_id: uuid.UUID, is_active: bool) -> BusinessChannel | None:
    """Sets the active status for a business channel."""
    channel = db.query(BusinessChannel).filter(BusinessChannel.id == channel_id).first()
    if channel:
        channel.is_active = is_active
        channel.updated_at = func.now()
    return channel

# --- Product/Service Functions ---

def add_product_service(db: Session, business_id: uuid.UUID, name: str, item_type: ItemTypeEnum,
                        description: str = None, base_price: float = None, currency: str = "USD",
                        attributes: dict = None) -> ProductService | None:
    """Adds a new product or service for a business."""
    business = get_business_by_id(db, business_id)
    if not business:
        return None

    product = ProductService(
        business_id=business_id,
        name=name,
        item_type=item_type,
        description=description,
        base_price=base_price,
        currency=currency,
        attributes=attributes
    )
    db.add(product)
    return product

def get_product_service_by_id(db: Session, product_id: uuid.UUID) -> ProductService | None:
    """Retrieves a product/service by its ID."""
    return db.query(ProductService).filter(ProductService.id == product_id).first()

def get_products_services_by_business(db: Session, business_id: uuid.UUID, item_type: ItemTypeEnum = None, is_active: bool = True) -> list[ProductService]:
    """Retrieves products/services for a given business, optionally filtered by item type and active status."""
    query = db.query(ProductService).filter(ProductService.business_id == business_id)
    if item_type:
        query = query.filter(ProductService.item_type == item_type)
    # Filter by active status (True for active, False for inactive)
    query = query.filter(ProductService.is_active == is_active)
    return query.all()

def search_products_services_by_name(db: Session, business_id: uuid.UUID, search_term: str, is_active: bool = True) -> list[ProductService]:
    """Searches products/services by name for a specific business."""
    query = db.query(ProductService).filter(
        ProductService.business_id == business_id,
        ProductService.name.ilike(f"%{search_term}%")
    )
    query = query.filter(ProductService.is_active == is_active)
    return query.all()

def update_product_service(db: Session, product_id: uuid.UUID, name: str = None, description: str = None,
                           base_price: float = None, currency: str = None, attributes: dict = None,
                           is_active: bool = None) -> ProductService | None:
    """Updates details of a product or service."""
    product = get_product_service_by_id(db, product_id)
    if product:
        if name is not None: product.name = name
        if description is not None: product.description = description
        if base_price is not None: product.base_price = base_price
        if currency is not None: product.currency = currency
        if attributes is not None: product.attributes = attributes
        if is_active is not None: product.is_active = is_active
        product.updated_at = func.now()
    return product

# --- LogisticPartner Functions ---

def create_logistic_partner(db: Session, name: str, contact_email: str = None, contact_phone: str = None,
                            api_endpoint: str = None, api_key: str = None, notes: str = None,
                            linked_business_id: uuid.UUID = None) -> LogisticPartner:
    """Creates a new logistic partner."""
    partner = LogisticPartner(
        name=name, contact_email=contact_email, contact_phone=contact_phone,
        api_endpoint=api_endpoint, api_key=api_key, # IMPORTANT: Encrypt api_key before storing
        notes=notes,
        linked_business_id=linked_business_id
    )
    db.add(partner)
    return partner

def get_logistic_partner_by_id(db: Session, partner_id: uuid.UUID) -> LogisticPartner | None:
    """Retrieves a logistic partner by ID."""
    return db.query(LogisticPartner).filter(LogisticPartner.id == partner_id).first()

def list_logistic_partners(db: Session, is_active: bool = True) -> list[LogisticPartner]:
    """Lists all logistic partners, filtered by active status."""
    query = db.query(LogisticPartner)
    query = query.filter(LogisticPartner.is_active == is_active)
    return query.all()

# --- BusinessLogisticPartnerSubscription Functions ---

def subscribe_business_to_logistic_partner(db: Session, business_id: uuid.UUID, logistic_partner_id: uuid.UUID,
                                           configuration_details: dict = None) -> BusinessLogisticPartnerSubscription | None:
    """Subscribes a business to a logistic partner."""
    # Check if subscription already exists to prevent duplicates if desired
    existing_subscription = db.query(BusinessLogisticPartnerSubscription).filter_by(
        business_id=business_id, logistic_partner_id=logistic_partner_id
    ).first()
    if existing_subscription:
        # Optionally update existing or raise error if re-subscribing with different details is not desired
        existing_subscription.configuration_details = configuration_details
        existing_subscription.is_active = True # Reactivate if it was inactive
        return existing_subscription

    subscription = BusinessLogisticPartnerSubscription(
        business_id=business_id,
        logistic_partner_id=logistic_partner_id,
        configuration_details=configuration_details
    )
    db.add(subscription)
    return subscription

def get_business_logistic_subscriptions(db: Session, business_id: uuid.UUID, is_active: bool = True) -> list[BusinessLogisticPartnerSubscription]:
    """Retrieves logistic partner subscriptions for a business, filtered by active status."""
    query = db.query(BusinessLogisticPartnerSubscription).filter(BusinessLogisticPartnerSubscription.business_id == business_id)
    query = query.filter(BusinessLogisticPartnerSubscription.is_active == is_active)
    return query.options(joinedload(BusinessLogisticPartnerSubscription.logistic_partner)).all() # Eager load partner details

def unsubscribe_business_from_logistic_partner(db: Session, business_id: uuid.UUID, logistic_partner_id: uuid.UUID) -> bool:
    """Deactivates a business's subscription to a logistic partner."""
    subscription = db.query(BusinessLogisticPartnerSubscription).filter_by(
        business_id=business_id, logistic_partner_id=logistic_partner_id
    ).first()
    if subscription:
        subscription.is_active = False
        # To permanently delete, uncomment below:
        # db.delete(subscription)
        return True
    return False

# --- PaymentPartner Functions ---

def create_payment_partner(db: Session, name: str, type: PaymentTypeEnum,
                           configuration_schema: dict = None, webhook_secret: str = None) -> PaymentPartner:
    """Creates a new payment partner (e.g., 'Stripe', 'Manual Bank Transfer Setup')."""
    partner = PaymentPartner(
        name=name, type=type, configuration_schema=configuration_schema,
        webhook_secret=webhook_secret # IMPORTANT: Encrypt webhook_secret before storing
    )
    db.add(partner)
    return partner

def get_payment_partner_by_id(db: Session, partner_id: uuid.UUID) -> PaymentPartner | None:
    """Retrieves a payment partner by ID."""
    return db.query(PaymentPartner).filter(PaymentPartner.id == partner_id).first()

def get_payment_partner_by_name(db: Session, name: str) -> PaymentPartner | None:
    """Retrieves a payment partner by name."""
    return db.query(PaymentPartner).filter(PaymentPartner.name == name).first()

def list_payment_partners(db: Session, type: PaymentTypeEnum = None, is_active: bool = True) -> list[PaymentPartner]:
    """Lists payment partners, optionally filtered by type and active status."""
    query = db.query(PaymentPartner)
    if type:
        query = query.filter(PaymentPartner.type == type)
    query = query.filter(PaymentPartner.is_active == is_active)
    return query.all()

# --- BusinessPaymentPartnerSubscription Functions ---

def subscribe_business_to_payment_partner(db: Session, business_id: uuid.UUID, payment_partner_id: uuid.UUID,
                                          configuration_details: dict) -> BusinessPaymentPartnerSubscription | None:
    """
    Subscribes a business to a payment partner.
    For 'manual_bank_transfer', configuration_details would hold bank account info.
    """
    # Check if subscription already exists
    existing_subscription = db.query(BusinessPaymentPartnerSubscription).filter_by(
        business_id=business_id, payment_partner_id=payment_partner_id
    ).first()
    if existing_subscription:
        existing_subscription.configuration_details = configuration_details # Update details
        existing_subscription.is_active = True # Reactivate if previously inactive
        return existing_subscription

    subscription = BusinessPaymentPartnerSubscription(
        business_id=business_id,
        payment_partner_id=payment_partner_id,
        configuration_details=configuration_details # IMPORTANT: Encrypt sensitive details if necessary
    )
    db.add(subscription)
    return subscription

def get_business_payment_subscriptions(db: Session, business_id: uuid.UUID, is_active: bool = True) -> list[BusinessPaymentPartnerSubscription]:
    """Retrieves payment partner subscriptions for a business, filtered by active status."""
    query = db.query(BusinessPaymentPartnerSubscription).filter(BusinessPaymentPartnerSubscription.business_id == business_id)
    query = query.filter(BusinessPaymentPartnerSubscription.is_active == is_active)
    return query.options(joinedload(BusinessPaymentPartnerSubscription.payment_partner)).all() # Eager load partner details

def get_manual_bank_transfer_details_for_business(db: Session, business_id: uuid.UUID) -> BusinessPaymentPartnerSubscription | None:
    """
    Crucial for V1: Retrieves the active manual bank transfer configuration for a business.
    Assumes there's only one active manual bank transfer setup per business, or picks the first one.
    """
    return db.query(BusinessPaymentPartnerSubscription)\
        .join(PaymentPartner, BusinessPaymentPartnerSubscription.payment_partner_id == PaymentPartner.id)\
        .filter(
            BusinessPaymentPartnerSubscription.business_id == business_id,
            BusinessPaymentPartnerSubscription.is_active == True,
            PaymentPartner.type == PaymentTypeEnum.manual_bank_transfer,
            PaymentPartner.is_active == True
        ).first()

def update_payment_subscription_config(db: Session, subscription_id: uuid.UUID, configuration_details: dict) -> BusinessPaymentPartnerSubscription | None:
    """Updates the configuration details for a specific payment subscription."""
    subscription = db.query(BusinessPaymentPartnerSubscription).filter(BusinessPaymentPartnerSubscription.id == subscription_id).first()
    if subscription:
        subscription.configuration_details = configuration_details # IMPORTANT: Encrypt sensitive details if necessary
        subscription.updated_at = func.now() # Assumes BusinessPaymentPartnerSubscription has an 'updated_at' field
    return subscription

def unsubscribe_business_from_payment_partner(db: Session, business_id: uuid.UUID, payment_partner_id: uuid.UUID) -> bool:
    """Deactivates a business's subscription to a payment partner."""
    subscription = db.query(BusinessPaymentPartnerSubscription).filter_by(
        business_id=business_id, payment_partner_id=payment_partner_id
    ).first()
    if subscription:
        subscription.is_active = False
        # To permanently delete, uncomment below:
        # db.delete(subscription)
        return True
    return False
