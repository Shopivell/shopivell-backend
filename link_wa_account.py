"""Script to link existing WhatsApp account to a store"""
import sys
from database import SessionLocal
from modules.whatsapp.models import WhatsAppAccount
from modules.stores.models import Store

db = SessionLocal()

# Check WhatsApp accounts
print("=== WhatsApp Accounts ===")
accounts = db.query(WhatsAppAccount).all()
print(f"Total: {len(accounts)}")
for i, acc in enumerate(accounts):
    print(f"{i+1}. Phone: {acc.phone_number}, Store: {acc.store_id}, Enabled: {acc.is_enabled}")

# Check stores
print("\n=== Stores ===")
stores = db.query(Store).all()
for i, store in enumerate(stores):
    print(f"{i+1}. ID: {store.id}, Name: {store.store_name}")

# If there are accounts without store_id, link them
if len(sys.argv) > 1 and sys.argv[1] == "--link":
    if accounts and stores:
        store_id = stores[0].id  # Use first store
        for acc in accounts:
            if not acc.store_id:
                acc.store_id = store_id
                acc.is_enabled = True
                acc.is_default = True
                print(f"\nLinked {acc.phone_number} to store {store_id}")
        db.commit()
        print("Done!")

db.close()
