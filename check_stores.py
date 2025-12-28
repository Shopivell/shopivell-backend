import psycopg2
import json

conn = psycopg2.connect(
    host='localhost',
    database='shopivell',
    user='postgres',
    password='farairato'
)
cur = conn.cursor()

# Check recent stores
print("=== Recent Stores ===")
cur.execute('SELECT id, store_name, owner_id, agency_id FROM stores ORDER BY created_at DESC LIMIT 5')
rows = cur.fetchall()
for r in rows:
    print(f"ID: {r[0]}")
    print(f"  Name: {r[1]}")
    print(f"  Owner: {r[2]}")
    print(f"  Agency: {r[3]}")
    print()

# Check agencies
print("\n=== Agencies ===")
cur.execute('SELECT id, name, owner_id FROM agencies ORDER BY created_at DESC LIMIT 5')
rows = cur.fetchall()
for r in rows:
    print(f"ID: {r[0]}, Name: {r[1]}, Owner: {r[2]}")

# Check users
print("\n=== Recent Users ===")
cur.execute('SELECT id, email, agency_id FROM users ORDER BY created_at DESC LIMIT 5')
rows = cur.fetchall()
for r in rows:
    print(f"ID: {r[0]}, Email: {r[1]}, Agency: {r[2]}")

conn.close()
