# modules/referral/models.py
"""
Database models for the referral system.
"""

from typing import Optional, List
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, Integer, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid
import enum

from database import Base


class ReferralStatus(str, enum.Enum):
    """Status of a referral."""
    PENDING = "pending"           # Link shared but not used yet
    SIGNED_UP = "signed_up"       # User signed up but not yet rewarded
    REWARDED = "rewarded"         # Tokens awarded to referrer
    EXPIRED = "expired"           # Referral link expired without signup


class ReferralSource(str, enum.Enum):
    """Source/channel of the referral share."""
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    FACEBOOK = "facebook"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    COPY = "copy"                 # User copied the link
    OTHER = "other"


class TokenTransactionType(str, enum.Enum):
    """Type of token transaction."""
    EARNED = "earned"             # Earned from referral
    REDEEMED = "redeemed"         # Used for payment discount
    EXPIRED = "expired"           # Tokens expired
    BONUS = "bonus"               # Promotional bonus
    ADJUSTMENT = "adjustment"     # Manual adjustment


class UserReferralCode(Base):
    """
    Unique referral code for each user.
    Each user gets one referral code they can share.
    """
    __tablename__ = "user_referral_codes"

    id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    user_id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        unique=True,
        index=True
    )
    referral_code: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        index=True
    )

    # Statistics
    total_referrals: Mapped[int] = mapped_column(Integer, default=0)
    successful_referrals: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens_earned: Mapped[int] = mapped_column(Integer, default=0)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships
    user = relationship("User", back_populates="referral_code")
    referrals = relationship("Referral", back_populates="referrer_code")


class Referral(Base):
    """
    Tracks each referral relationship.
    Created when a referral link is used at signup.
    """
    __tablename__ = "referrals"

    id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    referrer_code_id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user_referral_codes.id"),
        nullable=False,
        index=True
    )
    referred_user_id: Mapped[Optional[PG_UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,  # Nullable until user actually signs up
        index=True
    )

    # Referral details
    status: Mapped[ReferralStatus] = mapped_column(
        SQLEnum(ReferralStatus),
        default=ReferralStatus.PENDING
    )
    source: Mapped[ReferralSource] = mapped_column(
        SQLEnum(ReferralSource),
        default=ReferralSource.OTHER
    )
    tokens_awarded: Mapped[int] = mapped_column(Integer, default=0)

    # Tracking
    referred_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    signed_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rewarded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    referrer_code = relationship("UserReferralCode", back_populates="referrals")
    referred_user = relationship("User", foreign_keys=[referred_user_id])


class UserTokenBalance(Base):
    """
    Token balance for each user.
    Tracks available tokens that can be redeemed for discounts.
    """
    __tablename__ = "user_token_balances"

    id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    user_id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        unique=True,
        index=True
    )

    # Balance
    available_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_earned: Mapped[int] = mapped_column(Integer, default=0)
    total_redeemed: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships
    user = relationship("User", back_populates="token_balance")
    transactions = relationship("TokenTransaction", back_populates="token_balance")


class TokenTransaction(Base):
    """
    Ledger of all token changes.
    Provides audit trail for token earnings and redemptions.
    """
    __tablename__ = "token_transactions"

    id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    token_balance_id: Mapped[PG_UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user_token_balances.id"),
        nullable=False,
        index=True
    )

    # Transaction details
    transaction_type: Mapped[TokenTransactionType] = mapped_column(
        SQLEnum(TokenTransactionType),
        nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # Positive for earn, negative for redeem
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)

    # Reference to source (e.g., referral_id, payment_id)
    reference_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[Optional[PG_UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # Description
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    token_balance = relationship("UserTokenBalance", back_populates="transactions")
