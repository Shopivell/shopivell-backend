# modules/openrouter/ai_usage_service.py
"""Service for tracking AI token usage and enforcing limits."""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from database import SessionLocal
from modules.openrouter.models import AIUsageLog, StoreAIUsageSummary
from modules.openrouter.pricing import calculate_cost

logger = logging.getLogger(__name__)

# AI call limits per package tier (monthly)
AI_CALL_LIMITS = {
    "free": 50,
    "premium": 500,
    "business": 5000,
}

# AI token limits per package tier (monthly)
AI_TOKEN_LIMITS = {
    "free": 100_000,
    "premium": 1_000_000,
    "business": 10_000_000,
}


def track_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    agent_name: str = "unknown",
    store_id: Optional[str] = None,
    user_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    request_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record an AI usage log entry and update the monthly summary.
    Fire-and-forget: opens own DB session, never raises.
    """
    try:
        cost = calculate_cost(model, prompt_tokens, completion_tokens)

        db = SessionLocal()
        try:
            # 1. Create detailed log entry
            log_entry = AIUsageLog(
                store_id=store_id,
                user_id=user_id,
                campaign_id=campaign_id,
                agent_name=agent_name,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
                success=success,
                error_message=error_message,
                request_metadata=request_metadata or {},
            )
            db.add(log_entry)

            # 2. Update monthly summary
            if store_id:
                now = datetime.utcnow()
                summary = db.query(StoreAIUsageSummary).filter(
                    StoreAIUsageSummary.store_id == store_id,
                    StoreAIUsageSummary.year == now.year,
                    StoreAIUsageSummary.month == now.month,
                ).first()

                if summary:
                    summary.total_calls += 1
                    summary.total_prompt_tokens += prompt_tokens
                    summary.total_completion_tokens += completion_tokens
                    summary.total_tokens += total_tokens
                    summary.total_cost_usd += cost

                    agent_calls = dict(summary.calls_by_agent or {})
                    agent_calls[agent_name] = agent_calls.get(agent_name, 0) + 1
                    summary.calls_by_agent = agent_calls

                    agent_costs = dict(summary.cost_by_agent or {})
                    agent_costs[agent_name] = agent_costs.get(agent_name, 0) + cost
                    summary.cost_by_agent = agent_costs
                else:
                    summary = StoreAIUsageSummary(
                        store_id=store_id,
                        year=now.year,
                        month=now.month,
                        total_calls=1,
                        total_prompt_tokens=prompt_tokens,
                        total_completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        total_cost_usd=cost,
                        calls_by_agent={agent_name: 1},
                        cost_by_agent={agent_name: cost},
                    )
                    db.add(summary)

            db.commit()

            logger.info(
                f"[AIUsage] {agent_name} | {model} | "
                f"tokens={total_tokens} | cost=${cost:.6f} | "
                f"store={store_id or 'none'}"
            )

        except Exception as e:
            db.rollback()
            logger.error(f"[AIUsage] Failed to save usage log: {e}")
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[AIUsage] track_usage error: {e}")


def check_usage_limit(
    store_id: str,
    db: Optional[Session] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Check if a store has remaining AI usage quota.
    Returns: (allowed, message, usage_info)
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        # Get store subscription
        from modules.payment.models import StoreSubscription
        subscription = db.query(StoreSubscription).filter(
            StoreSubscription.store_id == store_id,
            StoreSubscription.is_active == True,
        ).first()

        package = "free"
        if subscription:
            package = subscription.package_name.value if hasattr(subscription.package_name, 'value') else str(subscription.package_name)

        call_limit = AI_CALL_LIMITS.get(package, AI_CALL_LIMITS["free"])
        token_limit = AI_TOKEN_LIMITS.get(package, AI_TOKEN_LIMITS["free"])

        # Get current month's usage
        now = datetime.utcnow()
        summary = db.query(StoreAIUsageSummary).filter(
            StoreAIUsageSummary.store_id == store_id,
            StoreAIUsageSummary.year == now.year,
            StoreAIUsageSummary.month == now.month,
        ).first()

        current_calls = summary.total_calls if summary else 0
        current_tokens = summary.total_tokens if summary else 0
        current_cost = summary.total_cost_usd if summary else 0.0

        usage_info = {
            "package": package,
            "current_calls": current_calls,
            "call_limit": call_limit,
            "calls_remaining": max(0, call_limit - current_calls),
            "current_tokens": current_tokens,
            "token_limit": token_limit,
            "tokens_remaining": max(0, token_limit - current_tokens),
            "current_cost_usd": round(current_cost, 4),
        }

        if current_calls >= call_limit:
            next_tier = _next_tier(package)
            return (
                False,
                f"AI call limit reached ({current_calls}/{call_limit}). "
                f"Upgrade to {next_tier} for more.",
                usage_info,
            )

        if current_tokens >= token_limit:
            next_tier = _next_tier(package)
            return (
                False,
                f"AI token limit reached ({current_tokens}/{token_limit}). "
                f"Upgrade to {next_tier} for more.",
                usage_info,
            )

        return (True, "OK", usage_info)

    finally:
        if close_db:
            db.close()


def require_ai_quota(store_id: str, db: Session) -> Dict[str, Any]:
    """
    FastAPI-friendly check. Raises HTTP 429 if limit exceeded.
    Use as pre-check in router endpoints.
    """
    allowed, message, usage_info = check_usage_limit(store_id, db)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "ai_usage_limit_exceeded",
                "message": message,
                "usage": usage_info,
            }
        )
    return usage_info


def get_usage_dashboard(
    store_id: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Get AI usage dashboard data for a store."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        now = datetime.utcnow()
        target_year = year or now.year
        target_month = month or now.month

        # Current month summary
        summary = db.query(StoreAIUsageSummary).filter(
            StoreAIUsageSummary.store_id == store_id,
            StoreAIUsageSummary.year == target_year,
            StoreAIUsageSummary.month == target_month,
        ).first()

        # Get subscription info
        from modules.payment.models import StoreSubscription
        subscription = db.query(StoreSubscription).filter(
            StoreSubscription.store_id == store_id,
        ).first()

        package = "free"
        if subscription:
            package = subscription.package_name.value if hasattr(subscription.package_name, 'value') else str(subscription.package_name)

        call_limit = AI_CALL_LIMITS.get(package, AI_CALL_LIMITS["free"])
        token_limit = AI_TOKEN_LIMITS.get(package, AI_TOKEN_LIMITS["free"])

        total_calls = summary.total_calls if summary else 0
        total_tokens = summary.total_tokens if summary else 0

        # Recent detailed logs (last 20)
        recent_logs = db.query(AIUsageLog).filter(
            AIUsageLog.store_id == store_id,
        ).order_by(AIUsageLog.created_at.desc()).limit(20).all()

        return {
            "period": {"year": target_year, "month": target_month},
            "package": package,
            "limits": {
                "ai_calls": call_limit,
                "ai_tokens": token_limit,
            },
            "usage": {
                "total_calls": total_calls,
                "total_tokens": total_tokens,
                "total_prompt_tokens": summary.total_prompt_tokens if summary else 0,
                "total_completion_tokens": summary.total_completion_tokens if summary else 0,
                "total_cost_usd": round(summary.total_cost_usd, 4) if summary else 0.0,
                "calls_by_agent": summary.calls_by_agent if summary else {},
                "cost_by_agent": summary.cost_by_agent if summary else {},
            },
            "utilization": {
                "calls_percent": round((total_calls / call_limit) * 100, 1) if call_limit else 0,
                "tokens_percent": round((total_tokens / token_limit) * 100, 1) if token_limit else 0,
            },
            "recent_logs": [
                {
                    "id": str(log.id),
                    "agent_name": log.agent_name,
                    "model": log.model,
                    "total_tokens": log.total_tokens,
                    "cost_usd": round(log.cost_usd, 6),
                    "success": log.success,
                    "created_at": log.created_at.isoformat(),
                }
                for log in recent_logs
            ],
        }

    finally:
        if close_db:
            db.close()


def _next_tier(current: str) -> str:
    """Get the name of the next subscription tier."""
    if current == "free":
        return "Premium"
    elif current == "premium":
        return "Business"
    return "a higher plan"
