"""
Migration script to add Agency tables and update Stores table.
Run this script once to apply the database changes.
"""
from database import engine
from sqlalchemy import text

def run_migration():
    with engine.connect() as conn:
        # Create the agencystatus enum type if it doesn't exist
        print("Creating agencystatus enum type...")
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'agencystatus') THEN
                    CREATE TYPE agencystatus AS ENUM ('active', 'suspended', 'pending');
                END IF;
            END$$;
        """))
        conn.commit()
        print("[OK] Enum type created or already exists")

        # Create the agencies table if it doesn't exist
        print("Creating agencies table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agencies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                owner_id UUID NOT NULL REFERENCES users(id),
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(255) UNIQUE NOT NULL,
                description TEXT,
                logo_url VARCHAR(500),
                email VARCHAR(255) NOT NULL,
                phone VARCHAR(50),
                website VARCHAR(500),
                address TEXT,
                city VARCHAR(100),
                country VARCHAR(100),
                status agencystatus DEFAULT 'active',
                settings JSONB DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
        """))
        conn.commit()
        print("[OK] Agencies table created or already exists")

        # Create index on owner_id
        print("Creating indexes...")
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_agencies_owner_id ON agencies(owner_id);
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_agencies_slug ON agencies(slug);
        """))
        conn.commit()
        print("[OK] Indexes created")

        # Add agency_id column to stores table if it doesn't exist
        print("Adding agency_id column to stores table...")
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'stores' AND column_name = 'agency_id'
                ) THEN
                    ALTER TABLE stores ADD COLUMN agency_id UUID REFERENCES agencies(id);
                    CREATE INDEX ix_stores_agency_id ON stores(agency_id);
                END IF;
            END$$;
        """))
        conn.commit()
        print("[OK] agency_id column added to stores table")

        print("\n[SUCCESS] Migration completed successfully!")

if __name__ == "__main__":
    run_migration()
