from database import SessionLocal
from modules.whatsapp.models import WhatsAppAccount, WhatsAppMessage

db = SessionLocal()

print("=== WhatsApp Accounts ===")
accounts = db.query(WhatsAppAccount).all()
print(f"Total accounts: {len(accounts)}")
for acc in accounts:
    print(f"  Phone: {acc.phone_number}, Store: {acc.store_id}, Enabled: {acc.is_enabled}, Default: {acc.is_default}")

print("\n=== Recent Messages ===")
messages = db.query(WhatsAppMessage).order_by(WhatsAppMessage.created_at.desc()).limit(10).all()
print(f"Total messages found: {len(messages)}")
for msg in messages:
    print(f"  [{msg.direction}] {msg.from_number} -> {msg.to_number}: {msg.message_text[:50] if msg.message_text else 'N/A'}...")

db.close()
