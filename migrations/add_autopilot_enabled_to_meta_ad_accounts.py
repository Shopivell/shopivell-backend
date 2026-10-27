"""
Migration: add autopilot_enabled column to meta_ad_accounts.

Master switch for autonomous rule execution. When False (default), the automated
rules engine runs in advise-only/dry-run mode for that account: it evaluates and
logs what it would do but makes no spend-affecting Meta changes. Must be explicitly
set True to allow live autonomous execution (pausing ads, changing budgets).

Run once to apply.
"""
from database import engine
from sqlalchemy import text


def run_migration():
    with engine.connect() as conn:
        print("Adding autopilot_enabled column to meta_ad_accounts table...")
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'meta_ad_accounts' AND column_name = 'autopilot_enabled'
                ) THEN
                    ALTER TABLE meta_ad_accounts
                        ADD COLUMN autopilot_enabled BOOLEAN NOT NULL DEFAULT FALSE;
                END IF;
            END$$;
        """))
        conn.commit()
        print("[OK] autopilot_enabled column added to meta_ad_accounts table")
        print("\n[SUCCESS] Migration completed successfully!")


if __name__ == "__main__":
    run_migration()
