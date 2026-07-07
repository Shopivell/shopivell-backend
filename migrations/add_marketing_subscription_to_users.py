"""
Migration: Add marketing_emails_subscribed column to users table.

The backend uses SQLAlchemy create_all, which never adds columns to existing
tables, so this must be run against the live database once.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")

DATABASE_URL = f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={DB_SSLMODE}"


def run_migration():
    print("[Migration] Adding marketing_emails_subscribed column to users table...")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'marketing_emails_subscribed'
        """))
        if result.fetchone():
            print("[Migration] Column already exists — nothing to do")
        else:
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN marketing_emails_subscribed BOOLEAN NOT NULL DEFAULT TRUE
            """))
            conn.commit()
            print("[Migration] marketing_emails_subscribed column added successfully!")
    print("[Migration] Complete!")


if __name__ == "__main__":
    run_migration()
