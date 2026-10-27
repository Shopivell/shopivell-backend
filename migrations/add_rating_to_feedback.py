"""
Migration: Add rating column to feedback table.

Adds an optional integer rating (1-5) for platform reviews.

Usage:
    python migrations/add_rating_to_feedback.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine, SessionLocal


def migrate():
    """Add rating column to feedback table."""

    db = SessionLocal()

    try:
        # Check if column already exists
        result = db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'feedback' AND column_name = 'rating'
        """))
        if result.fetchone():
            print("Column 'rating' already exists in 'feedback' table. Skipping.")
            return

        # Add rating column
        db.execute(text("""
            ALTER TABLE feedback ADD COLUMN rating INTEGER NULL
        """))

        db.commit()
        print("Successfully added 'rating' column to 'feedback' table.")

    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
