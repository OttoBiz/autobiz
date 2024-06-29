from datetime import datetime

import pandas as pd
from backend.db.models import Business, Product, Transaction
from backend.db.database import engine
from sqlalchemy.orm import sessionmaker

Session = sessionmaker(bind=engine)
session = Session()

Session = sessionmaker(bind=engine)


def load_csv_to_db(csv_file_path, table_name):
    df = pd.read_csv(csv_file_path)
    df = df.fillna("")
    df = df.astype(str)

    session = Session()

    try:
        if table_name == "businesses":
            for index, row in df.iterrows():
                print(row)  # Print each row for debugging
                business = Business(
                    business_name=str(row["business name"]),
                    ig_page=str(row.get("ig page", "")),
                    facebook_page=str(row.get("facebook page", "")),
                    twitter_page=str(row.get("twitter page", "")),
                    email=str(row["email"]),
                    tiktok=str(row.get("tiktok", "")),
                    website=str(row.get("website", "")),
                    phone_number=str(row.get("phone number", "")),
                    business_description=str(row.get("business description", "")),
                    business_niche=str(row.get("business niche", "")),
                    business_type=str(row.get("type", "")),
                    date_created=(
                        datetime.strptime(row["date created"], "%Y-%m-%d")
                        if "date created" in row and row["date created"]
                        else datetime.now()
                    ),
                )
                session.add(business)

        elif table_name == "products":
            for index, row in df.iterrows():
                print(row)  # Print each row for debugging
                product = Product(
                    business_id=row["id"],
                    product_name=row["Product"],
                    product_description=row["Description"],
                    product_category=row["Product category"],
                    price=float(row["Price"]),
                    items_in_stock=int(row["Available amount"]),
                    date_created=(
                        datetime.strptime(row["Date created"], "%Y-%m-%d")
                        if row["Date created"]
                        else datetime.now()
                    ),
                    date_modified=(
                        datetime.strptime(row["Date modified"], "%Y-%m-%d")
                        if row["Date modified"]
                        else datetime.now()
                    ),
                )
                session.add(product)

        elif table_name == "transactions":
            for index, row in df.iterrows():
                transaction = Transaction(
                    product_id=row["product_id"],
                    product_desc=row.get("product_desc"),
                    business_id=row["business_id"],
                    payment_status=row["payment_status"],
                    price=row["price"],
                    item_category=row.get("item_category"),
                    items_bought=row["items_bought"],
                    bot_marketed=row.get("bot_marketed", False),
                    date=(
                        datetime.strptime(row["date"], "%Y-%m-%d %H:%M:%S")
                        if "date" in row
                        else datetime.now()
                    ),
                    time=(
                        datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S")
                        if "time" in row
                        else datetime.now()
                    ),
                )
                session.add(transaction)

        # Commit the transaction
        session.commit()

    except Exception as e:
        # Rollback the transaction in case of an error
        session.rollback()
        print(f"An error occurred: {e}")

    finally:
        # Close the session
        session.close()


if __name__ == "__main__":
    load_csv_to_db("/workspaces/autobiz/dummy_data/Business_table.csv", "businesses")
    load_csv_to_db("/workspaces/autobiz/dummy_data/donrey_fashion.csv", "products")
    load_csv_to_db("/workspaces/autobiz/dummy_data/junae_cosmetics.csv", "products")
    load_csv_to_db("/workspaces/autobiz/dummy_data/manny_gadgets.csv", "products")
