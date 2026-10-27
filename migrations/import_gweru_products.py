"""
Migration script to import Gweru branch products for Platinum Pharmacy.
Run with: python migrations/import_gweru_products.py
"""
import uuid
from datetime import datetime
from database import engine
from sqlalchemy import text

STORE_ID = "94caaf72-2f38-4a62-9f4a-76f327ff44c0"
BRANCH = "Gweru"

# Import products from data file
from migrations.gweru_products_data import PRODUCTS


def run_migration():
    print(f"Importing {BRANCH} branch products for Platinum Pharmacy...")
    print(f"Store ID: {STORE_ID}")
    print(f"Products to import: {len(PRODUCTS)}")

    with engine.connect() as conn:
        # Check existing products
        result = conn.execute(text("""
            SELECT COUNT(*) FROM company_knowledge
            WHERE store_id = :store_id AND branch = :branch
        """), {"store_id": STORE_ID, "branch": BRANCH})
        existing = result.fetchone()[0]
        print(f"Existing {BRANCH} products: {existing}")

        if existing > 0:
            print(f"Deleting existing {BRANCH} products first...")
            conn.execute(text("""
                DELETE FROM company_knowledge
                WHERE store_id = :store_id AND branch = :branch
            """), {"store_id": STORE_ID, "branch": BRANCH})
            conn.commit()
            print(f"Deleted {existing} existing products")

        # Import new products
        imported = 0
        for name, price in PRODUCTS:
            content = f"Product: {name}\nPrice: ${price:.2f}"

            conn.execute(text("""
                INSERT INTO company_knowledge (id, store_id, content_type, content, is_active, branch, created_at, updated_at)
                VALUES (:id, :store_id, :content_type, :content, :is_active, :branch, :created_at, :updated_at)
            """), {
                "id": str(uuid.uuid4()),
                "store_id": STORE_ID,
                "content_type": "product",
                "content": content,
                "is_active": True,
                "branch": BRANCH,
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            })

            imported += 1
            if imported % 500 == 0:
                print(f"Imported {imported} products...")
                conn.commit()

        conn.commit()
        print(f"\n[OK] Successfully imported {imported} {BRANCH} products!")

        # Show all branches
        result = conn.execute(text("""
            SELECT branch, COUNT(*) FROM company_knowledge
            WHERE store_id = :store_id AND branch IS NOT NULL
            GROUP BY branch ORDER BY branch
        """), {"store_id": STORE_ID})
        print("\nAll branches:")
        for row in result.fetchall():
            print(f"  {row[0]}: {row[1]} products")

        print("\n[SUCCESS] Migration completed!")


if __name__ == "__main__":
    run_migration()
