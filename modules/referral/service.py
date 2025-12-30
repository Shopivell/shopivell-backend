# modules/referral/service.py
"""
Service layer for referral system business logic.
"""

import logging
import secrets
from typing import Optional, Tuple, List
from datetime import datetime
from uuid import UUID
from urllib.parse import quote

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from .models import (
    UserReferralCode,
    Referral,
    UserTokenBalance,
    TokenTransaction,
    ReferralStatus,
    ReferralSource,
    TokenTransactionType
)
from .constants import (
    TOKENS_PER_REFERRAL,
    TOKEN_VALUE_USD,
    MAX_TOKENS_PER_PAYMENT,
    REFERRAL_CODE_LENGTH,
    REFERRAL_CODE_CHARS,
    FRONTEND_BASE_URL,
    REFERRAL_SIGNUP_PATH
)

logger = logging.getLogger(__name__)


class ReferralService:
    """Service for managing referrals and tokens."""

    def __init__(self, db: Session):
        self.db = db

    # ============ Referral Code Methods ============

    def _generate_referral_code(self) -> str:
        """Generate a unique referral code."""
        return ''.join(secrets.choice(REFERRAL_CODE_CHARS) for _ in range(REFERRAL_CODE_LENGTH))

    def _generate_referral_link(self, code: str) -> str:
        """Generate full referral URL."""
        return f"{FRONTEND_BASE_URL}{REFERRAL_SIGNUP_PATH}?ref={code}"

    def get_or_create_referral_code(self, user_id: UUID) -> UserReferralCode:
        """
        Get user's referral code or create one if doesn't exist.

        Args:
            user_id: The user's ID

        Returns:
            UserReferralCode object
        """
        # Try to get existing code
        referral_code = self.db.query(UserReferralCode).filter(
            UserReferralCode.user_id == user_id
        ).first()

        if referral_code:
            return referral_code

        # Generate new unique code
        for _ in range(10):  # Try up to 10 times to avoid collisions
            code = self._generate_referral_code()
            # Check if code already exists
            existing = self.db.query(UserReferralCode).filter(
                UserReferralCode.referral_code == code
            ).first()
            if not existing:
                break
        else:
            # Fallback: use UUID prefix
            code = str(user_id)[:8].upper()

        # Create new referral code
        referral_code = UserReferralCode(
            user_id=user_id,
            referral_code=code,
            total_referrals=0,
            successful_referrals=0,
            total_tokens_earned=0,
            is_active=True
        )
        self.db.add(referral_code)
        self.db.commit()
        self.db.refresh(referral_code)

        logger.info(f"Created referral code {code} for user {user_id}")
        return referral_code

    def validate_referral_code(self, code: str) -> Tuple[bool, Optional[str], str]:
        """
        Validate a referral code.

        Args:
            code: The referral code to validate

        Returns:
            Tuple of (is_valid, referrer_name, message)
        """
        referral_code = self.db.query(UserReferralCode).options(
            joinedload(UserReferralCode.user)
        ).filter(
            UserReferralCode.referral_code == code.upper()
        ).first()

        if not referral_code:
            return False, None, "Invalid referral code"

        if not referral_code.is_active:
            return False, None, "This referral code is no longer active"

        # Get referrer's name
        referrer_name = None
        if referral_code.user:
            referrer_name = referral_code.user.full_name or referral_code.user.email.split('@')[0]

        return True, referrer_name, "Valid referral code"

    # ============ Referral Processing Methods ============

    def process_referral_signup(
        self,
        referred_user_id: UUID,
        referral_code: str,
        referred_email: Optional[str] = None,
        source: ReferralSource = ReferralSource.OTHER
    ) -> Optional[Referral]:
        """
        Process a new signup that used a referral code.
        Awards tokens to the referrer.

        Args:
            referred_user_id: The new user's ID
            referral_code: The referral code used
            referred_email: Email of referred user
            source: How the referral was shared

        Returns:
            Referral object if successful, None if invalid code
        """
        # Validate code
        referrer_code = self.db.query(UserReferralCode).filter(
            UserReferralCode.referral_code == referral_code.upper()
        ).first()

        if not referrer_code or not referrer_code.is_active:
            logger.warning(f"Invalid referral code used: {referral_code}")
            return None

        # Prevent self-referral
        if referrer_code.user_id == referred_user_id:
            logger.warning(f"Self-referral attempt by user {referred_user_id}")
            return None

        # Check if this user was already referred
        existing = self.db.query(Referral).filter(
            Referral.referred_user_id == referred_user_id
        ).first()
        if existing:
            logger.warning(f"User {referred_user_id} already has a referral record")
            return None

        # Create referral record
        referral = Referral(
            referrer_code_id=referrer_code.id,
            referred_user_id=referred_user_id,
            status=ReferralStatus.SIGNED_UP,
            source=source,
            referred_email=referred_email,
            signed_up_at=datetime.utcnow()
        )
        self.db.add(referral)

        # Update referrer's stats
        referrer_code.total_referrals += 1

        self.db.commit()
        self.db.refresh(referral)

        # Award tokens to referrer
        self._award_referral_tokens(referral)

        logger.info(f"Processed referral signup: {referred_user_id} via code {referral_code}")
        return referral

    def _award_referral_tokens(self, referral: Referral) -> None:
        """
        Award tokens to referrer for successful signup.

        Args:
            referral: The referral record
        """
        # Get referrer's code to find user_id
        referrer_code = self.db.query(UserReferralCode).filter(
            UserReferralCode.id == referral.referrer_code_id
        ).first()

        if not referrer_code:
            return

        # Award tokens
        self.award_tokens(
            user_id=referrer_code.user_id,
            amount=TOKENS_PER_REFERRAL,
            transaction_type=TokenTransactionType.EARNED,
            reference_type="referral",
            reference_id=referral.id,
            description=f"Earned for referring a new user"
        )

        # Update referral record
        referral.status = ReferralStatus.REWARDED
        referral.tokens_awarded = TOKENS_PER_REFERRAL
        referral.rewarded_at = datetime.utcnow()

        # Update referrer code stats
        referrer_code.successful_referrals += 1
        referrer_code.total_tokens_earned += TOKENS_PER_REFERRAL

        self.db.commit()

    def track_share(
        self,
        user_id: UUID,
        source: ReferralSource
    ) -> None:
        """
        Track when a user shares their referral link.
        Used for analytics.

        Args:
            user_id: The user sharing
            source: Share platform/method
        """
        # For now, just log it. Could store in analytics table later.
        logger.info(f"User {user_id} shared referral via {source.value}")

    # ============ Token Methods ============

    def get_or_create_token_balance(self, user_id: UUID) -> UserTokenBalance:
        """
        Get user's token balance or create if doesn't exist.

        Args:
            user_id: The user's ID

        Returns:
            UserTokenBalance object
        """
        balance = self.db.query(UserTokenBalance).filter(
            UserTokenBalance.user_id == user_id
        ).first()

        if balance:
            return balance

        # Create new balance record
        balance = UserTokenBalance(
            user_id=user_id,
            available_tokens=0,
            total_earned=0,
            total_redeemed=0
        )
        self.db.add(balance)
        self.db.commit()
        self.db.refresh(balance)

        return balance

    def award_tokens(
        self,
        user_id: UUID,
        amount: int,
        transaction_type: TokenTransactionType,
        reference_type: Optional[str] = None,
        reference_id: Optional[UUID] = None,
        description: Optional[str] = None
    ) -> TokenTransaction:
        """
        Award tokens to a user.

        Args:
            user_id: User to award tokens to
            amount: Number of tokens to award
            transaction_type: Type of transaction
            reference_type: Type of reference (e.g., "referral")
            reference_id: ID of reference object
            description: Human-readable description

        Returns:
            TokenTransaction record
        """
        balance = self.get_or_create_token_balance(user_id)

        # Update balance
        balance.available_tokens += amount
        balance.total_earned += amount
        new_balance = balance.available_tokens

        # Create transaction record
        transaction = TokenTransaction(
            token_balance_id=balance.id,
            transaction_type=transaction_type,
            amount=amount,
            balance_after=new_balance,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description
        )
        self.db.add(transaction)

        self.db.commit()
        self.db.refresh(transaction)

        logger.info(f"Awarded {amount} tokens to user {user_id}. New balance: {new_balance}")
        return transaction

    def calculate_token_discount(
        self,
        user_id: UUID,
        payment_amount: float,
        tokens_to_use: Optional[int] = None
    ) -> Tuple[int, float, float]:
        """
        Calculate discount for using tokens.

        Args:
            user_id: User's ID
            payment_amount: Original payment amount
            tokens_to_use: Specific number of tokens to use (None = max available)

        Returns:
            Tuple of (tokens_to_use, discount_amount, final_amount)
        """
        balance = self.get_or_create_token_balance(user_id)

        # Determine how many tokens to use
        max_tokens = min(
            balance.available_tokens,
            MAX_TOKENS_PER_PAYMENT,
            int(payment_amount / TOKEN_VALUE_USD)  # Can't discount more than payment
        )

        if tokens_to_use is None:
            tokens_to_use = max_tokens
        else:
            tokens_to_use = min(tokens_to_use, max_tokens)

        # Calculate discount
        discount_amount = tokens_to_use * TOKEN_VALUE_USD
        final_amount = max(0, payment_amount - discount_amount)

        return tokens_to_use, discount_amount, final_amount

    def redeem_tokens(
        self,
        user_id: UUID,
        amount: int,
        payment_id: UUID,
        description: Optional[str] = None
    ) -> Optional[TokenTransaction]:
        """
        Redeem tokens for payment discount.

        Args:
            user_id: User's ID
            amount: Number of tokens to redeem
            payment_id: Associated payment transaction ID
            description: Description of redemption

        Returns:
            TokenTransaction if successful, None if insufficient balance
        """
        balance = self.get_or_create_token_balance(user_id)

        if balance.available_tokens < amount:
            logger.warning(f"Insufficient tokens for user {user_id}: {balance.available_tokens} < {amount}")
            return None

        # Deduct tokens
        balance.available_tokens -= amount
        balance.total_redeemed += amount
        new_balance = balance.available_tokens

        # Create transaction record
        transaction = TokenTransaction(
            token_balance_id=balance.id,
            transaction_type=TokenTransactionType.REDEEMED,
            amount=-amount,  # Negative for redemption
            balance_after=new_balance,
            reference_type="payment",
            reference_id=payment_id,
            description=description or f"Redeemed for payment discount"
        )
        self.db.add(transaction)

        self.db.commit()
        self.db.refresh(transaction)

        logger.info(f"Redeemed {amount} tokens for user {user_id}. New balance: {new_balance}")
        return transaction

    def get_token_history(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[TokenTransaction], int]:
        """
        Get user's token transaction history.

        Args:
            user_id: User's ID
            limit: Max records to return
            offset: Records to skip

        Returns:
            Tuple of (transactions, total_count)
        """
        balance = self.get_or_create_token_balance(user_id)

        # Get transactions
        transactions = self.db.query(TokenTransaction).filter(
            TokenTransaction.token_balance_id == balance.id
        ).order_by(
            TokenTransaction.created_at.desc()
        ).offset(offset).limit(limit).all()

        # Get total count
        total = self.db.query(func.count(TokenTransaction.id)).filter(
            TokenTransaction.token_balance_id == balance.id
        ).scalar() or 0

        return list(transactions), total

    # ============ Statistics Methods ============

    def get_referral_stats(self, user_id: UUID) -> dict:
        """
        Get comprehensive referral statistics for a user.

        Args:
            user_id: User's ID

        Returns:
            Dict with statistics
        """
        referral_code = self.get_or_create_referral_code(user_id)
        token_balance = self.get_or_create_token_balance(user_id)

        # Count pending referrals
        pending_count = self.db.query(func.count(Referral.id)).filter(
            Referral.referrer_code_id == referral_code.id,
            Referral.status == ReferralStatus.PENDING
        ).scalar() or 0

        return {
            "total_referrals": referral_code.total_referrals,
            "successful_referrals": referral_code.successful_referrals,
            "pending_referrals": pending_count,
            "total_tokens_earned": referral_code.total_tokens_earned,
            "available_tokens": token_balance.available_tokens,
            "tokens_redeemed": token_balance.total_redeemed,
            "potential_savings": token_balance.available_tokens * TOKEN_VALUE_USD
        }

    def get_referral_list(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[Referral], int]:
        """
        Get list of user's referrals.

        Args:
            user_id: User's ID
            limit: Max records
            offset: Records to skip

        Returns:
            Tuple of (referrals, total_count)
        """
        referral_code = self.get_or_create_referral_code(user_id)

        # Get referrals
        referrals = self.db.query(Referral).filter(
            Referral.referrer_code_id == referral_code.id
        ).order_by(
            Referral.created_at.desc()
        ).offset(offset).limit(limit).all()

        # Get total count
        total = self.db.query(func.count(Referral.id)).filter(
            Referral.referrer_code_id == referral_code.id
        ).scalar() or 0

        return list(referrals), total

    # ============ Share Link Generation ============

    def generate_share_links(self, referral_code: str) -> dict:
        """
        Generate pre-formatted share links for different platforms.

        Args:
            referral_code: User's referral code

        Returns:
            Dict with share links for each platform
        """
        referral_link = self._generate_referral_link(referral_code)
        encoded_link = quote(referral_link, safe='')

        share_text = "Join me on Shopivell and get started with AI-powered ad generation!"
        encoded_text = quote(share_text, safe='')

        return {
            "referral_link": referral_link,
            "email_link": f"mailto:?subject={quote('Join Shopivell')}&body={encoded_text}%20{encoded_link}",
            "whatsapp_link": f"https://wa.me/?text={encoded_text}%20{encoded_link}",
            "facebook_link": f"https://www.facebook.com/sharer/sharer.php?u={encoded_link}",
            "twitter_link": f"https://twitter.com/intent/tweet?url={encoded_link}&text={encoded_text}"
        }
