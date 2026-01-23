from sqlalchemy import or_
# from sqlalchemy.orm import sessionmaker
from .models import Product, Business, Transaction #, engine
from .database import engine, Base, get_db 
from typing import List
from sqlalchemy.inspection import inspect
from sqlalchemy import text
from sqlalchemy import or_, and_
from typing import List
from sqlalchemy.exc import ProgrammingError

Base.metadata.create_all(bind=engine)

## POSTGRES DATABASE FUNCTIONS


async def get_products(
    name: str = None,
    category: str = None,
    min_price: float = None,
    max_price: float = None,
    **kwargs
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

        # if category:
        #     products_query = products_query.filter(Product.product_category == category)

        if min_price is not None:
            products_query = products_query.filter(Product.price >= min_price)

        if max_price is not None:
            products_query = products_query.filter(Product.price <= max_price)

        # Dynamically add filters based on kwargs
        # for key, value in kwargs.items():
        #     column_attr = getattr(Product, key, None)
        #     if column_attr is not None:
        #         if isinstance(value, str):
        #             value = f"%{value}%"
        #             products_query = products_query.filter(column_attr.ilike(value))
        #         else:
        #             products_query = products_query.filter(column_attr == value)

        products = products_query.all()

        products = [product.to_dict() for product in products]

    return products


# async def get_products(
#     name: str = None,
#     category: str = None,
#     min_price: float = None,
#     max_price: float = None,
#     **kwargs
# ):
#     with get_db() as db:
#         products_query = db.query(Product)

#         if name:
#             search_term = f"%{name}%"
#             products_query = products_query.filter(
#                 or_(
#                     Product.product_name.ilike(search_term),
#                     Product.product_description.ilike(search_term),
#                     Product.tags.ilike(search_term),
#                 )
#             )

#         if category:
#             products_query = products_query.filter(Product.product_category == category)

#         if min_price is not None:
#             products_query = products_query.filter(Product.price >= min_price)

#         if max_price is not None:
#             products_query = products_query.filter(Product.price <= max_price)

#         products = products_query.all()

#         products = [product.to_dict() for product in products]

#     return products

#Business: 
async def get_business_info(
    vendor_id,
    
):  
    # vendor_id = f"%{vendor_id}%"
    print(vendor_id)
    with get_db() as db:
        business_query = db.query(Business)
        
        business_query = business_query.filter(
            or_(
                Business.ig_page.ilike(vendor_id),
                Business.facebook_page.ilike(vendor_id),
                Business.twitter_page.ilike(vendor_id),
                Business.phone_number.ilike(vendor_id),
                Business.email.ilike(vendor_id),
                Business.tiktok.ilike(vendor_id)
            )
        )
        # business_query = business_query.filter(Business.tiktok == "2347000000004")
        # business_query = business_query.filter(Business.phone_number == vendor_id)
      
        business_information =  business_query.all()
        business_information = [business.to_dict() for business in business_information]

    return business_information[0]


def to_dict(db_object):
    # Assuming `db_object` is your SQLAlchemy ORM object
    dict_obj = {c.key: getattr(db_object, c.key) for c in inspect(db_object).mapper.column_attrs}
    return dict_obj


def search_products(query: str, limit: int = 10, offset: int = 0) -> List[Product]:
    with get_db() as db:
        try:
            formatted_query = " | ".join(query.split())  # Use OR instead of AND
            
            sql_query = text("""
                SELECT *
                FROM products
                WHERE ts_vector @@ to_tsquery('english', :query)
                ORDER BY ts_rank(ts_vector, to_tsquery('english', :query)) DESC
                LIMIT :limit OFFSET :offset
            """)
            
            results = db.execute(sql_query, {
                "query": formatted_query,
                "limit": limit,
                "offset": offset
            })
            
            # Get the column names of the Product model
            product_columns = set(inspect(Product).columns.keys())
            
            # Filter out any columns that aren't in the Product model
            products = [
                Product(**{k: v for k, v in row._asdict().items() if k in product_columns})
                for row in results
            ]
            
            if not products:
                print("No results found. Checking ts_vector content...")
                check_query = text("""
                    SELECT id, product_name, ts_vector::text
                    FROM products
                    LIMIT 5
                """)
                check_results = db.execute(check_query)
                for row in check_results:
                    print(f"ID: {row.id}, Name: {row.product_name}, ts_vector: {row.ts_vector}")
            
            return products
        except ProgrammingError as e:
            print(f"An error occurred: {str(e)}")
            return []

    
    
    
if __name__ == "__main__":
    # Usage
    search_results = search_products("i want to buy a gaming laptop", limit=15)
    if search_results:
        for product in search_results:
            print(f"Product: {product.product_name}")
            print(f"Description: {product.product_description}")
            print(f"Price: ${product.price}")
            print("---")
    else:
        print("No results found.")
