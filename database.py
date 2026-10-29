from pathlib import Path
from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# Set the correct path to the .env file inside the routers folder
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

USE_SQLITE = os.getenv("USE_SQLITE", "true").lower() == "true"
# SQL query echo is OFF by default: echo=True floods logs with every statement
# (and double-logs once structured logging is configured). Enable per-need with
# SQL_ECHO=true for debugging.
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() == "true"

if USE_SQLITE:
    DATABASE_DIR = Path(__file__).resolve().parent
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_DIR}/shopivell.db"
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        echo=SQL_ECHO,
        connect_args={"check_same_thread": False},
    )

    # Enable WAL mode and foreign keys for SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

else:
    DB_USERNAME = os.getenv("DB_USERNAME")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT")
    DB_NAME = os.getenv("DB_NAME")
    DB_SSLMODE = os.getenv("DB_SSLMODE", "prefer")

    missing_vars = [var for var, val in {
        "DB_USERNAME": DB_USERNAME,
        "DB_PASSWORD": DB_PASSWORD,
        "DB_HOST": DB_HOST,
        "DB_PORT": DB_PORT,
        "DB_NAME": DB_NAME,
    }.items() if not val]

    if missing_vars:
        raise ValueError(f"Missing required environment variables: {missing_vars}")

    SQLALCHEMY_DATABASE_URL = (
        f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={DB_SSLMODE}"
    )
    engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=SQL_ECHO)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # Ensure an aborted transaction doesn't get returned to the pool
        # in a failed state (which would surface as InFailedSqlTransaction
        # on the next request that reuses this connection).
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    """Initializes the database by creating all tables defined in Base."""
    from sqlalchemy import text

    if not USE_SQLITE:
        # Create pgvector extension if it doesn't exist (Postgres only)
        with engine.connect() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
            except Exception as e:
                print(f"Warning: Could not create vector extension: {e}")

    # Import models here so SQLAlchemy is aware of them
    from modules.customers import models as customer_models
    from modules.orders import models as order_models
    from modules.products import models as products_models
    from modules.analytics import models as analytics_models
    # from modules.Markets import models as markets_models
    from modules.stores import models as store_models
    from modules.users import models as user_models
    from modules.content.template import models as template_models
    from modules.content.content import models as content_models  # Example additional model
    from modules.social import models as social_models
    from modules.business import models as business_models
    from modules.payment import models as payment_models
    from modules.whatsapp import models as whatsapp_models
    from modules.agency import models as agency_models
    from modules.campaigns import models as campaign_models
    from modules.assets import models as asset_models
    from modules.notifications import models as notification_models
    from modules.admin import models as admin_models
    from modules.pos import models as pos_models
    from modules.accounting import models as accounting_models
    from modules.website_builder import models as website_builder_models
    from modules.fashion import models as fashion_models
    from modules.openrouter import models as openrouter_models
    from modules.reviews import models as reviews_models
    from modules.coupons import models as coupons_models
    from modules.returns import models as returns_models
    from modules.referral import models as referral_models
    from modules.feedback import models as feedback_models
    from modules.delivery import models as delivery_models
    from modules.procurement import models as procurement_models
    from modules.optimizer import models as optimizer_models

    Base.metadata.create_all(bind=engine)

    # create_all only creates missing TABLES — it never adds columns to
    # existing ones. Reconcile any model columns the live DB is missing
    # (e.g. stores.brand_dna) so SELECTs don't die with UndefinedColumn
    # after a deploy. The hand-written blocks below stay for special cases
    # that need more than a plain ADD COLUMN.
    try:
        reconcile_missing_columns()
    except Exception as e:
        print(f"[WARN] Column reconciler failed: {e}")

    if not USE_SQLITE:
        # Run column migrations for existing tables (Postgres-specific SQL)
        run_column_migrations()

    print(f"[OK] Database initialized ({'SQLite' if USE_SQLITE else 'PostgreSQL'})")


def run_column_migrations():
    """Add missing columns to existing tables"""
    from sqlalchemy import text

    with engine.connect() as conn:
        # Index used to filter the pharmacy inbox by staff branch assignment.
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_whatsapp_conversations_branch "
                "ON whatsapp_conversations (branch)"
            ))
            conn.commit()
            print("[OK] Verified pharmacy conversation branch index exists")
        except Exception as e:
            print(f"[WARN] Could not add pharmacy conversation branch index: {e}")

        # Add screenshot_url to stores if missing
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'stores' AND column_name = 'screenshot_url'
                    ) THEN
                        ALTER TABLE stores ADD COLUMN screenshot_url VARCHAR(500);
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified screenshot_url column exists in stores table")
        except Exception as e:
            print(f"[WARN] Could not add screenshot_url column: {e}")

        # Add Zernio ad-management columns to stores if missing (OpenClaw migration)
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'stores' AND column_name = 'zernio_profile_id'
                    ) THEN
                        ALTER TABLE stores ADD COLUMN zernio_profile_id VARCHAR(255);
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'stores' AND column_name = 'ads_enabled'
                    ) THEN
                        ALTER TABLE stores ADD COLUMN ads_enabled BOOLEAN NOT NULL DEFAULT FALSE;
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified zernio_profile_id and ads_enabled columns exist in stores table")
        except Exception as e:
            print(f"[WARN] Could not add Zernio store columns: {e}")

        # Add rating column to feedback table if missing
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'feedback' AND column_name = 'rating'
                    ) THEN
                        ALTER TABLE feedback ADD COLUMN rating INTEGER NULL;
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified rating column exists in feedback table")
        except Exception as e:
            print(f"[WARN] Could not add rating column: {e}")

        # Add revenue column to meta_ad_insights if missing (for ROAS backtesting)
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'meta_ad_insights' AND column_name = 'revenue'
                    ) THEN
                        ALTER TABLE meta_ad_insights ADD COLUMN revenue DOUBLE PRECISION DEFAULT 0.0;
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified revenue column exists in meta_ad_insights table")
        except Exception as e:
            print(f"[WARN] Could not add revenue column: {e}")

        # Add lead_score and lead_status columns to customers if missing
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'customers' AND column_name = 'lead_score'
                    ) THEN
                        ALTER TABLE customers ADD COLUMN lead_score INTEGER NOT NULL DEFAULT 0;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'customers' AND column_name = 'lead_status'
                    ) THEN
                        ALTER TABLE customers ADD COLUMN lead_status VARCHAR(50);
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified lead_score and lead_status columns exist in customers table")
        except Exception as e:
            print(f"[WARN] Could not add lead score columns: {e}")

        # Add agencies table if missing
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'agencystatus') THEN
                        CREATE TYPE agencystatus AS ENUM ('active', 'suspended', 'pending');
                    END IF;
                END$$;
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agencies (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    owner_id UUID NOT NULL REFERENCES users(id),
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(255) UNIQUE NOT NULL,
                    description TEXT,
                    logo_url VARCHAR(500),
                    email VARCHAR(255) NOT NULL,
                    phone VARCHAR(50),
                    website VARCHAR(500),
                    address TEXT,
                    city VARCHAR(100),
                    country VARCHAR(100),
                    status agencystatus DEFAULT 'active',
                    settings JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agencies_owner_id ON agencies(owner_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agencies_slug ON agencies(slug);"))
            conn.commit()
            print("[OK] Verified agencies table exists")
        except Exception as e:
            print(f"[WARN] Could not create agencies table: {e}")

        # Add WhatsApp marketing consent fields to whatsapp_leads
        # (WhatsApp Business Messaging Policy: opt-in before marketing,
        # permanent opt-out suppression)
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'whatsapp_leads' AND column_name = 'marketing_opt_in'
                    ) THEN
                        ALTER TABLE whatsapp_leads ADD COLUMN marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'whatsapp_leads' AND column_name = 'opt_in_source'
                    ) THEN
                        ALTER TABLE whatsapp_leads ADD COLUMN opt_in_source VARCHAR(100);
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'whatsapp_leads' AND column_name = 'opt_in_at'
                    ) THEN
                        ALTER TABLE whatsapp_leads ADD COLUMN opt_in_at TIMESTAMP;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'whatsapp_leads' AND column_name = 'opted_out_at'
                    ) THEN
                        ALTER TABLE whatsapp_leads ADD COLUMN opted_out_at TIMESTAMP;
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified WhatsApp consent columns exist in whatsapp_leads table")
        except Exception as e:
            print(f"[WARN] Could not add WhatsApp consent columns: {e}")

        # Add shopivell_user_id to facebook_business_accounts for user-level filtering
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'facebook_business_accounts' AND column_name = 'shopivell_user_id'
                    ) THEN
                        ALTER TABLE facebook_business_accounts ADD COLUMN shopivell_user_id VARCHAR(255);
                        CREATE INDEX IF NOT EXISTS ix_fba_shopivell_user_id ON facebook_business_accounts(shopivell_user_id);
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified shopivell_user_id column exists in facebook_business_accounts table")
        except Exception as e:
            print(f"[WARN] Could not add shopivell_user_id column: {e}")

        # Remember which store a user was last working in, so it's restored on their
        # next login instead of always defaulting to Store.owner_id's first match.
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'last_active_store_id'
                    ) THEN
                        ALTER TABLE users ADD COLUMN last_active_store_id UUID NULL;
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified last_active_store_id column exists in users table")
        except Exception as e:
            print(f"[WARN] Could not add last_active_store_id column: {e}")

        # Model-driven optimizer target calibration: opt-in flag + audit trail (when it
        # last ran and why it picked the numbers it did), separate from the manually-set
        # target_roas/target_cpa columns which already existed on this table.
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'ad_optimizer_configs' AND column_name = 'auto_calibrate'
                    ) THEN
                        ALTER TABLE ad_optimizer_configs ADD COLUMN auto_calibrate BOOLEAN NOT NULL DEFAULT FALSE;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'ad_optimizer_configs' AND column_name = 'last_calibrated_at'
                    ) THEN
                        ALTER TABLE ad_optimizer_configs ADD COLUMN last_calibrated_at TIMESTAMP NULL;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'ad_optimizer_configs' AND column_name = 'calibration_reasoning'
                    ) THEN
                        ALTER TABLE ad_optimizer_configs ADD COLUMN calibration_reasoning TEXT NULL;
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified auto_calibrate/last_calibrated_at/calibration_reasoning columns exist in ad_optimizer_configs table")
        except Exception as e:
            print(f"[WARN] Could not add optimizer calibration columns: {e}")

        # Brand kit columns on stores (Auto-Fill page: description, palette,
        # typography). Without these the ORM SELECT on stores fails with
        # UndefinedColumn on databases created before they were added.
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'stores' AND column_name = 'brand_description'
                    ) THEN
                        ALTER TABLE stores ADD COLUMN brand_description TEXT;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'stores' AND column_name = 'secondary_colors'
                    ) THEN
                        ALTER TABLE stores ADD COLUMN secondary_colors JSON;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'stores' AND column_name = 'font_heading'
                    ) THEN
                        ALTER TABLE stores ADD COLUMN font_heading VARCHAR(120);
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'stores' AND column_name = 'font_body'
                    ) THEN
                        ALTER TABLE stores ADD COLUMN font_body VARCHAR(120);
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified brand_description/secondary_colors/font_heading/font_body columns exist in stores table")
        except Exception as e:
            print(f"[WARN] Could not add brand-kit columns to stores: {e}")

        # Marketing emails opt-out flag on users (safety net; also in
        # migrations/add_marketing_subscription_to_users.py).
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'marketing_emails_subscribed'
                    ) THEN
                        ALTER TABLE users ADD COLUMN marketing_emails_subscribed BOOLEAN NOT NULL DEFAULT TRUE;
                    END IF;
                END$$;
            """))
            conn.commit()
            print("[OK] Verified marketing_emails_subscribed column exists in users table")
        except Exception as e:
            print(f"[WARN] Could not add marketing_emails_subscribed column: {e}")


def _safe_add_default(col) -> str:
    """SQL DEFAULT fragment for ADD COLUMN, or '' when none is needed.

    Postgres refuses ADD COLUMN ... NOT NULL without a default on a
    non-empty table, so NOT NULL columns need one. Only simple literals
    (bools, numbers, strings) are supported — enough for model defaults.
    Anything else raises and the caller skips that column with a warning.
    """
    if col.server_default is not None:
        return ""
    default = getattr(col.default, "arg", None)
    if callable(default):
        raise ValueError("callable default")
    if default is None:
        if not col.nullable:
            raise ValueError("NOT NULL without default")
        return ""
    if isinstance(default, bool):
        return f" DEFAULT {str(default).upper()}"
    if isinstance(default, (int, float)):
        return f" DEFAULT {default}"
    if isinstance(default, str):
        escaped = default.replace("'", "''")
        return f" DEFAULT '{escaped}'"
    raise ValueError("unsupported default type")


def reconcile_missing_columns():
    """Add model columns that are missing from the live database.

    create_all creates missing TABLES but never alters existing ones, so any
    model column added after a DB was created (brand_dna, ai_creative_prompt,
    ...) breaks every ORM SELECT with UndefinedColumn. This compares every
    table in the registry against the actual schema and adds what's missing,
    compiling DDL for the live dialect so it also heals the dev SQLite file.

    Failures are per-column and non-fatal: a column that can't be added
    safely logs a warning and startup continues.
    """
    from sqlalchemy import text
    from sqlalchemy.schema import CreateColumn

    added = []
    with engine.connect() as conn:
        # What does the DB already have?
        db_cols = {}
        if engine.dialect.name == "sqlite":
            for table in Base.metadata.sorted_tables:
                rows = conn.exec_driver_sql(f"PRAGMA table_info({table.name})").fetchall()
                if rows:
                    db_cols[table.name] = {str(r[1]) for r in rows}
        else:
            for t, c in conn.execute(text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            )).fetchall():
                db_cols.setdefault(str(t), set()).add(str(c))

        for table in Base.metadata.sorted_tables:
            existing = db_cols.get(table.name)
            if existing is None:
                continue  # brand-new table — create_all already made it
            for col in table.columns:
                if col.name in existing:
                    continue
                try:
                    ddl = str(CreateColumn(col).compile(dialect=engine.dialect))
                    stmt = f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}{_safe_add_default(col)}'
                    conn.execute(text(stmt))
                    added.append(f"{table.name}.{col.name}")
                except Exception as e:
                    print(f"[WARN] reconcile {table.name}.{col.name} skipped: {e}")
        conn.commit()

    if added:
        print(f"[OK] Column reconciler added missing columns: {added}")
    else:
        print("[OK] Column reconciler: schema matches models")
