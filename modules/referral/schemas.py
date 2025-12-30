# modules/referral/schemas.py
"""
Pydantic schemas for referral API requests and responses.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from enum import Enum


class ReferralSourceEnum(str, Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    FACEBOOK = "facebook"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    COPY = "copy"
    OTHER = "other"


class ReferralStatusEnum(str, Enum):
    PENDING = "pending"
    SIGNED_UP = "signed_up"
    REWARDED = "rewarded"
    EXPIRED = "expired"


# ============ Request Schemas ============

class TrackShareRequest(BaseModel):
    """Track when user shares referral link."""
    source: ReferralSourceEnum


class EstimateDiscountRequest(BaseModel):
    """Calculate discount for a payment amount."""
    payment_amount: float = Field(..., gt=0, description="Payment amount in USD")
    tokens_to_use: Optional[int] = Field(None, ge=0, description="Number of tokens to redeem")


class RedeemTokensRequest(BaseModel):
    """Redeem tokens for payment discount."""
    payment_id: UUID
    tokens_to_redeem: int = Field(..., gt=0, le=50, description="Tokens to redeem (max 50)")


# ============ Response Schemas ============

class ReferralCodeResponse(BaseModel):
    """User's referral code and link."""
    referral_code: str
    referral_link: str
    total_referrals: int
    successful_referrals: int
    total_tokens_earned: int
    is_active: bool

    class Config:
        from_attributes = True


class ReferralStatsResponse(BaseModel):
    """Detailed referral statistics."""
    total_referrals: int
    successful_referrals: int
    pending_referrals: int
    total_tokens_earned: int
    available_tokens: int
    tokens_redeemed: int
    potential_savings: float  # available_tokens * $1


class ReferralItemResponse(BaseModel):
    """Single referral item in list."""
    id: UUID
    status: ReferralStatusEnum
    source: ReferralSourceEnum
    tokens_awarded: int
    referred_email: Optional[str]
    created_at: datetime
    signed_up_at: Optional[datetime]
    rewarded_at: Optional[datetime]

    class Config:
        from_attributes = True


class ReferralListResponse(BaseModel):
    """List of user's referrals."""
    referrals: List[ReferralItemResponse]
    total: int


class ValidateCodeResponse(BaseModel):
    """Response when validating a referral code."""
    is_valid: bool
    referrer_name: Optional[str] = None
    message: str


class TokenBalanceResponse(BaseModel):
    """User's token balance."""
    available_tokens: int
    total_earned: int
    total_redeemed: int
    token_value_usd: float = 1.0

    class Config:
        from_attributes = True


class TokenTransactionResponse(BaseModel):
    """Single token transaction."""
    id: UUID
    transaction_type: str
    amount: int
    balance_after: int
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class TokenHistoryResponse(BaseModel):
    """Token transaction history."""
    transactions: List[TokenTransactionResponse]
    total: int


class DiscountEstimateResponse(BaseModel):
    """Estimated discount for payment."""
    original_amount: float
    tokens_available: int
    tokens_to_use: int
    discount_amount: float
    final_amount: float
    max_tokens_allowed: int


class ShareLinksResponse(BaseModel):
    """Pre-formatted share links for different platforms."""
    referral_link: str
    email_link: str
    whatsapp_link: str
    facebook_link: str
    twitter_link: str
