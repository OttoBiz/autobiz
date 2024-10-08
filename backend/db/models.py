from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID
# from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from dotenv import load_dotenv
from .database import Base, engine
load_dotenv()

class Business(Base):
    __tablename__ = "businesses"
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
    bank_name = Column(String(100))
    bank_account_number = Column(String(50))
    bank_account_name = Column(String(50))
    business_type = Column(String(50))  # Could be 'logistics' or 'vendor'
    date_created = Column(DateTime, default=datetime.now)
    logistic_partner = Column(String(100))

    products = relationship("Product", back_populates="business")
    transactions = relationship("Transaction", back_populates="business")
    

    def to_dict(self):
        """
        Converts the Business object to a dictionary representation.

        Returns:
            A dictionary containing all the attributes of the Business object.
        """
        return {
            "id": self.id,
            "business_name": self.business_name,
            "ig_page": self.ig_page,
            "facebook_page": self.facebook_page,
            "twitter_page": self.twitter_page,
            "email": self.email,
            "tiktok": self.tiktok,
            "website": self.website,
            "phone_number": self.phone_number,
            "business_description": self.business_description,
            "business_niche": self.business_niche,
            "business_type": self.business_type,
            "bank_name": self.bank_name,
            "bank_account_number": self.bank_account_number,
            "bank_account_name": self.bank_account_name,
            "logistic_id": self.logistic_partner
            # "date_created": self.date_created.isoformat(),  # Convert datetime to ISO format
        }


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    product_name = Column(String(100), nullable=False)
    product_description = Column(String(500))
    product_category = Column(String(100))
    price = Column(Float, nullable=False)
    items_in_stock = Column(Integer)
    tags = Column(String(200))
    date_created = Column(DateTime, default=datetime.now)
    date_modified = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    business = relationship("Business", back_populates="products")

    def to_dict(self):
        return {
            "product_name": self.product_name,
            "price": self.price,
            "items_left_in_stock": self.items_in_stock,
            "tags": self.tags
        }


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_desc = Column(String(500))
    business_id = Column(Integer, ForeignKey("businesses.id"), nullable=False)
    payment_status = Column(String(50))  # Could be 'pending' or 'verified'
    price = Column(Float, nullable=False)
    item_category = Column(String(100))
    items_bought = Column(Integer, nullable=False)
    bot_marketed = Column(Boolean, default=False)
    date = Column(DateTime, default=datetime.now)
    time = Column(DateTime, default=datetime.now)

    product = relationship("Product")
    business = relationship("Business", back_populates="transactions")

# Create all tables in the engine
Base.metadata.create_all(engine)
