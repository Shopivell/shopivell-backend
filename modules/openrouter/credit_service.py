# modules/openrouter/credit_service.py
"""Per-store AI credit wallet: monthly tier allowance + purchased top-ups, with ledger.

Each function opens its own DB session (fire-and-forget, like track_usage) so credit
bookkeeping never interferes with the caller's request transaction and concurrent
callers don't race to create duplicate wallets.

Consumption deducts from the monthly tier allowance first, then from purchased credits.
When the balance hits zero the bot stops answering until the owner tops up.
"""

import logging
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from database import SessionLocal
from .models import StoreAICreditWallet, AICreditTransaction
from .credits import monthly_allowance, credits_for_cost

logger = logging.getLogger(__name__)


def _get_package(store_id: str, db) -> str:
    """Resolve the store's active subscription tier (defaults to 'free')."""
    from modules.payment.models import StoreSubscription
    sub = (
        db.query(StoreSubscription)
        .filter(
            StoreSubscription.store_id == store_id,
            StoreSubscription.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not sub:
        return "free"
    return sub.package_name.value if hasattr(sub.package_name, "value") else str(sub.package_name)


def _available(w: StoreAICreditWallet) -> int:
    return max(0, w.allowance_total - w.allowance_used) + w.purchased_balance


def _ensure_monthly_allowance(w: StoreAICreditWallet, package: str, db) -> None:
    """Grant/reset this month's tier allowance if not already granted for the current month."""
    now = datetime.utcnow()
    already_granted = (
        w.period_year == now.year and w.period_month == now.month and w.allowance_total > 0
    )
    if already_granted:
        return
    grant = monthly_allowance(package)
    w.allowance_total = grant
    w.allowance_used = 0
    w.period_year = now.year
    w.period_month = now.month
    w.lifetime_granted = (w.lifetime_granted or 0) + grant
    db.add(
        AICreditTransaction(
            store_id=w.store_id,
            kind="grant",
            credits=grant,
            balance_after=_available(w),
            reason=f"Monthly {package} allowance",
        )
    )


def _get_or_create_wallet(store_id: str, db, package: str) -> StoreAICreditWallet:
    w = (
        db.query(StoreAICreditWallet)
        .filter(StoreAICreditWallet.store_id == store_id)
        .first()
    )
    if w is None:
        w = StoreAICreditWallet(store_id=store_id)
        db.add(w)
        db.flush()
    _ensure_monthly_allowance(w, package, db)
    return w


def _balance_dict(w: StoreAICreditWallet, package: str) -> Dict[str, Any]:
    return {
        "package": package,
        "available_credits": _available(w),
        "allowance_total": w.allowance_total,
        "allowance_remaining": max(0, w.allowance_total - w.allowance_used),
        "purchased_balance": w.purchased_balance,
        "lifetime_consumed": w.lifetime_consumed,
        "lifetime_purchased": w.lifetime_purchased,
        "period": f"{w.period_year}-{w.period_month:02d}",
    }


def get_balance(store_id: str) -> Dict[str, Any]:
    """Current credit balance for a store (creates wallet + grants monthly allowance on first read)."""
    db = SessionLocal()
    try:
        package = _get_package(store_id, db)
        w = _get_or_create_wallet(store_id, db, package)
        info = _balance_dict(w, package)
        db.commit()
        return info
    except Exception as e:
        db.rollback()
        logger.error(f"[Credits] get_balance failed for {store_id}: {e}")
        # Fail open with a conservative default so a bookkeeping bug can't brick the bot
        return {"package": "free", "available_credits": 0, "allowance_total": 0,
                "allowance_remaining": 0, "purchased_balance": 0, "lifetime_consumed": 0,
                "lifetime_purchased": 0, "period": "", "error": str(e)}
    finally:
        db.close()


def has_credits(store_id: str, minimum: int = 1) -> Tuple[bool, Dict[str, Any]]:
    """True if the store has at least `minimum` credits available."""
    info = get_balance(store_id)
    return (info.get("available_credits", 0) >= minimum, info)


def consume_for_cost(store_id: str, cost_usd: float, reference: Optional[str] = None) -> int:
    """Deduct credits for a completed message (allowance first, then purchased). Returns credits charged."""
    credits = credits_for_cost(cost_usd)
    db = SessionLocal()
    try:
        package = _get_package(store_id, db)
        w = _get_or_create_wallet(store_id, db, package)

        remaining = credits
        from_allowance = min(max(0, w.allowance_total - w.allowance_used), remaining)
        w.allowance_used += from_allowance
        remaining -= from_allowance
        if remaining > 0:
            from_purchased = min(w.purchased_balance, remaining)
            w.purchased_balance -= from_purchased
            remaining -= from_purchased
        # remaining > 0 => store didn't have enough; we charge what they had and floor at 0.
        charged = credits - remaining
        w.lifetime_consumed = (w.lifetime_consumed or 0) + charged

        db.add(
            AICreditTransaction(
                store_id=store_id,
                kind="consume",
                credits=-charged,
                balance_after=_available(w),
                reason="WhatsApp bot message",
                reference=reference,
                extra={"cost_usd": round(cost_usd, 6), "credits_requested": credits},
            )
        )
        db.commit()
        return charged
    except Exception as e:
        db.rollback()
        logger.error(f"[Credits] consume failed for {store_id}: {e}")
        return 0
    finally:
        db.close()


def add_credits(
    store_id: str,
    credits: int,
    kind: str = "purchase",
    reason: str = "Top-up",
    reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Add purchased/granted credits to a store wallet (top-up). Returns new balance info."""
    if credits <= 0:
        raise ValueError("credits must be positive")
    db = SessionLocal()
    try:
        package = _get_package(store_id, db)
        w = _get_or_create_wallet(store_id, db, package)
        w.purchased_balance += credits
        if kind == "purchase":
            w.lifetime_purchased = (w.lifetime_purchased or 0) + credits
        db.add(
            AICreditTransaction(
                store_id=store_id,
                kind=kind,
                credits=credits,
                balance_after=_available(w),
                reason=reason,
                reference=reference,
            )
        )
        info = _balance_dict(w, package)
        db.commit()
        return info
    finally:
        db.close()
