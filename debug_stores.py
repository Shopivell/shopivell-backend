import psycopg2

conn = psycopg2.connect(
    host='localhost',
    database='shopivell',
    user='postgres',
    password='farairato'
)
cur = conn.cursor()

print("=== ALL STORES ===")
cur.execute('SELECT id, store_name, owner_id, agency_id, created_at FROM stores ORDER BY created_at DESC')
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"Store ID: {r[0]}")
        print(f"  Name: {r[1]}")
        print(f"  Owner ID: {r[2]}")
        print(f"  Agency ID: {r[3]}")
        print(f"  Created: {r[4]}")
        print()
else:
    print("No stores found!")

print("\n=== ALL AGENCIES ===")
cur.execute('SELECT id, name, owner_id, email FROM agencies ORDER BY created_at DESC')
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"Agency ID: {r[0]}")
        print(f"  Name: {r[1]}")
        print(f"  Owner ID: {r[2]}")
        print(f"  Email: {r[3]}")
        print()
else:
    print("No agencies found!")

print("\n=== ALL USERS ===")
cur.execute('SELECT id, email, name FROM users ORDER BY created_at DESC LIMIT 5')
rows = cur.fetchall()
for r in rows:
    print(f"User ID: {r[0]}, Email: {r[1]}, Name: {r[2]}")

conn.close()
