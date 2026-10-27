"""
Migration script to add branch column to company_knowledge table.
This enables multi-branch support for stores like Platinum Pharmacy.
"""
from database import engine
from sqlalchemy import text


def run_migration():
    with engine.connect() as conn:
        print("Adding branch column to company_knowledge table...")
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'company_knowledge' AND column_name = 'branch'
                ) THEN
                    ALTER TABLE company_knowledge ADD COLUMN branch VARCHAR(100);
                    CREATE INDEX IF NOT EXISTS ix_company_knowledge_branch ON company_knowledge(branch);
                END IF;
            END$$;
        """))
        conn.commit()
        print("[OK] branch column added with index")
        print("\n[SUCCESS] Migration completed!")


if __name__ == "__main__":
    run_migration()
