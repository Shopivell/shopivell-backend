# modules/agent/credits.py
"""Token wallet for the agent: metered LLM/tool usage deducted from a per-user
balance, with an append-only ledger (AgentCreditLedger)."""
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.agent.models import AgentCreditLedger

# Rough chars-per-token for en-ish text; good enough for pre-flight estimates
# (real usage from the API response is what gets charged where available).
_CHARS_PER_TOKEN = 4


class InsufficientTokens(Exception):
    """Raised when a turn would need more tokens than the user has left."""
    def __init__(self, balance: int, needed: int):
        self.balance = balance
        self.needed = needed
        super().__init__(f"need {needed} tokens, balance {balance}")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def get_balance(db: Session, user_id: str) -> int:
    row = (db.query(AgentCreditLedger)
           .filter(AgentCreditLedger.user_id == user_id)
           .order_by(AgentCreditLedger.created_at.desc(), AgentCreditLedger.id.desc())
           .first())
    return int(row.balance_after) if row else 0


def topup(db: Session, user_id: str, amount: int, reason: str = "topup", detail: str = "",
          store_id: Optional[str] = None) -> int:
    if amount <= 0:
        raise ValueError("amount must be positive")
    balance = get_balance(db, user_id) + int(amount)
    db.add(AgentCreditLedger(user_id=user_id, store_id=store_id, delta=int(amount), balance_after=balance,
                             reason=reason, detail=detail[:255]))
    db.commit()
    return balance


def charge(db: Session, user_id: str, amount: int, reason: str, detail: str = "",
           allow_negative: bool = False, store_id: Optional[str] = None) -> int:
    """Deduct tokens and append a ledger row. Returns the new balance.
    Raises InsufficientTokens when amount > balance (unless allow_negative)."""
    amount = int(amount)
    if amount <= 0:
        return get_balance(db, user_id)
    balance = get_balance(db, user_id)
    if not allow_negative and amount > balance:
        raise InsufficientTokens(balance, amount)
    new_balance = balance - amount
    db.add(AgentCreditLedger(user_id=user_id, store_id=store_id, delta=-amount, balance_after=new_balance,
                             reason=reason[:60], detail=detail[:255]))
    db.commit()
    return new_balance


def charge_with_overdraft(db: Session, user_id: str, amount: int, reason: str, detail: str = "",
                          store_id: Optional[str] = None) -> Tuple[int, bool]:
    """Charge, letting the balance go negative for this turn (the work is already done),
    but only if the user had a positive balance when the turn started. Returns
    (new_balance, went_negative)."""
    amount = int(amount)
    balance = get_balance(db, user_id)
    had_credit = balance > 0
    new_balance = balance - amount
    db.add(AgentCreditLedger(user_id=user_id, store_id=store_id, delta=-amount, balance_after=new_balance,
                             reason=reason[:60], detail=detail[:255]))
    db.commit()
    return new_balance, had_credit and new_balance < 0


def charge_system(db: Session, user_id: str, amount: int, reason: str, detail: str = "",
                  store_id: Optional[str] = None) -> Optional[int]:
    """System-wide AI metering outside the agent chat: the campaign pipeline
    (research + angles), campaign/asset ad images, and Brand DNA generation all
    draw on the same wallet.

    Zero-balance users are NOT charged (free tier keeps working — no hard gate
    outside the agent's explicit confirm flow); anyone with credit pays per use.
    Never raises: metering must not break the feature it wraps. Returns the new
    balance, or None when nothing was charged.
    """
    try:
        if get_balance(db, user_id) <= 0:
            return None
        new_balance, _ = charge_with_overdraft(db, user_id, amount, reason, detail, store_id=store_id)
        return new_balance
    except Exception:
        return None


def history(db: Session, user_id: str, limit: int = 50) -> list:
    rows = (db.query(AgentCreditLedger)
            .filter(AgentCreditLedger.user_id == user_id)
            .order_by(AgentCreditLedger.created_at.desc(), AgentCreditLedger.id.desc())
            .limit(limit).all())
    return [{
        "id": str(r.id), "delta": r.delta, "balance_after": r.balance_after,
        "store_id": str(r.store_id) if r.store_id else None,
        "reason": r.reason, "detail": r.detail,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


def usage_by_store(db: Session, user_id: str, days: int = 30) -> dict:
    """Tokens spent per store over the last `days`, split by action. Usage with no store
    (agent chat outside a store, older rows) is grouped under store_id None. This is the
    per-store (and so per-customer) usage report: a user running many stores shows many rows."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.query(AgentCreditLedger.store_id, AgentCreditLedger.reason,
                     func.sum(-AgentCreditLedger.delta), func.count(AgentCreditLedger.id))
            .filter(AgentCreditLedger.user_id == user_id, AgentCreditLedger.delta < 0,
                    AgentCreditLedger.created_at >= since)
            .group_by(AgentCreditLedger.store_id, AgentCreditLedger.reason).all())
    stores: dict = {}
    for store_id, reason, spent, uses in rows:
        key = str(store_id) if store_id else None
        entry = stores.setdefault(key, {"store_id": key, "spent": 0, "uses": 0, "by_action": {}})
        entry["spent"] += int(spent or 0)
        entry["uses"] += int(uses or 0)
        entry["by_action"][reason] = {"spent": int(spent or 0), "uses": int(uses or 0)}
    names = {}
    ids = [k for k in stores if k]
    if ids:
        try:
            from modules.stores.models import Store
            names = {str(st.id): st.store_name for st in db.query(Store).filter(Store.id.in_(ids)).all()}
        except Exception:
            names = {}
    for key, entry in stores.items():
        entry["store_name"] = names.get(key) if key else None
    ordered = sorted(stores.values(), key=lambda e: e["spent"], reverse=True)
    return {"days": days, "total_spent": sum(e["spent"] for e in ordered), "stores": ordered}
