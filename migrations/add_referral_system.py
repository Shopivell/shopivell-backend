"""
Migration: Add referral system tables.

Creates the following tables:
- user_referral_codes: Unique referral codes for each user
- referrals: Tracks referral relationships
- user_token_balances: Token balance for each user
- token_transactions: Ledger of token changes

Usage:
    python migrations/add_referral_system.py
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine, SessionLocal


def migrate():
    """Create referral system tables."""

    db = SessionLocal()

    try:
        # Create ENUM types first
        print("Creating ENUM types...")

        # Check if types already exist
        type_check = text("""
            SELECT typname FROM pg_type
            WHERE typname IN ('referralstatus', 'referralsource', 'tokentransactiontype')
        """)
        result = db.execute(type_check)
        existing_types = [row[0] for row in result]

        if 'referralstatus' not in existing_types:
            db.execute(text("""
                CREATE TYPE referralstatus AS ENUM ('pending', 'signed_up', 'rewarded', 'expired')
            """))
            print("[OK] Created referralstatus ENUM")
        else:
            print("[OK] referralstatus ENUM already exists")

        if 'referralsource' not in existing_types:
            db.execute(text("""
                CREATE TYPE referralsource AS ENUM ('email', 'whatsapp', 'facebook', 'twitter', 'linkedin', 'copy', 'other')
            """))
            print("[OK] Created referralsource ENUM")
        else:
            print("[OK] referralsource ENUM already exists")

        if 'tokentransactiontype' not in existing_types:
            db.execute(text("""
                CREATE TYPE tokentransactiontype AS ENUM ('earned', 'redeemed', 'expired', 'bonus', 'adjustment')
            """))
            print("[OK] Created tokentransactiontype ENUM")
        else:
            print("[OK] tokentransactiontype ENUM already exists")

        db.commit()

        # Create user_referral_codes table
        print("\nCreating user_referral_codes table...")
        table_check = text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'user_referral_codes'
        """)
        if not db.execute(table_check).fetchone():
            db.execute(text("""
                CREATE TABLE user_referral_codes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    referral_code VARCHAR(20) NOT NULL UNIQUE,
                    total_referrals INTEGER DEFAULT 0,
                    successful_referrals INTEGER DEFAULT 0,
                    total_tokens_earned INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.execute(text("CREATE INDEX idx_user_referral_codes_user_id ON user_referral_codes(user_id)"))
            db.execute(text("CREATE INDEX idx_user_referral_codes_code ON user_referral_codes(referral_code)"))
            print("[OK] Created user_referral_codes table")
        else:
            print("[OK] user_referral_codes table already exists")

        db.commit()

        # Create referrals table
        print("\nCreating referrals table...")
        table_check = text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'referrals'
        """)
        if not db.execute(table_check).fetchone():
            db.execute(text("""
                CREATE TABLE referrals (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    referrer_code_id UUID NOT NULL REFERENCES user_referral_codes(id) ON DELETE CASCADE,
                    referred_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
                    status referralstatus DEFAULT 'pending',
                    source referralsource DEFAULT 'other',
                    tokens_awarded INTEGER DEFAULT 0,
                    referred_email VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    signed_up_at TIMESTAMP,
                    rewarded_at TIMESTAMP
                )
            """))
            db.execute(text("CREATE INDEX idx_referrals_referrer_code_id ON referrals(referrer_code_id)"))
            db.execute(text("CREATE INDEX idx_referrals_referred_user_id ON referrals(referred_user_id)"))
            print("[OK] Created referrals table")
        else:
            print("[OK] referrals table already exists")

        db.commit()

        # Create user_token_balances table
        print("\nCreating user_token_balances table...")
        table_check = text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'user_token_balances'
        """)
        if not db.execute(table_check).fetchone():
            db.execute(text("""
                CREATE TABLE user_token_balances (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    available_tokens INTEGER DEFAULT 0,
                    total_earned INTEGER DEFAULT 0,
                    total_redeemed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.execute(text("CREATE INDEX idx_user_token_balances_user_id ON user_token_balances(user_id)"))
            print("[OK] Created user_token_balances table")
        else:
            print("[OK] user_token_balances table already exists")

        db.commit()

        # Create token_transactions table
        print("\nCreating token_transactions table...")
        table_check = text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'token_transactions'
        """)
        if not db.execute(table_check).fetchone():
            db.execute(text("""
                CREATE TABLE token_transactions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    token_balance_id UUID NOT NULL REFERENCES user_token_balances(id) ON DELETE CASCADE,
                    transaction_type tokentransactiontype NOT NULL,
                    amount INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    reference_type VARCHAR(50),
                    reference_id UUID,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.execute(text("CREATE INDEX idx_token_transactions_balance_id ON token_transactions(token_balance_id)"))
            print("[OK] Created token_transactions table")
        else:
            print("[OK] token_transactions table already exists")

        db.commit()
        print("\n[SUCCESS] Migration completed!")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Migration failed: {e}")
        raise
    finally:
        db.close()


def rollback():
    """Remove referral system tables (rollback migration)."""

    db = SessionLocal()

    try:
        print("Rolling back: Removing referral system tables...")

        # Drop tables in reverse order (respecting foreign key constraints)
        db.execute(text("DROP TABLE IF EXISTS token_transactions CASCADE"))
        print("[OK] Dropped token_transactions table")

        db.execute(text("DROP TABLE IF EXISTS user_token_balances CASCADE"))
        print("[OK] Dropped user_token_balances table")

        db.execute(text("DROP TABLE IF EXISTS referrals CASCADE"))
        print("[OK] Dropped referrals table")

        db.execute(text("DROP TABLE IF EXISTS user_referral_codes CASCADE"))
        print("[OK] Dropped user_referral_codes table")

        # Drop ENUM types
        db.execute(text("DROP TYPE IF EXISTS tokentransactiontype"))
        db.execute(text("DROP TYPE IF EXISTS referralsource"))
        db.execute(text("DROP TYPE IF EXISTS referralstatus"))
        print("[OK] Dropped ENUM types")

        db.commit()
        print("\n[SUCCESS] Rollback completed!")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Rollback failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Referral system migration")
    parser.add_argument("--rollback", action="store_true", help="Rollback the migration")
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
