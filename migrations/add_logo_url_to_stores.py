"""
Migration: Add logo_url column to stores table
Run this script to add the logo_url column if it doesn't exist.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Get database URL
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")

DATABASE_URL = f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={DB_SSLMODE}"


def run_migration():
    print("[Migration] Adding logo_url column to stores table...")

    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        # Check if column exists
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'stores' AND column_name = 'logo_url'
        """))

        if result.fetchone():
            print("[Migration] logo_url column already exists in stores table")
        else:
            print("[Migration] Adding logo_url column...")
            conn.execute(text("""
                ALTER TABLE stores
                ADD COLUMN logo_url VARCHAR(500)
            """))
            conn.commit()
            print("[Migration] logo_url column added successfully!")

        # Also check assets table has cloudinary columns
        print("\n[Migration] Checking assets table cloudinary columns...")

        columns_to_check = [
            ('cloudinary_public_id', 'VARCHAR(255)'),
            ('cloudinary_url', 'VARCHAR(512)'),
            ('cloudinary_secure_url', 'VARCHAR(512)'),
            ('thumbnail_url', 'VARCHAR(512)')
        ]

        for col_name, col_type in columns_to_check:
            result = conn.execute(text(f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'assets' AND column_name = '{col_name}'
            """))

            if result.fetchone():
                print(f"  [OK] {col_name} exists")
            else:
                print(f"  [ADDING] {col_name}...")
                conn.execute(text(f"""
                    ALTER TABLE assets
                    ADD COLUMN {col_name} {col_type}
                """))
                conn.commit()
                print(f"  [ADDED] {col_name}")

    print("\n[Migration] Complete!")


if __name__ == "__main__":
    run_migration()
