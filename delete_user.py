"""
Delete user and all related data
"""
import psycopg2

email = 'farai.rato@students.uz.ac.zw'

conn = psycopg2.connect(
    host='localhost',
    database='shopivell',
    user='postgres',
    password='farairato'
)
cur = conn.cursor()

print(f"Deleting user: {email}")
print("=" * 50)

# Find the user
cur.execute('SELECT id, name FROM users WHERE email = %s', (email,))
user = cur.fetchone()

if not user:
    print(f"User not found with email: {email}")
    conn.close()
    exit()

user_id = user[0]
user_name = user[1]
print(f"Found user: {user_name} (ID: {user_id})")

# Delete setup sessions
cur.execute('DELETE FROM store_setup_sessions WHERE user_id = %s', (user_id,))
print(f"Deleted {cur.rowcount} setup sessions")

# Delete stores (this will cascade delete related data)
cur.execute('DELETE FROM stores WHERE owner_id = %s', (user_id,))
print(f"Deleted {cur.rowcount} stores")

# Delete agencies
cur.execute('DELETE FROM agencies WHERE owner_id = %s', (user_id,))
print(f"Deleted {cur.rowcount} agencies")

# Delete the user
cur.execute('DELETE FROM users WHERE id = %s', (user_id,))
print(f"Deleted user")

conn.commit()
print("=" * 50)
print("Done! User and all related data deleted.")
conn.close()
