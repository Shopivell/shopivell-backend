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

    Base.metadata.create_all(bind=engine)

    if not USE_SQLITE:
        # Run column migrations for existing tables (Postgres-specific SQL)
        run_column_migrations()

    print(f"[OK] Database initialized ({'SQLite' if USE_SQLITE else 'PostgreSQL'})")


def run_column_migrations():
    """Add missing columns to existing tables"""
    from sqlalchemy import text

    with engine.connect() as conn:
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
