"""
Services Module
Handles service-related operations for businesses offering services

NOTE: Services table needs to be created in migrations before these functions work.
"""
from typing import List, Dict, Any, Optional
from backend.db.connection import get_db
from backend.logging_config import get_logger

logger = get_logger(__name__)


async def get_service_by_id(service_id: str) -> Optional[Dict[str, Any]]:
    """Get service by ID"""
    pool = await get_db()
    
    query = """
        SELECT id, business_id, name, description, price, category,
               duration_hours, tags, is_active, created_at, updated_at
        FROM services
        WHERE id = $1::uuid
    """
    
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, service_id)
            return dict(row) if row else None
    except Exception:
        logger.error("get_service_by_id_failed | service_id=%s", service_id, exc_info=True)
        return None


async def get_services_by_business(
    business_id: str,
    category: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get services by business ID"""
    pool = await get_db()
    
    query = """
        SELECT id, business_id, name, description, price, category,
               duration_hours, tags, is_active, created_at, updated_at
        FROM services
        WHERE business_id = $1::uuid AND is_active = true
    """
    params = [business_id]
    param_count = 2
    
    if category:
        query += f" AND category ILIKE ${param_count}"
        params.append(f"%{category}%")
        param_count += 1
    
    query += f" ORDER BY created_at DESC LIMIT {limit}"
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
    except Exception:
        logger.error("get_services_by_business_failed | business_id=%s", business_id, exc_info=True)
        return []


async def search_services(
    query: str,
    business_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Search services by query string"""
    pool = await get_db()
    
    sql_query = """
        SELECT id, business_id, name, description, price, category,
               duration_hours, tags, is_active, created_at, updated_at
        FROM services
        WHERE is_active = true
    """
    params = []
    param_count = 1
    
    if business_id:
        sql_query += f" AND business_id = ${param_count}::uuid"
        params.append(business_id)
        param_count += 1
    
    if category:
        sql_query += f" AND category ILIKE ${param_count}"
        params.append(f"%{category}%")
        param_count += 1
    
    # Search in name, description, and tags
    sql_query += f" AND (name ILIKE ${param_count} OR description ILIKE ${param_count} OR tags ILIKE ${param_count})"
    params.append(f"%{query}%")
    param_count += 1
    
    sql_query += f" ORDER BY created_at DESC LIMIT {limit}"
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql_query, *params)
            return [dict(row) for row in rows]
    except Exception:
        logger.error("search_services_failed | query=%s", query, exc_info=True)
        return []


async def create_service(
    business_id: str,
    service_name: str,
    service_description: str,
    price: float,
    service_category: Optional[str] = None,
    duration_hours: Optional[int] = None,
    tags: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Create a new service"""
    pool = await get_db()
    
    query = """
        INSERT INTO services (business_id, name, description, price, category, duration_hours, tags, is_active)
        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, true)
        RETURNING id, business_id, name, description, price, category, duration_hours, tags, is_active, created_at, updated_at
    """
    
    params = [business_id, service_name, service_description, price, service_category, duration_hours, tags]
    
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return dict(row) if row else None
    except Exception:
        logger.error("create_service_failed | business_id=%s name=%s", business_id, service_name, exc_info=True)
        return None

