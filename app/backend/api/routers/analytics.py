"""
Analytics API endpoints
Business and user analytics
"""
from fastapi import APIRouter
from typing import Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
from backend.db.database import get_db
from backend.db.models import Transaction, Order, User, Business
from sqlalchemy import func, and_

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsRequest(BaseModel):
    """Analytics request"""
    user_id: Optional[str] = None
    business_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    api_key: Optional[str] = None


@router.post("/business")
async def business_analytics(request: AnalyticsRequest):
    """
    Get business analytics and insights.
    Provides performance metrics, sales data, and recommendations.
    """
    if not request.business_id:
        return {"error": "business_id is required"}
    
    with get_db() as db:
        # Get sales data
        sales_query = db.query(
            func.sum(Transaction.amount).label("total_sales"),
            func.count(Transaction.id).label("total_transactions"),
            func.avg(Transaction.amount).label("avg_transaction_value")
        ).filter(
            Transaction.business_id == request.business_id,
            Transaction.payment_status == "verified"
        )
        
        if request.start_date:
            sales_query = sales_query.filter(Transaction.date >= request.start_date)
        if request.end_date:
            sales_query = sales_query.filter(Transaction.date <= request.end_date)
        
        sales_data = sales_query.first()
        
        # Get order statistics
        orders_query = db.query(
            func.count(Order.id).label("total_orders"),
            func.sum(Order.total_amount).label("total_revenue")
        ).filter(Order.business_id == request.business_id)
        
        orders_data = orders_query.first()
        
        # Get top products
        top_products = db.query(
            func.count(Order.id).label("order_count")
        ).join(Order).filter(
            Order.business_id == request.business_id
        ).group_by(Order.id).limit(5).all()
    
    return {
        "business_id": request.business_id,
        "sales": {
            "total_sales": float(sales_data.total_sales or 0),
            "total_transactions": sales_data.total_transactions or 0,
            "average_transaction_value": float(sales_data.avg_transaction_value or 0)
        },
        "orders": {
            "total_orders": orders_data.total_orders or 0,
            "total_revenue": float(orders_data.total_revenue or 0)
        },
        "insights": [
            "Consider running promotions on slow-moving products",
            "Peak sales hours: 10 AM - 2 PM"
        ]
    }


@router.post("/user")
async def user_analytics(request: AnalyticsRequest):
    """
    Get user analytics and spending habits.
    Provides purchase history, preferences, and product recommendations.
    """
    if not request.user_id:
        return {"error": "user_id is required"}
    
    with get_db() as db:
        # Get user purchase history
        transactions = db.query(Transaction).filter(
            Transaction.user_id == request.user_id,
            Transaction.payment_status == "verified"
        ).all()
        
        total_spent = sum(t.amount for t in transactions)
        purchase_count = len(transactions)
        avg_order_value = total_spent / purchase_count if purchase_count > 0 else 0
        
        # Get orders with metadata
        orders = db.query(Order).filter(Order.user_id == request.user_id).all()
        
        # Calculate spending habits
        spending_by_month = {}
        spending_by_category = {}
        
        for order in orders:
            # Monthly spending
            if order.date_created:
                month_key = order.date_created.strftime("%Y-%m")
                spending_by_month[month_key] = spending_by_month.get(month_key, 0) + order.total_amount
            
            # Category spending (from metadata)
            if order.metadata and isinstance(order.metadata, dict):
                category = order.metadata.get("category", "uncategorized")
                spending_by_category[category] = spending_by_category.get(category, 0) + order.total_amount
        
        # Get recent purchases
        recent_purchases = [
            {
                "order_id": str(order.id),
                "order_number": order.order_number if hasattr(order, 'order_number') else None,
                "amount": order.total_amount,
                "status": order.status if hasattr(order, 'status') else None,
                "date": order.date_created.isoformat() if order.date_created else None
            }
            for order in sorted(orders, key=lambda x: x.date_created if x.date_created else datetime.min, reverse=True)[:5]
        ]
        
        # Determine spending pattern
        spending_pattern = "moderate"
        if purchase_count > 0:
            if avg_order_value > 500:
                spending_pattern = "high_value"
            elif avg_order_value < 100:
                spending_pattern = "budget_conscious"
            
            if purchase_count > 10:
                spending_pattern += "_frequent"
            elif purchase_count < 3:
                spending_pattern += "_occasional"
        
        # Generate recommendations based on spending habits
        recommendations = []
        if purchase_count == 0:
            recommendations = [
                "Start exploring our product catalog",
                "Check out our featured products",
                "Sign up for exclusive deals"
            ]
        else:
            top_category = max(spending_by_category.items(), key=lambda x: x[1])[0] if spending_by_category else None
            if top_category:
                recommendations.append(f"Based on your preferences, you might like more {top_category} products")
            
            if avg_order_value < 200:
                recommendations.append("Consider bundling products for better value")
            
            if purchase_count > 5:
                recommendations.append("You're a valued customer! Check out our loyalty rewards")
            
            recommendations.append("Browse our new arrivals and trending products")
    
    return {
        "user_id": request.user_id,
        "spending_habits": {
            "total_spent": float(total_spent),
            "purchase_count": purchase_count,
            "average_order_value": float(avg_order_value),
            "spending_pattern": spending_pattern,
            "spending_by_month": spending_by_month,
            "spending_by_category": spending_by_category,
            "favorite_category": max(spending_by_category.items(), key=lambda x: x[1])[0] if spending_by_category else None
        },
        "recent_purchases": recent_purchases,
        "recommendations": recommendations,
        "insights": [
            f"Average order value: ${avg_order_value:.2f}",
            f"Total purchases: {purchase_count}",
            f"Most active month: {max(spending_by_month.items(), key=lambda x: x[1])[0] if spending_by_month else 'N/A'}"
        ]
    }

