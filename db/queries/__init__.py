"""Database query functions."""

from db.queries.agent import (
    create_agent,
    delete_agent,
    get_agent_by_business_id,
    get_agent_by_id,
    update_agent,
)
from db.queries.business import (
    create_business,
    delete_business,
    get_business_by_id,
    get_business_by_slug,
    get_businesses_by_owner,
    update_business,
)
from db.queries.conversation import (
    create_conversation,
    delete_conversation,
    escalate_conversation,
    get_business_conversations,
    get_conversation_by_id,
    get_customer_conversations,
    update_conversation,
)
from db.queries.customer import (
    add_customer_tags,
    create_customer,
    delete_customer,
    find_customer_by_contact,
    get_business_customers,
    get_customer_by_id,
    update_customer,
)
from db.queries.message import (
    create_message,
    delete_message,
    get_conversation_messages,
    get_message_by_id,
    get_public_messages,
    update_message,
)
from db.queries.product import (
    check_low_stock,
    create_product,
    delete_product,
    get_business_products,
    get_product_by_id,
    get_product_by_sku,
    search_products,
    update_inventory,
    update_product,
)

__all__ = [
    # Agent
    "create_agent",
    "get_agent_by_id",
    "get_agent_by_business_id",
    "update_agent",
    "delete_agent",
    # Business
    "create_business",
    "get_business_by_id",
    "get_business_by_slug",
    "get_businesses_by_owner",
    "update_business",
    "delete_business",
    # Customer
    "create_customer",
    "get_customer_by_id",
    "find_customer_by_contact",
    "get_business_customers",
    "update_customer",
    "add_customer_tags",
    "delete_customer",
    # Conversation
    "create_conversation",
    "get_conversation_by_id",
    "get_customer_conversations",
    "get_business_conversations",
    "update_conversation",
    "escalate_conversation",
    "delete_conversation",
    # Message
    "create_message",
    "get_message_by_id",
    "get_conversation_messages",
    "get_public_messages",
    "update_message",
    "delete_message",
    # Product
    "create_product",
    "get_product_by_id",
    "get_product_by_sku",
    "get_business_products",
    "search_products",
    "update_product",
    "update_inventory",
    "check_low_stock",
    "delete_product",
]
