from sqlalchemy import or_

from models import Product
from database import engine, Base, get_db
from typing import List


Base.metadata.create_all(bind=engine)

## POSTGRES DATABASE FUNCTIONS


async def get_products(
    name: str = None,
    category: str = None,
    min_price: float = None,
    max_price: float = None,
):
    with get_db() as db:
        products_query = db.query(Product)

        if name:
            search_term = f"%{name}%"
            products_query = products_query.filter(
                or_(
                    Product.product_name.ilike(search_term),
                    Product.product_description.ilike(search_term),
                    Product.tags.ilike(search_term),
                )
            )

        if category:
            products_query = products_query.filter(Product.product_category == category)

        if min_price is not None:
            products_query = products_query.filter(Product.price >= min_price)

        if max_price is not None:
            products_query = products_query.filter(Product.price <= max_price)

        products = products_query.all()

        products = [product.to_dict() for product in products]

    return products
