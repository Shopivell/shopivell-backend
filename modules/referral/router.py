# modules/referral/router.py
"""
API endpoints for referral system.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from dependencies import get_current_user
from modules.users.models import User

from .service import ReferralService
from .models import ReferralSource
from .constants import TOKEN_VALUE_USD, MAX_TOKENS_PER_PAYMENT
from .schemas import (
    ReferralCodeResponse,
    ReferralStatsResponse,
    ReferralListResponse,
    ReferralItemResponse,
    ValidateCodeResponse,
    TokenBalanceResponse,
    TokenHistoryResponse,
    TokenTransactionResponse,
    DiscountEstimateResponse,
    ShareLinksResponse,
    TrackShareRequest,
    EstimateDiscountRequest,
    ReferralSourceEnum,
    ReferralStatusEnum
)

referral_router = APIRouter(prefix="/api/referrals", tags=["Referrals"])


# ============ Referral Code Endpoints ============

@referral_router.get("/my-code", response_model=ReferralCodeResponse)
async def get_my_referral_code(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get user's referral code and link.
    Creates a new code if user doesn't have one.
    """
    service = ReferralService(db)
    referral_code = service.get_or_create_referral_code(current_user.id)

    return ReferralCodeResponse(
        referral_code=referral_code.referral_code,
        referral_link=service._generate_referral_link(referral_code.referral_code),
        total_referrals=referral_code.total_referrals,
        successful_referrals=referral_code.successful_referrals,
        total_tokens_earned=referral_code.total_tokens_earned,
        is_active=referral_code.is_active
    )


@referral_router.get("/share-links", response_model=ShareLinksResponse)
async def get_share_links(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get pre-formatted share links for different platforms.
    """
    service = ReferralService(db)
    referral_code = service.get_or_create_referral_code(current_user.id)
    links = service.generate_share_links(referral_code.referral_code)

    return ShareLinksResponse(**links)


@referral_router.get("/stats", response_model=ReferralStatsResponse)
async def get_referral_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed referral statistics.
    """
    service = ReferralService(db)
    stats = service.get_referral_stats(current_user.id)

    return ReferralStatsResponse(**stats)


@referral_router.get("/list", response_model=ReferralListResponse)
async def list_referrals(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List user's referrals with pagination.
    """
    service = ReferralService(db)
    referrals, total = service.get_referral_list(
        user_id=current_user.id,
        limit=limit,
        offset=offset
    )

    return ReferralListResponse(
        referrals=[
            ReferralItemResponse(
                id=r.id,
                status=ReferralStatusEnum(r.status.value),
                source=ReferralSourceEnum(r.source.value),
                tokens_awarded=r.tokens_awarded,
                referred_email=r.referred_email,
                created_at=r.created_at,
                signed_up_at=r.signed_up_at,
                rewarded_at=r.rewarded_at
            )
            for r in referrals
        ],
        total=total
    )


@referral_router.get("/validate/{code}", response_model=ValidateCodeResponse)
async def validate_referral_code(
    code: str,
    db: Session = Depends(get_db)
):
    """
    Validate a referral code.
    Used on signup page to verify code and show referrer name.
    No authentication required.
    """
    service = ReferralService(db)
    is_valid, referrer_name, message = service.validate_referral_code(code)

    return ValidateCodeResponse(
        is_valid=is_valid,
        referrer_name=referrer_name,
        message=message
    )


@referral_router.post("/track-share")
async def track_share(
    request: TrackShareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Track when user shares their referral link.
    Used for analytics.
    """
    service = ReferralService(db)
    service.track_share(
        user_id=current_user.id,
        source=ReferralSource(request.source.value)
    )

    return {"success": True, "message": "Share tracked"}


# ============ Token Endpoints ============

@referral_router.get("/tokens/balance", response_model=TokenBalanceResponse)
async def get_token_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get user's token balance.
    """
    service = ReferralService(db)
    balance = service.get_or_create_token_balance(current_user.id)

    return TokenBalanceResponse(
        available_tokens=balance.available_tokens,
        total_earned=balance.total_earned,
        total_redeemed=balance.total_redeemed,
        token_value_usd=TOKEN_VALUE_USD
    )


@referral_router.get("/tokens/history", response_model=TokenHistoryResponse)
async def get_token_history(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get token transaction history.
    """
    service = ReferralService(db)
    transactions, total = service.get_token_history(
        user_id=current_user.id,
        limit=limit,
        offset=offset
    )

    return TokenHistoryResponse(
        transactions=[
            TokenTransactionResponse(
                id=t.id,
                transaction_type=t.transaction_type.value,
                amount=t.amount,
                balance_after=t.balance_after,
                description=t.description,
                created_at=t.created_at
            )
            for t in transactions
        ],
        total=total
    )


@referral_router.post("/tokens/estimate-discount", response_model=DiscountEstimateResponse)
async def estimate_discount(
    request: EstimateDiscountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Calculate potential discount for a payment.
    """
    service = ReferralService(db)
    balance = service.get_or_create_token_balance(current_user.id)

    tokens_to_use, discount_amount, final_amount = service.calculate_token_discount(
        user_id=current_user.id,
        payment_amount=request.payment_amount,
        tokens_to_use=request.tokens_to_use
    )

    return DiscountEstimateResponse(
        original_amount=request.payment_amount,
        tokens_available=balance.available_tokens,
        tokens_to_use=tokens_to_use,
        discount_amount=discount_amount,
        final_amount=final_amount,
        max_tokens_allowed=min(balance.available_tokens, MAX_TOKENS_PER_PAYMENT)
    )
