"""
Script to delete the Zimswitch store for testing purposes.
Run: python delete_zimswitch_store.py
"""
from database import engine
from sqlalchemy import text

def delete_zimswitch_store():
    with engine.connect() as conn:
        # Find user by email
        result = conn.execute(
            text("SELECT id, email FROM users WHERE email = :email"),
            {"email": "farairhato@gmail.com"}
        ).fetchone()

        if not result:
            print("User farairhato@gmail.com not found")
            return

        user_id = result[0]
        print(f"Found user: {result[1]} (id: {user_id})")

        # Find zimswitch store(s) owned by this user
        stores = conn.execute(
            text("""
                SELECT id, store_name FROM stores
                WHERE owner_id = :owner_id
                AND LOWER(store_name) LIKE :pattern
            """),
            {"owner_id": user_id, "pattern": "%zimswitch%"}
        ).fetchall()

        if not stores:
            print("No Zimswitch store found for this user")
            # List all stores for this user
            all_stores = conn.execute(
                text("SELECT id, store_name FROM stores WHERE owner_id = :owner_id"),
                {"owner_id": user_id}
            ).fetchall()
            print(f"\nUser has {len(all_stores)} store(s):")
            for s in all_stores:
                print(f"  - {s[1]} (id: {s[0]})")
            return

        for store in stores:
            store_id = store[0]
            store_name = store[1]
            print(f"Deleting store: {store_name} (id: {store_id})")

            # Delete related records first (foreign key constraints)
            conn.execute(text("DELETE FROM store_subscriptions WHERE store_id = :id"), {"id": store_id})
            conn.execute(text("DELETE FROM store_bot_configs WHERE store_id = :id"), {"id": store_id})
            conn.execute(text("DELETE FROM products WHERE store_id = :id"), {"id": store_id})
            conn.execute(text("DELETE FROM faqs WHERE store_id = :id"), {"id": store_id})

            # Delete the store
            conn.execute(text("DELETE FROM stores WHERE id = :id"), {"id": store_id})

        conn.commit()
        print(f"\nDeleted {len(stores)} store(s) successfully!")

if __name__ == "__main__":
    delete_zimswitch_store()
