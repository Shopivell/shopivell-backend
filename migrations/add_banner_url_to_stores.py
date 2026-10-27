"""
Migration script to add banner_url column to stores table.
"""
from database import engine
from sqlalchemy import text


def run_migration():
    with engine.connect() as conn:
        print("Adding banner_url column to stores table...")
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'stores' AND column_name = 'banner_url'
                ) THEN
                    ALTER TABLE stores ADD COLUMN banner_url VARCHAR(500);
                END IF;
            END$$;
        """))
        conn.commit()
        print("[OK] banner_url column added")
        print("\n[SUCCESS] Migration completed!")


if __name__ == "__main__":
    run_migration()
