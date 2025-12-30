# modules/referral/__init__.py
"""
Referral System Module

Handles user referrals, token rewards, and subscription discounts.
"""

from .router import referral_router
from .service import ReferralService
from .models import (
    UserReferralCode,
    Referral,
    UserTokenBalance,
    TokenTransaction,
    ReferralStatus,
    ReferralSource,
    TokenTransactionType
)

__all__ = [
    "referral_router",
    "ReferralService",
    "UserReferralCode",
    "Referral",
    "UserTokenBalance",
    "TokenTransaction",
    "ReferralStatus",
    "ReferralSource",
    "TokenTransactionType"
]
