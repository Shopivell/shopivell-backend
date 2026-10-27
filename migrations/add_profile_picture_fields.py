"""
Migration: Add profile_picture_url and profile_picture_updated_at to whatsapp_conversations table.

Run this script to add the new columns for WhatsApp profile picture support.

Usage:
    python migrations/add_profile_picture_fields.py
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine, SessionLocal

def migrate():
    """Add profile picture fields to whatsapp_conversations table."""

    db = SessionLocal()

    try:
        # Check if columns already exist
        check_query = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'whatsapp_conversations'
            AND column_name IN ('profile_picture_url', 'profile_picture_updated_at')
        """)

        result = db.execute(check_query)
        existing_columns = [row[0] for row in result]

        # Add profile_picture_url if not exists
        if 'profile_picture_url' not in existing_columns:
            print("Adding profile_picture_url column...")
            db.execute(text("""
                ALTER TABLE whatsapp_conversations
                ADD COLUMN profile_picture_url TEXT NULL
            """))
            print("[OK] Added profile_picture_url column")
        else:
            print("[OK] profile_picture_url column already exists")

        # Add profile_picture_updated_at if not exists
        if 'profile_picture_updated_at' not in existing_columns:
            print("Adding profile_picture_updated_at column...")
            db.execute(text("""
                ALTER TABLE whatsapp_conversations
                ADD COLUMN profile_picture_updated_at TIMESTAMP NULL
            """))
            print("[OK] Added profile_picture_updated_at column")
        else:
            print("[OK] profile_picture_updated_at column already exists")

        db.commit()
        print("\n[SUCCESS] Migration completed!")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Migration failed: {e}")
        raise
    finally:
        db.close()


def rollback():
    """Remove profile picture fields (rollback migration)."""

    db = SessionLocal()

    try:
        print("Rolling back: Removing profile picture columns...")

        db.execute(text("""
            ALTER TABLE whatsapp_conversations
            DROP COLUMN IF EXISTS profile_picture_url,
            DROP COLUMN IF EXISTS profile_picture_updated_at
        """))

        db.commit()
        print("✅ Rollback completed successfully!")

    except Exception as e:
        db.rollback()
        print(f"❌ Rollback failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Profile picture migration")
    parser.add_argument("--rollback", action="store_true", help="Rollback the migration")
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
