import psycopg2

conn = psycopg2.connect(
    host='localhost',
    database='shopivell',
    user='postgres',
    password='farairato'
)
cur = conn.cursor()

print("=" * 50)
print("WHATSAPP ACCOUNTS")
print("=" * 50)
cur.execute("SELECT id, phone_number, store_id, is_enabled, is_default FROM whatsapp_accounts")
accounts = cur.fetchall()
print(f"Found: {len(accounts)}")
for acc in accounts:
    print(f"  ID: {acc[0]}")
    print(f"  Phone: {acc[1]}")
    print(f"  Store ID: {acc[2]}")
    print(f"  Enabled: {acc[3]}, Default: {acc[4]}")
    print()

print("=" * 50)
print("WHATSAPP MESSAGES")
print("=" * 50)
cur.execute("SELECT COUNT(*) FROM whatsapp_messages")
print(f"Total messages: {cur.fetchone()[0]}")

cur.execute("""
    SELECT from_number, to_number, message_text, direction, created_at
    FROM whatsapp_messages
    ORDER BY created_at DESC
    LIMIT 5
""")
messages = cur.fetchall()
for msg in messages:
    print(f"  [{msg[3]}] {msg[0]} -> {msg[1]}")
    print(f"    Text: {msg[2][:50] if msg[2] else 'N/A'}...")
    print(f"    Time: {msg[4]}")
    print()

print("=" * 50)
print("STORES")
print("=" * 50)
cur.execute("SELECT id, store_name FROM stores")
stores = cur.fetchall()
for store in stores:
    print(f"  {store[0]} - {store[1]}")

# Link accounts to the first store that doesn't have one
if accounts and stores:
    store_id = stores[0][0]
    print(f"\n>>> Linking all WhatsApp accounts to store: {stores[0][1]}")
    cur.execute("""
        UPDATE whatsapp_accounts
        SET store_id = %s, is_enabled = true, is_default = true
    """, (store_id,))
    print(f"    Updated {cur.rowcount} accounts")
    conn.commit()

conn.close()
print("\nDone! Now restart your frontend dev server and refresh the page.")
