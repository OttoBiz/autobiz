"""
Services Module
Handles service-related operations for businesses offering services
"""
from typing import List, Dict, Any, Optional
from backend.db.database import get_db
from backend.db.models import Service, Business
from sqlalchemy import or_


async def get_service_by_id(service_id: str) -> Optional[Dict[str, Any]]:
    """Get service by ID"""
    with get_db() as db:
        service = db.query(Service).filter(Service.id == service_id).first()
        if service:
            return service.to_dict()
    return None


async def get_services_by_business(
    business_id: str,
    category: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get services by business ID"""
    with get_db() as db:
        query = db.query(Service).filter(Service.business_id == business_id)
        if category:
            query = query.filter(Service.service_category == category)
        services = query.limit(limit).all()
        return [s.to_dict() for s in services]


async def search_services(
    query: str,
    business_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Search services by query string"""
    with get_db() as db:
        query_obj = db.query(Service)
        
        if business_id:
            query_obj = query_obj.filter(Service.business_id == business_id)
        
        if category:
            query_obj = query_obj.filter(Service.service_category == category)
        
        # Search in name and description
        search_term = f"%{query}%"
        query_obj = query_obj.filter(
            or_(
                Service.service_name.ilike(search_term),
                Service.service_description.ilike(search_term),
                Service.tags.ilike(search_term)
            )
        )
        
        services = query_obj.limit(limit).all()
        return [s.to_dict() for s in services]


async def create_service(
    business_id: str,
    service_name: str,
    service_description: str,
    price: float,
    service_category: Optional[str] = None,
    duration_hours: Optional[int] = None,
    tags: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new service"""
    with get_db() as db:
        service = Service(
            business_id=business_id,
            service_name=service_name,
            service_description=service_description,
            price=price,
            service_category=service_category,
            duration_hours=duration_hours,
            tags=tags
        )
        db.add(service)
        db.commit()
        db.refresh(service)
        return service.to_dict()

