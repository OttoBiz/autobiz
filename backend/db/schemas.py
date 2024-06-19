import os

from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DB_URL")

# Replace with your actual database connection details
engine = create_engine(DB_URL)

Base = declarative_base()

class Business(Base):
    __tablename__ = 'businesses'
    id = Column(Integer, primary_key=True)
    business_name = Column(String(100), nullable=False)
    ig_page = Column(String(100))
    facebook_page = Column(String(100))
    twitter_page = Column(String(100))
    email = Column(String(100), nullable=False)
    tiktok = Column(String(100))
    website = Column(String(100))
    phone_number = Column(String(20))
    business_description = Column(String(500))
    business_niche = Column(String(100))
    business_type = Column(String(50))  # Could be 'logistics' or 'vendor'
    date_created = Column(DateTime, default=datetime.now)

    products = relationship('Product', back_populates='business')
    transactions = relationship('Transaction', back_populates='business')

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey('businesses.id'), nullable=False)
    product_name = Column(String(100), nullable=False)
    product_description = Column(String(500))
    product_category = Column(String(100))
    price = Column(Float, nullable=False)
    items_in_stock = Column(Integer)
    tags = Column(String(200))
    date_created = Column(DateTime, default=datetime.now)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    business = relationship('Business', back_populates='products')

class Transaction(Base):
    __tablename__ = 'transactions'
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    product_desc = Column(String(500))
    business_id = Column(Integer, ForeignKey('businesses.id'), nullable=False)
    payment_status = Column(String(50))  # Could be 'pending' or 'verified'
    price = Column(Float, nullable=False)
    item_category = Column(String(100))
    items_bought = Column(Integer, nullable=False)
    bot_marketed = Column(Boolean, default=False)
    date = Column(DateTime, default=datetime.now)
    time = Column(DateTime, default=datetime.now)

    product = relationship('Product')
    business = relationship('Business', back_populates='transactions')

# Create all tables in the engine
Base.metadata.create_all(engine)
