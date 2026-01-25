"""
Migration script to add screenshot_url column to stores table.
Run this script once to apply the database changes.
"""
from database import engine
from sqlalchemy import text


def run_migration():
    with engine.connect() as conn:
        # Add screenshot_url column to stores table if it doesn't exist
        print("Adding screenshot_url column to stores table...")
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'stores' AND column_name = 'screenshot_url'
                ) THEN
                    ALTER TABLE stores ADD COLUMN screenshot_url VARCHAR(500);
                END IF;
            END$$;
        """))
        conn.commit()
        print("[OK] screenshot_url column added to stores table")

        print("\n[SUCCESS] Migration completed successfully!")


if __name__ == "__main__":
    run_migration()
