# modules/openrouter/router.py
"""API endpoints for AI usage tracking dashboard."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, CurrentUser
from .ai_usage_service import get_usage_dashboard, check_usage_limit
from .credit_service import get_balance
from .models import AIUsageLog, AICreditTransaction

logger = logging.getLogger(__name__)

ai_usage_router = APIRouter(prefix="/api/ai-usage", tags=["AI Usage"])


@ai_usage_router.get("/dashboard")
async def get_ai_usage_dashboard(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get AI usage dashboard for the current user's store."""
    if not current_user.store_id:
        raise HTTPException(status_code=400, detail="No store associated with user")

    dashboard = get_usage_dashboard(
        store_id=current_user.store_id,
        year=year,
        month=month,
        db=db,
    )
    return dashboard


@ai_usage_router.get("/quota")
async def get_ai_quota(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check remaining AI quota for the current user's store."""
    if not current_user.store_id:
        raise HTTPException(status_code=400, detail="No store associated with user")

    allowed, message, usage_info = check_usage_limit(current_user.store_id, db)
    return {
        "allowed": allowed,
        "message": message,
        **usage_info,
    }


@ai_usage_router.get("/credits")
async def get_ai_credits(
    current_user: CurrentUser = Depends(get_current_user),
):
    """Current AI message-credit balance for the store (monthly allowance + purchased)."""
    if not current_user.store_id:
        raise HTTPException(status_code=400, detail="No store associated with user")

    info = get_balance(str(current_user.store_id))
    info["needs_topup"] = info.get("available_credits", 0) <= 0
    return info


@ai_usage_router.get("/credits/transactions")
async def get_ai_credit_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Paginated AI credit ledger (grants, purchases, consumption) for the store."""
    if not current_user.store_id:
        raise HTTPException(status_code=400, detail="No store associated with user")

    query = db.query(AICreditTransaction).filter(
        AICreditTransaction.store_id == current_user.store_id
    )
    total = query.count()
    txns = query.order_by(AICreditTransaction.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "transactions": [
            {
                "id": str(t.id),
                "kind": t.kind,
                "credits": t.credits,
                "balance_after": t.balance_after,
                "reason": t.reason,
                "reference": t.reference,
                "created_at": t.created_at.isoformat(),
            }
            for t in txns
        ],
    }


@ai_usage_router.get("/history")
async def get_ai_usage_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    agent_name: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get paginated AI usage log history for the current store."""
    if not current_user.store_id:
        raise HTTPException(status_code=400, detail="No store associated with user")

    query = db.query(AIUsageLog).filter(
        AIUsageLog.store_id == current_user.store_id
    )

    if agent_name:
        query = query.filter(AIUsageLog.agent_name == agent_name)

    total = query.count()
    logs = query.order_by(AIUsageLog.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "logs": [
            {
                "id": str(log.id),
                "agent_name": log.agent_name,
                "model": log.model,
                "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens,
                "total_tokens": log.total_tokens,
                "cost_usd": round(log.cost_usd, 6),
                "success": log.success,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
    }
