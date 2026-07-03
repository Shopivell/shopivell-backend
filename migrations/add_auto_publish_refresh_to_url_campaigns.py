"""
Migration script to add auto_publish_refresh column to url_campaigns table.

Controls the fatigue auto-refresh safety gate: when False (default), replacement
ads generated for fatigued creatives are created PAUSED for human approval; when
True, they go live ACTIVE automatically.

Run this script once to apply the database changes.
"""
from database import engine
from sqlalchemy import text


def run_migration():
    with engine.connect() as conn:
        print("Adding auto_publish_refresh column to url_campaigns table...")
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'url_campaigns' AND column_name = 'auto_publish_refresh'
                ) THEN
                    ALTER TABLE url_campaigns
                        ADD COLUMN auto_publish_refresh BOOLEAN NOT NULL DEFAULT FALSE;
                END IF;
            END$$;
        """))
        conn.commit()
        print("[OK] auto_publish_refresh column added to url_campaigns table")

        print("\n[SUCCESS] Migration completed successfully!")


if __name__ == "__main__":
    run_migration()
