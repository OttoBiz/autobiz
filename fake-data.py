import random
from db import Business, Product, Transaction, engine
from faker import Faker
from sqlalchemy.orm import sessionmaker

Session = sessionmaker(bind=engine)
session = Session()
fake = Faker()


# Populate the database with dummy data
def create_dummy_businesses(num_businesses):
    businesses = []
    for _ in range(num_businesses):
        business = Business(
            business_name=fake.company()[:15],
            ig_page=fake.url()[:15],
            facebook_page=fake.url()[:15],
            twitter_page=fake.url()[:15],
            email=fake.email()[:15],
            tiktok=fake.url()[:15],
            website=fake.url()[:15],
            phone_number=fake.phone_number()[:15],
            business_description=fake.text()[:15],
            business_niche=fake.word()[:15],
            business_type=random.choice(['logistics', 'vendor', 'service']),
        )
        businesses.append(business)
    return businesses

def create_dummy_products(businesses, num_products):
    products = []
    for business in businesses:
        for _ in range(num_products):
            product = Product(
                business_id=business.id,
                product_name=fake.word()[:30],
                product_description=fake.text(),
                product_category=fake.word()[:30],
                price=round(random.uniform(10.0, 1000.0), 2),
                items_in_stock=random.randint(1, 100),
                tags=', '.join(fake.words(nb=3)),
            )
            products.append(product)
    return products

def create_dummy_transactions(products, num_transactions):
    transactions = []
    for _ in range(num_transactions):
        product = random.choice(products)
        transaction = Transaction(
            product_id=product.id,
            product_desc=product.product_description,
            business_id=product.business_id,
            payment_status=random.choice(['pending', 'verified']),
            price=product.price,
            item_category=product.product_category,
            items_bought=random.randint(1, 10),
            bot_marketed=fake.boolean(),
        )
        transactions.append(transaction)
    return transactions

def populate_database(num_businesses=10, num_products_per_business=10, num_transactions=50):
    businesses = create_dummy_businesses(num_businesses)
    session.add_all(businesses)
    session.commit()

    products = create_dummy_products(businesses, num_products_per_business)
    session.add_all(products)
    session.commit()

    transactions = create_dummy_transactions(products, num_transactions)
    session.add_all(transactions)
    session.commit()

if __name__ == "__main__":
    populate_database()