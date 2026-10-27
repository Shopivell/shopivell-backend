"""
Migration script to add facebook_pixel_id column to stores table.
Run this script once to apply the database changes.
"""
from database import engine
from sqlalchemy import text


def run_migration():
    with engine.connect() as conn:
        print("Adding facebook_pixel_id column to stores table...")
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'stores' AND column_name = 'facebook_pixel_id'
                ) THEN
                    ALTER TABLE stores ADD COLUMN facebook_pixel_id VARCHAR(50);
                END IF;
            END$$;
        """))
        conn.commit()
        print("[OK] facebook_pixel_id column added to stores table")

        print("\n[SUCCESS] Migration completed successfully!")


if __name__ == "__main__":
    run_migration()
