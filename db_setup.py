"""Database setup script for WhatsApp AI Assistant."""

# NOTE: This is a temporary setup script for development.
# In production, use proper database migrations with Alembic.

from sqlmodel import create_engine, SQLModel, Session, select
from sqlalchemy import text
from config import settings
from models import (
    Business, Customer, Product, Order,
    OrderItem, Payment, Delivery
)


def create_tables():
    """Create all database tables."""
    print("Creating database tables...")

    try:
        # Create database engine
        engine = create_engine(
            settings.database_url,
            echo=True if settings.debug else False
        )

        # Create all tables
        SQLModel.metadata.create_all(engine)

        print("✅ Database tables created successfully!")
        return engine

    except Exception as e:
        print(f"❌ Error creating database tables: {e}")
        raise


def seed_sample_data(engine):
    """Add sample data for development/testing."""
    print("Adding sample data...")

    try:
        with Session(engine) as session:
            # Check if sample business already exists
            existing_business = session.exec(select(Business).where(
                Business.whatsapp_number == "+1234567890"
            )).first()

            if existing_business:
                print("Sample data already exists, skipping...")
                return

            # Create sample business
            business = Business(
                name="Demo Store",
                whatsapp_number="+1234567890",
                owner_name="John Doe",
                owner_contact="john@demo.com"
            )
            session.add(business)
            session.commit()
            session.refresh(business)

            # Create sample products
            products = [
                Product(
                    business_id=business.id,
                    name="Laptop",
                    description="High-performance laptop",
                    price=999.99,
                    currency="NGN",
                    stock=10
                ),
                Product(
                    business_id=business.id,
                    name="Phone",
                    description="Latest smartphone",
                    price=599.99,
                    currency="NGN",
                    stock=25
                ),
                Product(
                    business_id=business.id,
                    name="Headphones",
                    description="Wireless headphones",
                    price=149.99,
                    currency="NGN",
                    stock=50
                )
            ]

            for product in products:
                session.add(product)

            session.commit()

            print("✅ Sample data added successfully!")
            print(f"   - Business: {business.name}")
            print(f"   - Products: {len(products)} items")

    except Exception as e:
        print(f"❌ Error adding sample data: {e}")
        raise


def test_connection():
    """Test database connection."""
    print("Testing database connection...")

    try:
        engine = create_engine(settings.database_url)

        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 as test"))
            test_value = result.fetchone()[0]

        if test_value == 1:
            print("✅ Database connection successful!")
            return True
        else:
            print("❌ Database connection test failed")
            return False

    except Exception as e:
        print(f"❌ Database connection error: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure PostgreSQL is running")
        print("2. Check your DATABASE_URL in .env file")
        print("3. Verify database credentials")
        print("4. If using Docker: run 'docker-compose up -d postgres'")
        return False


def main():
    """Main setup function."""
    print("🚀 Setting up WhatsApp AI Assistant Database")
    print("=" * 50)

    # Test connection first
    if not test_connection():
        print("\n❌ Setup failed: Cannot connect to database")
        return

    try:
        # Create tables
        engine = create_tables()

        # Add sample data
        seed_sample_data(engine)

        print("\n" + "=" * 50)
        print("🎉 Database setup completed successfully!")
        print("\nNext steps:")
        print("1. Start the application: uv run uvicorn main:app --reload")
        print("2. View database: http://localhost:8080 (if using docker-compose)")
        print("3. Test API: http://localhost:8000")

    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        print("\nPlease check the error messages above and try again.")


if __name__ == "__main__":
    main()
