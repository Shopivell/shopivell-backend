from pathlib import Path
from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
# Set the correct path to the .env file inside the routers folder
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")  # FIXED here
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_SSLMODE = os.getenv("DB_SSLMODE", "prefer")  # default "prefer"

# Validate all required env variables
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

engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initializes the database by creating all tables defined in Base."""
    from sqlalchemy import text

    # Create pgvector extension if it doesn't exist
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
    from modules.marketing import models as marketing_models
    from modules.whatsapp import models as whatsapp_models
    from modules.agents import models as agents_models
    from modules.agency import models as agency_models
    from modules.campaigns import models as campaign_models
    from modules.assets import models as asset_models
    from modules.notifications import models as notification_models
    from modules.admin import models as admin_models
    from modules.pos import models as pos_models
    from modules.accounting import models as accounting_models
    from modules.website_builder import models as website_builder_models
    from modules.fashion import models as fashion_models

    Base.metadata.create_all(bind=engine)

    # Run column migrations for existing tables
    run_column_migrations()


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
    

# from pathlib import Path
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker, declarative_base

# # Define the path for the SQLite database file
# # It will be created in the current working directory
# DATABASE_FILE = "boneka.db"
# SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_FILE}"

# # Create the SQLAlchemy engine for SQLite
# # The 'echo=True' will log all SQL statements to the console, useful for debugging
# engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True)

# # Configure a local session class
# # autocommit=False means changes aren't saved until commit() is called
# # autoflush=False means objects aren't flushed to the database until commit() or query
# # bind=engine connects this session to our SQLite database engine
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# # Base class for your declarative models
# # Your database tables will inherit from this Base
# Base = declarative_base()

# def get_db():
#     """
#     Dependency to get a database session.
#     This function provides a database session that can be used in your application.
#     It ensures the session is properly closed after use, even if errors occur.
#     """
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()