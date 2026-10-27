"""Migration: create AI credit wallet + transaction ledger tables.

Run:  python -m migrations.add_ai_credits
Idempotent — only creates tables that don't already exist.
"""

from database import engine, Base
# Import the models so they register on Base.metadata
from modules.openrouter.models import StoreAICreditWallet, AICreditTransaction


def run():
    Base.metadata.create_all(
        bind=engine,
        tables=[
            StoreAICreditWallet.__table__,
            AICreditTransaction.__table__,
        ],
    )
    print("[OK] Created tables: store_ai_credit_wallets, ai_credit_transactions")


if __name__ == "__main__":
    run()
