"""
Migration: Add store brand-kit columns + agent chat tables to the LIVE database.

The backend uses SQLAlchemy create_all, which creates missing TABLES but never
adds COLUMNS to existing tables, so new columns on stores/users must be added
by running this script against the live database once.

Adds:
  stores.brand_description        TEXT NULL
  stores.secondary_colors         JSON NULL
  stores.font_heading             VARCHAR(120) NULL
  stores.font_body                VARCHAR(120) NULL
  users.marketing_emails_subscribed BOOLEAN NOT NULL DEFAULT TRUE (if missing)
  users.last_active_store_id      UUID NULL (if missing)
  agent_conversations / agent_messages / agent_credit_ledger tables (if missing)

Idempotent: safe to run multiple times.

Usage:
    python migrations/add_brand_kit_and_agent_tables.py
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


def column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
    """), {"t": table, "c": column})
    return result.fetchone() is not None


def add_column_if_missing(conn, table: str, column: str, ddl: str) -> None:
    if column_exists(conn, table, column):
        print(f"[Migration] {table}.{column} already exists — skipping")
    else:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        print(f"[Migration] Added {table}.{column} ({ddl})")


def run_migration():
    print("[Migration] Connecting to database...")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        # ── 1. Store brand-kit columns ────────────────────────────────────
        print("[Migration] Ensuring stores brand-kit columns...")
        add_column_if_missing(conn, "stores", "brand_description", "TEXT")
        add_column_if_missing(conn, "stores", "secondary_colors", "JSON")
        add_column_if_missing(conn, "stores", "font_heading", "VARCHAR(120)")
        add_column_if_missing(conn, "stores", "font_body", "VARCHAR(120)")
        add_column_if_missing(conn, "stores", "brand_dna", "JSON")
        add_column_if_missing(conn, "stores", "ai_creative_prompt", "TEXT")
        add_column_if_missing(
            conn, "stores", "ai_creative_auto_publish", "BOOLEAN NOT NULL DEFAULT FALSE"
        )

        # ── 2. User columns (idempotent safety net) ───────────────────────
        print("[Migration] Ensuring users columns...")
        if column_exists(conn, "users", "marketing_emails_subscribed"):
            print("[Migration] users.marketing_emails_subscribed already exists — skipping")
        else:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN marketing_emails_subscribed "
                "BOOLEAN NOT NULL DEFAULT TRUE"
            ))
            print("[Migration] Added users.marketing_emails_subscribed (BOOLEAN NOT NULL DEFAULT TRUE)")

        add_column_if_missing(conn, "users", "last_active_store_id", "UUID")

        # ── 3. Agent chat tables (create_all normally handles these at
        # boot, but create them here so the API works even if boot order
        # or timing skips it) ─────────────────────────────────────────────
        print("[Migration] Ensuring agent chat tables...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_conversations (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id),
                store_id UUID REFERENCES stores(id),
                title VARCHAR(255) DEFAULT 'New chat',
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agent_conversations_user_id ON agent_conversations (user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agent_conversations_store_id ON agent_conversations (store_id)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id UUID PRIMARY KEY,
                conversation_id UUID NOT NULL REFERENCES agent_conversations(id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL,
                content TEXT,
                parts JSON,
                created_at TIMESTAMP
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agent_messages_conversation_id ON agent_messages (conversation_id)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_credit_ledger (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id),
                delta INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                reason VARCHAR(60) NOT NULL,
                detail VARCHAR(255),
                created_at TIMESTAMP
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_agent_credit_ledger_user_id ON agent_credit_ledger (user_id)"
        ))
        print("[Migration] Agent tables ensured")

        conn.commit()

        # ── 4. Verify ─────────────────────────────────────────────────────
        print("[Migration] Verifying...")
        missing = []
        for table, cols in {
            "stores": ["brand_description", "secondary_colors", "font_heading", "font_body"],
            "users": ["marketing_emails_subscribed", "last_active_store_id"],
        }.items():
            for c in cols:
                if not column_exists(conn, table, c):
                    missing.append(f"{table}.{c}")
        for t in ("agent_conversations", "agent_messages", "agent_credit_ledger"):
            result = conn.execute(text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name = :t"
            ), {"t": t})
            if not result.fetchone():
                missing.append(f"table {t}")

        if missing:
            print(f"[Migration] FAILED — still missing: {missing}")
            sys.exit(1)
        print("[Migration] All columns and tables verified!")

    print("[Migration] Complete!")


if __name__ == "__main__":
    run_migration()
