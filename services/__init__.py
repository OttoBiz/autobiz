"""Services package for WhatsApp AI Assistant."""

from .db import (
    # Connection management
    create_tables,
    get_db_session,
    test_db_connection,
    test_redis_connection,
    
    # Redis session management
    save_memory,
    load_memory,
    delete_memory,
    extend_memory_ttl,
    
    # Business operations
    create_business,
    get_business_by_id,
    get_business_by_whatsapp,
    update_business,
    list_businesses,
    
    # Customer operations
    create_customer,
    get_customer_by_id,
    get_customer_by_whatsapp,
    get_or_create_customer,
    update_customer,
    
    # Product operations
    create_product,
    get_product_by_id,
    list_products_by_business,
    search_products,
    update_product,
    update_product_stock,
    
    # Order operations
    create_order,
    get_order_by_id,
    list_orders_by_customer,
    list_orders_by_business,
    update_order_status,
    add_order_item,
    
    # Payment operations
    create_payment,
    update_payment_status,
    
    # Delivery operations
    create_delivery,
    update_delivery_status,
)

__all__ = [
    # Connection management
    "create_tables",
    "get_db_session", 
    "test_db_connection",
    "test_redis_connection",
    
    # Redis session management
    "save_memory",
    "load_memory",
    "delete_memory",
    "extend_memory_ttl",
    
    # Business operations
    "create_business",
    "get_business_by_id",
    "get_business_by_whatsapp",
    "update_business", 
    "list_businesses",
    
    # Customer operations
    "create_customer",
    "get_customer_by_id",
    "get_customer_by_whatsapp",
    "get_or_create_customer",
    "update_customer",
    
    # Product operations
    "create_product",
    "get_product_by_id",
    "list_products_by_business",
    "search_products",
    "update_product",
    "update_product_stock",
    
    # Order operations
    "create_order",
    "get_order_by_id",
    "list_orders_by_customer",
    "list_orders_by_business",
    "update_order_status",
    "add_order_item",
    
    # Payment operations
    "create_payment",
    "update_payment_status",
    
    # Delivery operations
    "create_delivery",
    "update_delivery_status",
]