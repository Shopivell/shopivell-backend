"""
Migration: Add micro-strategy tables.

Creates:
- micro_strategies: Top-level Lexi test plans
- micro_strategy_phases: Individual testing phases (HEADLINE, IMAGE, AUDIENCE, OFFER)
- phase_variations: Variations within each phase (5 per phase)
- pixel_readiness_trackers: Traffic-to-Lead-Gen auto-switch tracking

Usage:
    python migrations/add_micro_strategy.py
    python migrations/add_micro_strategy.py --rollback
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine, SessionLocal


def migrate():
    """Create micro-strategy tables."""
    db = SessionLocal()

    try:
        print("Creating micro-strategy tables...")

        # 1. micro_strategies
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS micro_strategies (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                ad_account_id UUID NOT NULL REFERENCES meta_ad_accounts(id),
                store_id UUID NOT NULL REFERENCES stores(id),
                name VARCHAR(255) NOT NULL,
                status VARCHAR(50) DEFAULT 'DRAFT',
                winner_metric VARCHAR(50) DEFAULT 'LOWEST_CPA',
                daily_budget_cents INTEGER DEFAULT 1000,
                max_spend_per_phase_cents INTEGER DEFAULT 5000,
                min_days_per_phase INTEGER DEFAULT 3,
                max_days_per_phase INTEGER DEFAULT 7,
                variations_per_phase INTEGER DEFAULT 5,
                source_url TEXT,
                source_campaign_id UUID,
                product_context JSONB,
                current_phase_number INTEGER DEFAULT 0,
                winning_headline TEXT,
                winning_image_url TEXT,
                winning_audience JSONB,
                winning_offer TEXT,
                learnings JSONB,
                meta_campaign_id VARCHAR(255),
                destination_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        print("  [OK] micro_strategies")

        # 2. micro_strategy_phases
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS micro_strategy_phases (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                strategy_id UUID NOT NULL REFERENCES micro_strategies(id) ON DELETE CASCADE,
                phase_number INTEGER NOT NULL,
                phase_type VARCHAR(50) NOT NULL,
                status VARCHAR(50) DEFAULT 'PENDING',
                budget_per_variation_cents INTEGER,
                total_spend_cents INTEGER DEFAULT 0,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                winner_variation_id UUID,
                winner_value TEXT,
                winner_metadata JSONB,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        print("  [OK] micro_strategy_phases")

        # 3. phase_variations
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS phase_variations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                phase_id UUID NOT NULL REFERENCES micro_strategy_phases(id) ON DELETE CASCADE,
                variation_number INTEGER NOT NULL,
                variation_name VARCHAR(255) NOT NULL,
                variable_type VARCHAR(50) NOT NULL,
                variable_value TEXT NOT NULL,
                variable_metadata JSONB,
                meta_adset_id VARCHAR(255),
                meta_ad_id VARCHAR(255),
                meta_creative_id VARCHAR(255),
                impressions INTEGER DEFAULT 0,
                clicks INTEGER DEFAULT 0,
                spend_cents INTEGER DEFAULT 0,
                conversions INTEGER DEFAULT 0,
                ctr FLOAT DEFAULT 0.0,
                cpc FLOAT DEFAULT 0.0,
                cpa FLOAT DEFAULT 0.0,
                roas FLOAT DEFAULT 0.0,
                is_winner BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        print("  [OK] phase_variations")

        # 4. pixel_readiness_trackers
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS pixel_readiness_trackers (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                ad_account_id UUID NOT NULL REFERENCES meta_ad_accounts(id),
                store_id UUID NOT NULL REFERENCES stores(id),
                micro_strategy_id UUID REFERENCES micro_strategies(id) ON DELETE SET NULL,
                pixel_id VARCHAR(255) NOT NULL,
                pixel_name VARCHAR(255),
                current_objective VARCHAR(50) DEFAULT 'OUTCOME_TRAFFIC',
                switch_status VARCHAR(50) DEFAULT 'TRAFFIC_PHASE',
                traffic_campaign_id VARCHAR(255),
                leadgen_campaign_id VARCHAR(255),
                page_view_count INTEGER DEFAULT 0,
                view_content_count INTEGER DEFAULT 0,
                lead_count INTEGER DEFAULT 0,
                add_to_cart_count INTEGER DEFAULT 0,
                purchase_count INTEGER DEFAULT 0,
                total_optimization_events INTEGER DEFAULT 0,
                required_events INTEGER DEFAULT 50,
                required_days INTEGER DEFAULT 7,
                event_window_days INTEGER DEFAULT 7,
                traffic_started_at TIMESTAMP,
                switch_triggered_at TIMESTAMP,
                leadgen_started_at TIMESTAMP,
                audience_snapshot JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        print("  [OK] pixel_readiness_trackers")

        # Create indexes
        print("Creating indexes...")
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_micro_strategies_store_id ON micro_strategies(store_id);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_micro_strategies_status ON micro_strategies(status);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_micro_strategies_ad_account ON micro_strategies(ad_account_id);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_ms_phases_strategy_id ON micro_strategy_phases(strategy_id);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_phase_variations_phase_id ON phase_variations(phase_id);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_pixel_trackers_store_id ON pixel_readiness_trackers(store_id);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_pixel_trackers_status ON pixel_readiness_trackers(switch_status);"))
        print("  [OK] Indexes created")

        db.commit()
        print("\n[SUCCESS] Micro-strategy migration completed!")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Migration failed: {e}")
        raise
    finally:
        db.close()


def rollback():
    """Drop micro-strategy tables in reverse order."""
    db = SessionLocal()

    try:
        print("Rolling back micro-strategy tables...")
        db.execute(text("DROP TABLE IF EXISTS pixel_readiness_trackers CASCADE;"))
        print("  [OK] Dropped pixel_readiness_trackers")
        db.execute(text("DROP TABLE IF EXISTS phase_variations CASCADE;"))
        print("  [OK] Dropped phase_variations")
        db.execute(text("DROP TABLE IF EXISTS micro_strategy_phases CASCADE;"))
        print("  [OK] Dropped micro_strategy_phases")
        db.execute(text("DROP TABLE IF EXISTS micro_strategies CASCADE;"))
        print("  [OK] Dropped micro_strategies")

        db.commit()
        print("\n[SUCCESS] Rollback completed!")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Rollback failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Micro-strategy migration")
    parser.add_argument("--rollback", action="store_true", help="Rollback the migration")
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
