"""
Fix stores that don't have agency_id linked
"""
import psycopg2

conn = psycopg2.connect(
    host='localhost',
    database='shopivell',
    user='postgres',
    password='farairato'
)
cur = conn.cursor()

print("=" * 60)
print("FIXING STORE-AGENCY LINKS")
print("=" * 60)

# Find stores without agency_id
cur.execute('''
    SELECT s.id, s.store_name, s.owner_id, s.agency_id
    FROM stores s
    WHERE s.agency_id IS NULL
''')
stores_without_agency = cur.fetchall()

print(f"\nFound {len(stores_without_agency)} stores without agency_id")

for store in stores_without_agency:
    store_id, store_name, owner_id, agency_id = store
    print(f"\nStore: {store_name} (ID: {store_id})")
    print(f"  Owner ID: {owner_id}")

    # Find agency for this owner
    cur.execute('''
        SELECT id, name FROM agencies WHERE owner_id = %s
    ''', (owner_id,))
    agency = cur.fetchone()

    if agency:
        agency_id, agency_name = agency
        print(f"  Found agency: {agency_name} (ID: {agency_id})")

        # Update store with agency_id
        cur.execute('''
            UPDATE stores SET agency_id = %s WHERE id = %s
        ''', (agency_id, store_id))
        print(f"  [OK] Linked store to agency!")
    else:
        print(f"  [X] No agency found for owner {owner_id}")

conn.commit()
print("\n" + "=" * 60)
print("DONE! Changes committed.")
print("=" * 60)

# Verify the fix
cur.execute('''
    SELECT s.store_name, a.name as agency_name
    FROM stores s
    JOIN agencies a ON s.agency_id = a.id
''')
linked = cur.fetchall()
print(f"\nVerification - Stores linked to agencies: {len(linked)}")
for s in linked:
    print(f"  Store '{s[0]}' → Agency '{s[1]}'")

conn.close()
