"""
Migration script to add WhatsApp marketing consent fields to whatsapp_leads.
Required for WhatsApp Business Messaging Policy compliance (opt-in before
marketing messages, permanent opt-out suppression).
Run this script once to apply the database changes.
"""
from database import engine
from sqlalchemy import text


COLUMNS = [
    ("marketing_opt_in", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("opt_in_source", "VARCHAR(100)"),
    ("opt_in_at", "TIMESTAMP"),
    ("opted_out_at", "TIMESTAMP"),
]


def run_migration():
    with engine.connect() as conn:
        for column_name, column_def in COLUMNS:
            print(f"Adding {column_name} column to whatsapp_leads table...")
            conn.execute(text(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'whatsapp_leads' AND column_name = '{column_name}'
                    ) THEN
                        ALTER TABLE whatsapp_leads ADD COLUMN {column_name} {column_def};
                    END IF;
                END$$;
            """))
            conn.commit()
            print(f"[OK] {column_name} column added to whatsapp_leads table")

        print("\n[SUCCESS] Migration completed successfully!")


if __name__ == "__main__":
    run_migration()
