"""
Prepopulate Supabase with required tables and initial data
"""
import asyncio
from sqlalchemy import create_engine, text
from backend.db.models import Base, User, Business, Product, Service
from backend.db.database import engine, get_db
from backend.config import config
import uuid
from faker import Faker

fake = Faker()


def create_tables():
    """Create all database tables"""
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully")


def prepopulate_users():
    """Create dummy users"""
    with get_db() as db:
        users = []
        for i in range(10):
            user = User(
                id=uuid.uuid4(),
                phone_number=fake.phone_number(),
                email=fake.email(),
                full_name=fake.name(),
                address=fake.address(),
                city=fake.city(),
                state=fake.state(),
                country=fake.country()
            )
            users.append(user)
            db.add(user)
        db.commit()
        print(f"Created {len(users)} users")


def prepopulate_businesses():
    """Create dummy businesses"""
    with get_db() as db:
        businesses_data = [
            {"name": "Donrey Fashion", "type": "vendor", "tier": "platinum"},
            {"name": "Junae Cosmetics", "type": "vendor", "tier": "gold"},
            {"name": "Manny Gadgets", "type": "vendor", "tier": "platinum"},
            {"name": "Tesla Tech", "type": "vendor", "tier": "gold"},
            {"name": "Kemi Surprises", "type": "vendor", "tier": "free"},
            {"name": "Fast Delivery Co", "type": "logistics", "tier": "platinum"},
            {"name": "Express Logistics", "type": "logistics", "tier": "gold"},
        ]
        
        businesses = []
        for biz_data in businesses_data:
            business = Business(
                id=uuid.uuid4(),
                business_name=biz_data["name"],
                business_type=biz_data["type"],
                tier=biz_data["tier"],
                email=fake.email(),
                phone_number=fake.phone_number(),
                business_description=fake.text(),
                bank_name="Test Bank",
                bank_account_number=fake.bban(),
                bank_account_name=biz_data["name"]
            )
            businesses.append(business)
            db.add(business)
        db.commit()
        print(f"Created {len(businesses)} businesses")


def prepopulate_products():
    """Create dummy products"""
    with get_db() as db:
        # Get businesses
        businesses = db.query(Business).filter(Business.business_type == "vendor").all()
        
        products = []
        for business in businesses:
            for i in range(5):  # 5 products per business
                product = Product(
                    id=uuid.uuid4(),
                    business_id=business.id,
                    product_name=fake.word().capitalize() + " " + fake.word(),
                    product_description=fake.text(),
                    product_category=random.choice(["Electronics", "Fashion", "Cosmetics", "Gadgets"]),
                    price=round(random.uniform(10, 500), 2),
                    items_in_stock=random.randint(0, 100),
                    tags=fake.word() + ", " + fake.word()
                )
                products.append(product)
                db.add(product)
        db.commit()
        print(f"Created {len(products)} products")


if __name__ == "__main__":
    import random
    
    print("Creating tables...")
    create_tables()
    
    print("Prepopulating users...")
    prepopulate_users()
    
    print("Prepopulating businesses...")
    prepopulate_businesses()
    
    print("Prepopulating products...")
    prepopulate_products()
    
    print("Done!")

