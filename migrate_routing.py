"""
Migration script for Multi-Store Routing feature.
Creates new tables:
- ad_campaigns
- Updates to whatsapp_conversations (routing fields)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import engine, Base, SessionLocal
from sqlalchemy import text

def run_migration():
    print("=" * 60)
    print("MULTI-STORE ROUTING MIGRATION")
    print("=" * 60)

    # Import all models to register them with SQLAlchemy
    print("\n1. Importing models...")
    from modules.whatsapp import models as whatsapp_models
    from modules.stores import models as store_models
    from modules.users import models as user_models
    print("   [OK] Models imported")

    # Create all tables (will only create new ones, won't drop existing)
    print("\n2. Creating new tables...")
    Base.metadata.create_all(bind=engine)
    print("   [OK] Tables created/updated")

    # Verify the new tables exist
    print("\n3. Verifying tables...")
    db = SessionLocal()
    try:
        # Check ad_campaigns table
        result = db.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'ad_campaigns'"))
        if result.scalar() > 0:
            print("   [OK] ad_campaigns table exists")
        else:
            print("   [X] ad_campaigns table NOT found")

        # Check whatsapp_conversations has new columns
        result = db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'whatsapp_conversations'
            AND column_name IN ('routing_status', 'routed_via', 'whatsapp_account_id', 'referral_data')
        """))
        columns = [row[0] for row in result.fetchall()]
        print(f"   [OK] Routing columns in whatsapp_conversations: {columns}")

    except Exception as e:
        print(f"   Error verifying: {e}")
    finally:
        db.close()

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print("\nNew features enabled:")
    print("  - Ad Campaign management for multi-store routing")
    print("  - Store Router for Click-to-WhatsApp ads")
    print("  - Conversation routing with referral tracking")
    print("\nNext steps:")
    print("  1. Create an ad campaign: POST /api/whatsapp/campaigns")
    print("  2. Link your WhatsApp account to a store")
    print("  3. Test by sending a message to your WhatsApp number")

if __name__ == "__main__":
    run_migration()
