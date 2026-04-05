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


# ============ Admin Endpoints ============

from .models import Referral, UserReferralCode, UserTokenBalance, TokenTransaction
from sqlalchemy import func


@referral_router.get("/admin/all")
async def admin_list_referrals(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """List all referrals (admin)."""
    query = db.query(Referral)
    total = query.count()

    referrals = query.order_by(Referral.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for ref in referrals:
        # Get referrer through the referral code relationship
        referrer_code = db.query(UserReferralCode).filter(UserReferralCode.id == ref.referrer_code_id).first()
        referrer = db.query(User).filter(User.id == referrer_code.user_id).first() if referrer_code else None
        referred = db.query(User).filter(User.id == ref.referred_user_id).first() if ref.referred_user_id else None
        items.append({
            "id": str(ref.id),
            "referrer_id": str(referrer_code.user_id) if referrer_code else "Unknown",
            "referrer_email": referrer.email if referrer else "Unknown",
            "referred_user_id": str(ref.referred_user_id) if ref.referred_user_id else "Unknown",
            "referred_email": ref.referred_email or (referred.email if referred else "Unknown"),
            "referral_code": referrer_code.referral_code if referrer_code else "Unknown",
            "status": ref.status.value if hasattr(ref.status, 'value') else ref.status,
            "tokens_awarded": ref.tokens_awarded,
            "created_at": ref.created_at.isoformat() if ref.created_at else None,
            "completed_at": ref.rewarded_at.isoformat() if ref.rewarded_at else (ref.signed_up_at.isoformat() if ref.signed_up_at else None),
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@referral_router.get("/admin/stats")
async def admin_referral_stats(db: Session = Depends(get_db)):
    """Get referral system stats (admin)."""
    from .models import ReferralStatus as RS
    total = db.query(Referral).count()
    completed = db.query(Referral).filter(Referral.status == RS.REWARDED).count()
    pending = db.query(Referral).filter(Referral.status == RS.PENDING).count()
    total_tokens = db.query(func.coalesce(func.sum(Referral.tokens_awarded), 0)).scalar()

    from .constants import TOKENS_PER_REFERRAL, TOKEN_VALUE_USD, MAX_TOKENS_PER_PAYMENT

    return {
        "total_referrals": total,
        "completed_referrals": completed,
        "pending_referrals": pending,
        "total_tokens_awarded": int(total_tokens),
        "tokens_per_referral": TOKENS_PER_REFERRAL,
        "token_value_usd": TOKEN_VALUE_USD,
        "max_tokens_per_payment": MAX_TOKENS_PER_PAYMENT,
    }


@referral_router.post("/admin/manual-referral")
async def admin_manual_referral(
    request: dict,
    db: Session = Depends(get_db)
):
    """Manually process a referral (admin). Body: {referrer_email, referred_email}"""
    referrer_email = request.get("referrer_email")
    referred_email = request.get("referred_email")

    if not referrer_email or not referred_email:
        raise HTTPException(status_code=400, detail="referrer_email and referred_email are required")

    referrer = db.query(User).filter(User.email == referrer_email).first()
    referred = db.query(User).filter(User.email == referred_email).first()

    if not referrer:
        raise HTTPException(status_code=404, detail=f"Referrer {referrer_email} not found")
    if not referred:
        raise HTTPException(status_code=404, detail=f"Referred user {referred_email} not found")

    # Get or create referral code for referrer
    referrer_code = db.query(UserReferralCode).filter(UserReferralCode.user_id == referrer.id).first()
    if not referrer_code:
        from .constants import REFERRAL_CODE_LENGTH, REFERRAL_CODE_CHARS
        import random
        code = ''.join(random.choices(REFERRAL_CODE_CHARS, k=REFERRAL_CODE_LENGTH))
        referrer_code = UserReferralCode(user_id=referrer.id, referral_code=code)
        db.add(referrer_code)
        db.flush()

    # Check if referral already exists
    existing = db.query(Referral).filter(
        Referral.referrer_code_id == referrer_code.id,
        Referral.referred_user_id == referred.id
    ).first()
    if existing:
        return {"message": "Referral already exists", "status": existing.status.value, "tokens_awarded": existing.tokens_awarded}

    from .constants import TOKENS_PER_REFERRAL
    from .models import ReferralStatus, TokenTransactionType
    from datetime import datetime

    # Create referral
    referral = Referral(
        referrer_code_id=referrer_code.id,
        referred_user_id=referred.id,
        referred_email=referred.email,
        status=ReferralStatus.REWARDED,
        tokens_awarded=TOKENS_PER_REFERRAL,
        signed_up_at=referred.created_at or datetime.utcnow(),
        rewarded_at=datetime.utcnow(),
    )
    db.add(referral)

    # Update referrer code stats
    referrer_code.total_referrals += 1
    referrer_code.successful_referrals += 1
    referrer_code.total_tokens_earned += TOKENS_PER_REFERRAL

    # Award tokens
    balance = db.query(UserTokenBalance).filter(UserTokenBalance.user_id == referrer.id).first()
    if not balance:
        balance = UserTokenBalance(user_id=referrer.id)
        db.add(balance)
        db.flush()

    balance.available_tokens += TOKENS_PER_REFERRAL
    balance.total_earned += TOKENS_PER_REFERRAL

    # Log transaction
    tx = TokenTransaction(
        token_balance_id=balance.id,
        transaction_type=TokenTransactionType.EARNED,
        amount=TOKENS_PER_REFERRAL,
        balance_after=balance.available_tokens,
        reference_type="referral",
        reference_id=referral.id,
        description=f"Manual referral reward: {referred.email} signed up"
    )
    db.add(tx)
    db.commit()

    return {
        "message": f"Referral processed: {referrer_email} earned {TOKENS_PER_REFERRAL} tokens for referring {referred_email}",
        "tokens_awarded": TOKENS_PER_REFERRAL,
        "referral_id": str(referral.id),
    }


@referral_router.get("/admin/config")
async def get_referral_config(db: Session = Depends(get_db)):
    """Get referral reward configuration."""
    from .constants import TOKENS_PER_REFERRAL, TOKEN_VALUE_USD, MAX_TOKENS_PER_PAYMENT
    return {
        "tokens_per_referral": TOKENS_PER_REFERRAL,
        "token_value_usd": TOKEN_VALUE_USD,
        "max_tokens_per_payment": MAX_TOKENS_PER_PAYMENT,
    }


@referral_router.put("/admin/config")
async def update_referral_config(
    request: dict,
    db: Session = Depends(get_db)
):
    """Update referral reward configuration (writes to constants file)."""
    import os

    tokens_per_referral = request.get("tokens_per_referral")
    token_value_usd = request.get("token_value_usd")
    max_tokens_per_payment = request.get("max_tokens_per_payment")

    # Update the constants file
    constants_path = os.path.join(os.path.dirname(__file__), "constants.py")

    new_content = f'''# modules/referral/constants.py
"""
Referral system configuration constants.
"""

# Token rewards
TOKENS_PER_REFERRAL = {int(tokens_per_referral) if tokens_per_referral else 10}      # Tokens awarded when referred user signs up
TOKEN_VALUE_USD = {float(token_value_usd) if token_value_usd else 1.00}        # Each token = $X discount
MAX_TOKENS_PER_PAYMENT = {int(max_tokens_per_payment) if max_tokens_per_payment else 50}   # Max tokens discount per payment

# Referral code settings
REFERRAL_CODE_LENGTH = 8      # Length of generated referral codes
REFERRAL_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # Excluding similar chars (0/O, 1/I)

# Frontend URL for referral links
FRONTEND_BASE_URL = "https://shopivell.com"  # Update with actual domain
REFERRAL_SIGNUP_PATH = "/signup"
'''

    with open(constants_path, 'w') as f:
        f.write(new_content)

    # Reload the module to pick up changes
    import importlib
    from . import constants
    importlib.reload(constants)

    return {
        "message": "Referral configuration updated",
        "tokens_per_referral": int(tokens_per_referral) if tokens_per_referral else 10,
        "token_value_usd": float(token_value_usd) if token_value_usd else 1.00,
        "max_tokens_per_payment": int(max_tokens_per_payment) if max_tokens_per_payment else 50,
    }
