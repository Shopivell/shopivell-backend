"""
Script to add draft support columns to meta_campaigns, meta_ad_sets, and meta_ads tables.
Run this once to update the database schema.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine

def add_draft_columns():
    """Add is_draft, notes, draft_data, and published_at columns to marketing tables."""

    columns_to_add = [
        # meta_campaigns table
        ("meta_campaigns", "is_draft", "BOOLEAN DEFAULT FALSE"),
        ("meta_campaigns", "notes", "TEXT"),
        ("meta_campaigns", "draft_data", "JSONB"),
        ("meta_campaigns", "published_at", "TIMESTAMP"),

        # meta_ad_sets table
        ("meta_ad_sets", "is_draft", "BOOLEAN DEFAULT FALSE"),
        ("meta_ad_sets", "notes", "TEXT"),
        ("meta_ad_sets", "draft_data", "JSONB"),
        ("meta_ad_sets", "published_at", "TIMESTAMP"),

        # meta_ads table (already has these in model, but may need to add to DB)
        ("meta_ads", "is_draft", "BOOLEAN DEFAULT FALSE"),
        ("meta_ads", "notes", "TEXT"),
        ("meta_ads", "draft_data", "JSONB"),
        ("meta_ads", "published_at", "TIMESTAMP"),
    ]

    with engine.connect() as conn:
        for table, column, column_type in columns_to_add:
            try:
                # Check if column exists
                check_sql = text(f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = :table AND column_name = :column
                """)
                result = conn.execute(check_sql, {"table": table, "column": column})

                if result.fetchone() is None:
                    # Column doesn't exist, add it
                    alter_sql = text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
                    conn.execute(alter_sql)
                    print(f"Added column {column} to {table}")
                else:
                    print(f"Column {column} already exists in {table}")

            except Exception as e:
                print(f"Error adding {column} to {table}: {e}")

        conn.commit()
        print("\nMigration completed successfully!")

if __name__ == "__main__":
    add_draft_columns()
