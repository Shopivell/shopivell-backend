# modules/payments/service.py - FIXED VERSION
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
import uuid
from sqlalchemy.orm import Session
import logging

from modules.payment.models import (
    PaymentTransaction, PaymentStatus, PaymentMethod,
    SubscriptionPlan, StoreSubscription, PackagePricing
)
from modules.referral.models import UserTokenBalance, TokenTransaction, TokenTransactionType
from modules.referral.constants import TOKEN_VALUE_USD, MAX_TOKENS_PER_PAYMENT
import os

logger = logging.getLogger(__name__)

# Stripe and PayPal configuration
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")
PAYPAL_MODE = os.getenv("PAYPAL_MODE", "sandbox")  # sandbox or live

class PaymentService:
    def __init__(self, db: Session):
        self.db = db
        self.paynow = None
        self._init_paynow()
    
    def _init_paynow(self):
        """Initialize PayNow integration"""
        try:
            from paynow import Paynow

            integration_id = os.getenv("PAYNOW_INTEGRATION_ID", "")
            integration_key = os.getenv("PAYNOW_INTEGRATION_KEY", "")
            return_url = os.getenv("PAYNOW_RETURN_URL", "")
            result_url = os.getenv("PAYNOW_RESULT_URL", "")

            # Don't initialize with placeholder/empty credentials
            if not integration_id or not integration_key or integration_id == "INTEGRATION_ID" or integration_key == "INTEGRATION_KEY":
                logger.warning("PayNow credentials not configured. Running in simulation mode.")
                self.paynow = None
                return

            self.paynow = Paynow(
                integration_id,
                integration_key,
                return_url,
                result_url
            )
            logger.info("PayNow initialized successfully")
        except ImportError:
            logger.warning("PayNow library not installed. Running in simulation mode.")
            self.paynow = None
        except Exception as e:
            logger.error(f"Failed to initialize PayNow: {str(e)}")
            self.paynow = None
    
    def create_payment_transaction(
        self,
        store_id: uuid.UUID,
        user_id: uuid.UUID,
        amount: float,
        payment_method: PaymentMethod,
        package_name: SubscriptionPlan,
        billing_period: str = "monthly",
        mobile_number: Optional[str] = None,
        tokens_to_redeem: int = 0
    ) -> Tuple[Optional[PaymentTransaction], Optional[str]]:
        """Create a new payment transaction"""
        try:
            # Generate unique reference
            reference = f"PAY-{uuid.uuid4().hex[:8].upper()}-{int(datetime.now().timestamp())}"
            
            # Get package pricing
            package = self.db.query(PackagePricing).filter(
                PackagePricing.package_name == package_name,
                PackagePricing.is_active == True
            ).first()
            
            if not package:
                return None, "Package not found or inactive"
            
            # Validate amount matches package price
            if billing_period == "annual" and package.annual_price:
                expected_amount = package.annual_price
            else:
                expected_amount = package.monthly_price
            
            if abs(amount - expected_amount) > 0.01:
                return None, f"Amount does not match package price. Expected: ${expected_amount:.2f}"
            
            # Apply token discount if tokens provided
            token_discount = 0.0
            actual_amount = float(amount)
            if tokens_to_redeem > 0:
                # Validate token balance
                token_balance = self.db.query(UserTokenBalance).filter(
                    UserTokenBalance.user_id == user_id
                ).first()
                
                if token_balance and token_balance.available_tokens >= tokens_to_redeem:
                    # Calculate discount (capped at MAX_TOKENS_PER_PAYMENT and payment amount)
                    max_tokens = min(
                        tokens_to_redeem,
                        MAX_TOKENS_PER_PAYMENT,
                        int(amount / TOKEN_VALUE_USD)
                    )
                    token_discount = max_tokens * TOKEN_VALUE_USD
                    actual_amount = max(0, amount - token_discount)
                    
                    # Deduct tokens
                    token_balance.available_tokens -= max_tokens
                    token_balance.total_redeemed += max_tokens
                    
                    # Create token transaction record
                    token_tx = TokenTransaction(
                        token_balance_id=token_balance.id,
                        transaction_type=TokenTransactionType.REDEEMED,
                        amount=-max_tokens,
                        balance_after=token_balance.available_tokens,
                        reference_type="payment",
                        description=f"Redeemed for {package_name.value} subscription"
                    )
                    self.db.add(token_tx)
                    logger.info(f"Applied {max_tokens} token discount (${token_discount:.2f}) for user {user_id}")
                else:
                    logger.warning(f"Insufficient tokens for user {user_id}: requested {tokens_to_redeem}, available {token_balance.available_tokens if token_balance else 0}")
            
            # Create transaction
            transaction = PaymentTransaction(
                store_id=store_id,
                user_id=user_id,
                reference=reference,
                amount=actual_amount,  # Amount after token discount
                currency="USD",
                payment_method=payment_method,
                package_name=package_name,
                billing_period=billing_period,
                mobile_number=mobile_number,
                status=PaymentStatus.PENDING,
                payment_metadata={"token_discount": float(token_discount), "original_amount": float(amount)},
                initiated_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=24)
            )
            
            self.db.add(transaction)
            self.db.commit()
            self.db.refresh(transaction)
            
            logger.info(f"Created payment transaction {reference} for store {store_id}")
            return transaction, None
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating payment transaction: {str(e)}")
            return None, str(e)
    
    def initiate_ecocash_payment(
        self,
        transaction: PaymentTransaction,
        mobile_number: str,
        email: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Initiate EcoCash payment via PayNow

        PayNow API Reference:
        - Create payment: paynow.create_payment(reference, email)
        - Add items: payment.add(name, amount)
        - Send to mobile: paynow.send_mobile(payment, phone, 'ecocash')
        - Response: response.success, response.poll_url, response.instructions
        """
        try:
            if not self.paynow:
                # Simulate PayNow response for testing
                logger.info("PayNow not configured, simulating payment")
                return self._simulate_paynow_payment(transaction, mobile_number)

            # Real PayNow integration
            # Reference format: Order reference that will appear in PayNow
            description = f"Shopivell {transaction.package_name.value.capitalize()} - {transaction.reference}"
            payment = self.paynow.create_payment(description, email)

            # Add the subscription as a line item
            payment.add(
                f"{transaction.package_name.value.capitalize()} Subscription ({transaction.billing_period})",
                float(transaction.amount)
            )

            # Send mobile payment request to EcoCash
            # The phone number should be in format: 0771234567 or 0781234567
            response = self.paynow.send_mobile(payment, mobile_number, 'ecocash')

            # Log response for debugging
            logger.info(f"PayNow EcoCash response - success: {response.success}")
            if hasattr(response, 'poll_url'):
                logger.info(f"PayNow poll_url: {response.poll_url}")

            if response.success:
                # Extract poll_url (required for status checking)
                raw_poll_url = getattr(response, 'poll_url', None)
                poll_url = str(raw_poll_url) if raw_poll_url else None

                # Extract instructions for the user
                default_instruction = 'Check your EcoCash phone for a payment prompt. Dial *151*2# to approve.'
                raw_instructions = getattr(response, 'instructions', None) or getattr(response, 'instruction', None)

                # Ensure instructions is a proper string (not a class type)
                if raw_instructions is None or raw_instructions is str or isinstance(raw_instructions, type):
                    instructions = default_instruction
                elif callable(raw_instructions):
                    try:
                        instructions = str(raw_instructions())
                    except:
                        instructions = default_instruction
                else:
                    instructions = str(raw_instructions) if raw_instructions else default_instruction

                # Generate or extract PayNow reference
                paynow_ref = self._extract_paynow_reference(response)

                # Update transaction with PayNow details
                transaction.poll_url = poll_url
                transaction.paynow_reference = paynow_ref
                transaction.mobile_number = mobile_number
                transaction.status = PaymentStatus.PROCESSING

                self.db.commit()

                return {
                    "poll_url": poll_url,
                    "paynow_reference": paynow_ref,
                    "instruction": instructions,
                    "reference": transaction.reference
                }, None
            else:
                # Extract error message from response
                error_msg = self._extract_error_message(response)

                transaction.status = PaymentStatus.FAILED
                transaction.error_message = error_msg
                self.db.commit()
                return None, error_msg

        except Exception as e:
            logger.error(f"Error initiating EcoCash payment: {str(e)}", exc_info=True)

            # Update transaction with error
            try:
                transaction.status = PaymentStatus.FAILED
                transaction.error_message = str(e)
                self.db.commit()
            except Exception as db_error:
                logger.error(f"Error updating transaction: {db_error}")
                self.db.rollback()

            return None, str(e)
    
    def _extract_paynow_reference(self, response) -> str:
        """Extract PayNow reference from response"""
        # Try different possible attribute names
        ref_attrs = ['paynow_reference', 'reference', 'paynowreference', 'ref']
        
        for attr in ref_attrs:
            if hasattr(response, attr):
                ref = getattr(response, attr)
                if ref and str(ref).strip():
                    return str(ref).strip()
        
        # If no reference found, generate one
        return f"PNW-{uuid.uuid4().hex[:8].upper()}"
    
    def _extract_error_message(self, response) -> str:
        """Extract error message from response"""
        # Try different possible attribute names
        error_attrs = ['error', 'message', 'error_message', 'errorMessage']
        
        for attr in error_attrs:
            if hasattr(response, attr):
                error_val = getattr(response, attr)
                if error_val:
                    # Handle case where error is a type object
                    if isinstance(error_val, type):
                        return f"Payment error: {error_val.__name__}"
                    else:
                        return str(error_val)
        
        # If no error message found, return generic
        return "Payment initiation failed"
    
    def _simulate_paynow_payment(
        self,
        transaction: PaymentTransaction,
        mobile_number: str
    ) -> Tuple[Dict[str, Any], None]:
        """Simulate PayNow payment for testing"""
        paynow_ref = f"PNW-SIM-{uuid.uuid4().hex[:8].upper()}"
        poll_url = f"https://demo.paynow.co.zw/poll/{paynow_ref}"
        
        # Update transaction
        transaction.poll_url = poll_url
        transaction.paynow_reference = paynow_ref
        transaction.mobile_number = mobile_number
        
        self.db.commit()
        
        return {
            "poll_url": poll_url,
            "paynow_reference": paynow_ref,
            "instruction": "Dial *151*2# to complete payment (SIMULATED)",
            "reference": transaction.reference,
            "simulated": True
        }, None
    
    def check_payment_status(self, poll_url: str) -> Optional[Dict[str, Any]]:
        """
        Check payment status from PayNow

        PayNow API Reference:
        - Check status: paynow.check_transaction_status(poll_url)
        - Response: status.paid (boolean), status.status (string)
        """
        try:
            if not self.paynow:
                return {"status": "pending", "paid": False, "message": "PayNow not configured - simulation mode"}

            # Call PayNow to check transaction status
            status = self.paynow.check_transaction_status(poll_url)

            # Log response for debugging
            logger.info(f"PayNow status check - paid: {getattr(status, 'paid', None)}, status: {getattr(status, 'status', None)}")

            result = {
                "status": "unknown",
                "paid": False,
                "amount": None,
                "reference": None,
                "paynow_reference": None
            }

            # Check if payment is complete using status.paid (boolean)
            if hasattr(status, 'paid'):
                result["paid"] = bool(status.paid)
                if status.paid:
                    result["status"] = "paid"

            # Get status string if available
            if hasattr(status, 'status'):
                status_str = str(status.status).lower()
                result["status"] = status_str

                # Map PayNow status to our status
                # PayNow statuses: created, sent, cancelled, disputed, paid, awaiting delivery, delivered, refunded
                if status_str in ['paid', 'delivered', 'awaiting delivery']:
                    result["paid"] = True
                elif status_str in ['cancelled', 'refunded', 'disputed']:
                    result["paid"] = False
                    result["failed"] = True

            # Extract amount if available
            if hasattr(status, 'amount'):
                result["amount"] = float(status.amount) if status.amount else None

            # Extract reference
            if hasattr(status, 'reference'):
                result["reference"] = str(status.reference)

            # Extract PayNow reference
            result["paynow_reference"] = self._extract_paynow_reference(status)

            return result

        except Exception as e:
            logger.error(f"Error checking payment status: {str(e)}", exc_info=True)
            return {"status": "error", "paid": False, "message": str(e)}

    def poll_and_update_transaction(self, reference: str) -> Tuple[Optional[PaymentTransaction], Optional[str]]:
        """
        Poll PayNow for transaction status and update our database accordingly.
        This is the main method to check if a mobile payment has been completed.
        """
        try:
            # Get transaction by reference
            transaction = self.db.query(PaymentTransaction).filter(
                PaymentTransaction.reference == reference
            ).first()

            if not transaction:
                return None, "Transaction not found"

            # Skip if already completed or failed
            if transaction.status in [PaymentStatus.COMPLETED, PaymentStatus.FAILED, PaymentStatus.CANCELLED]:
                return transaction, None

            # Need poll_url to check status
            if not transaction.poll_url:
                return transaction, "No poll URL available for this transaction"

            # Auto-complete simulated payments after ~10 seconds
            is_simulated = transaction.paynow_reference and (
                transaction.paynow_reference.startswith("PNW-SIM-") or
                transaction.paynow_reference.startswith("INB-SIM-")
            )
            if is_simulated:
                elapsed = (datetime.utcnow() - transaction.initiated_at).total_seconds()
                if elapsed >= 10:
                    transaction.status = PaymentStatus.COMPLETED
                    transaction.completed_at = datetime.utcnow()
                    self._activate_subscription(transaction)
                    self.db.commit()
                    self.db.refresh(transaction)
                    print(f"[PAYMENT] Simulated payment {reference} auto-completed after {elapsed:.0f}s - SENDING EMAIL NOW")
                    logger.info(f"Simulated payment {reference} auto-completed after {elapsed:.0f}s")
                    self._send_receipt_email(transaction)
                    return transaction, None
                else:
                    logger.info(f"Simulated payment {reference} waiting ({elapsed:.0f}s / 10s)")
                    return transaction, None

            # Check status with PayNow
            status_result = self.check_payment_status(transaction.poll_url)

            if not status_result:
                return transaction, "Failed to check payment status"

            # Update based on PayNow response
            if status_result.get("paid"):
                # Payment completed successfully
                transaction.status = PaymentStatus.COMPLETED
                transaction.completed_at = datetime.utcnow()

                # Update PayNow reference if available
                if status_result.get("paynow_reference"):
                    transaction.paynow_reference = status_result["paynow_reference"]

                # Activate subscription
                self._activate_subscription(transaction)

                self.db.commit()
                self.db.refresh(transaction)
                logger.info(f"Payment {reference} marked as COMPLETED after polling")
                self._send_receipt_email(transaction)
                return transaction, None

            elif status_result.get("failed"):
                # Payment failed
                transaction.status = PaymentStatus.FAILED
                transaction.completed_at = datetime.utcnow()
                transaction.error_message = f"Payment {status_result.get('status', 'failed')}"

                self.db.commit()
                self.db.refresh(transaction)
                logger.info(f"Payment {reference} marked as FAILED after polling")
                return transaction, None

            else:
                # Still pending/processing
                paynow_status = status_result.get("status", "unknown")
                logger.info(f"Payment {reference} still pending. PayNow status: {paynow_status}")
                return transaction, None

        except Exception as e:
            logger.error(f"Error polling transaction status: {str(e)}", exc_info=True)
            return None, str(e)

    def update_payment_status(
        self,
        reference: str,
        status: PaymentStatus,
        paynow_reference: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> Tuple[Optional[PaymentTransaction], Optional[str]]:
        """Update payment transaction status"""
        try:
            transaction = self.db.query(PaymentTransaction).filter(
                PaymentTransaction.reference == reference
            ).first()
            
            if not transaction:
                return None, "Transaction not found"
            
            # Update transaction
            transaction.status = status
            
            if paynow_reference:
                transaction.paynow_reference = str(paynow_reference)
            
            if error_message:
                transaction.error_message = str(error_message)
            
            if status == PaymentStatus.COMPLETED:
                transaction.completed_at = datetime.utcnow()
                self._activate_subscription(transaction)
            elif status == PaymentStatus.FAILED:
                transaction.completed_at = datetime.utcnow()
            
            self.db.commit()
            self.db.refresh(transaction)
            
            logger.info(f"Updated payment {reference} to status: {status}")
            return transaction, None
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating payment status: {str(e)}")
            return None, str(e)
    
    def _activate_subscription(self, transaction: PaymentTransaction):
        """Activate or renew subscription after successful payment"""
        try:
            # Calculate period end date
            if transaction.billing_period == "annual":
                period_end = datetime.utcnow() + timedelta(days=365)
            else:
                period_end = datetime.utcnow() + timedelta(days=30)
            
            # Check for existing subscription
            subscription = self.db.query(StoreSubscription).filter(
                StoreSubscription.store_id == transaction.store_id
            ).first()
            
            if subscription:
                # Update existing subscription
                subscription.package_name = transaction.package_name
                subscription.billing_period = transaction.billing_period
                subscription.current_period_start = datetime.utcnow()
                subscription.current_period_end = period_end
                subscription.is_active = True
                subscription.cancelled_at = None
                subscription.trial_ends_at = None  # Clear trial on paid upgrade
                subscription.last_payment_id = subscription.current_payment_id
                subscription.current_payment_id = transaction.id

                # Update enabled features
                self._update_subscription_features(subscription)
            else:
                # Create new subscription
                subscription = StoreSubscription(
                    store_id=transaction.store_id,
                    package_name=transaction.package_name,
                    billing_period=transaction.billing_period,
                    current_payment_id=transaction.id,
                    current_period_start=datetime.utcnow(),
                    current_period_end=period_end,
                    enabled_features=self._get_package_features(transaction.package_name),
                    usage_limits=self._get_package_limits(transaction.package_name)
                )
                self.db.add(subscription)
            
            # Update store's enabled_features
            from modules.stores.models import Store
            store = self.db.query(Store).filter(Store.id == transaction.store_id).first()
            if store:
                store.enabled_features = subscription.enabled_features
            
            self.db.commit()
            logger.info(f"Activated subscription for store {transaction.store_id}")
            
        except Exception as e:
            logger.error(f"Error activating subscription: {str(e)}")
            raise
    
    def _get_package_features(self, package_name: SubscriptionPlan) -> Dict[str, Any]:
        """Get features for a specific package"""
        features_map = {
            SubscriptionPlan.FREE: {
                "max_products": 10,
                "max_orders": 50,
                "analytics": False,
                "custom_domain": False,
                "priority_support": False,
                "social_posting": True,
                "basic_store": True
            },
            SubscriptionPlan.PREMIUM: {
                "max_products": 100,
                "max_orders": 500,
                "analytics": True,
                "custom_domain": True,
                "priority_support": False,
                "social_posting": True,
                "advanced_store": True,
                "inventory_management": True
            },
            SubscriptionPlan.BUSINESS: {
                "max_products": 1000,
                "max_orders": 5000,
                "analytics": True,
                "custom_domain": True,
                "priority_support": True,
                "social_posting": True,
                "advanced_store": True,
                "inventory_management": True,
                "multi_user_access": True,
                "api_access": True,
                "custom_branding": True
            }
        }
        
        return features_map.get(package_name, features_map[SubscriptionPlan.FREE])
    
    def _get_package_limits(self, package_name: SubscriptionPlan) -> Dict[str, Any]:
        """Get usage limits for a specific package"""
        limits_map = {
            SubscriptionPlan.FREE: {
                "monthly_bandwidth": "1GB",
                "storage": "100MB",
                "api_calls": 1000,
                "ai_calls": 50,
                "ai_tokens": 100_000,
                "support_response_time": "48h"
            },
            SubscriptionPlan.PREMIUM: {
                "monthly_bandwidth": "10GB",
                "storage": "1GB",
                "api_calls": 10000,
                "ai_calls": 500,
                "ai_tokens": 1_000_000,
                "support_response_time": "24h"
            },
            SubscriptionPlan.BUSINESS: {
                "monthly_bandwidth": "100GB",
                "storage": "10GB",
                "api_calls": 100000,
                "ai_calls": 5000,
                "ai_tokens": 10_000_000,
                "support_response_time": "4h"
            }
        }
        
        return limits_map.get(package_name, limits_map[SubscriptionPlan.FREE])
    
    def _update_subscription_features(self, subscription: StoreSubscription):
        """Update subscription features based on package"""
        subscription.enabled_features = self._get_package_features(subscription.package_name)
        subscription.usage_limits = self._get_package_limits(subscription.package_name)

    def get_payment_summary(self, store_id: uuid.UUID) -> Dict[str, Any]:
        """Get payment summary for a store"""
        try:
            # Get subscription
            subscription = self.db.query(StoreSubscription).filter(
                StoreSubscription.store_id == store_id
            ).first()

            # Get transaction stats
            total_transactions = self.db.query(PaymentTransaction).filter(
                PaymentTransaction.store_id == store_id
            ).count()

            completed_payments = self.db.query(PaymentTransaction).filter(
                PaymentTransaction.store_id == store_id,
                PaymentTransaction.status == PaymentStatus.COMPLETED
            ).count()

            # Calculate total spent
            from sqlalchemy import func
            total_spent = self.db.query(func.sum(PaymentTransaction.amount)).filter(
                PaymentTransaction.store_id == store_id,
                PaymentTransaction.status == PaymentStatus.COMPLETED
            ).scalar() or 0.0

            # Get package info
            if subscription and subscription.is_active:
                package = self.db.query(PackagePricing).filter(
                    PackagePricing.package_name == subscription.package_name,
                    PackagePricing.is_active == True
                ).first()

                next_payment_date = subscription.current_period_end
                next_payment_amount = package.monthly_price if subscription.billing_period == "monthly" else package.annual_price if package else 0
            elif subscription:
                # Cancelled subscription — treat as free
                package = self.db.query(PackagePricing).filter(
                    PackagePricing.package_name == SubscriptionPlan.FREE,
                    PackagePricing.is_active == True
                ).first()
                next_payment_date = None
                next_payment_amount = 0
            else:
                package = self.db.query(PackagePricing).filter(
                    PackagePricing.package_name == SubscriptionPlan.FREE,
                    PackagePricing.is_active == True
                ).first()
                next_payment_date = None
                next_payment_amount = 0

            return {
                "store_id": str(store_id),
                "current_package": subscription.package_name.value if subscription and subscription.is_active else SubscriptionPlan.FREE.value,
                "billing_period": subscription.billing_period if subscription else "monthly",
                "is_active": subscription.is_active if subscription else True,
                "auto_renew": subscription.auto_renew if subscription else False,
                "current_period_start": subscription.current_period_start if subscription else None,
                "current_period_end": subscription.current_period_end if subscription else None,
                "next_payment_date": next_payment_date,
                "next_payment_amount": next_payment_amount,
                "total_transactions": total_transactions,
                "completed_payments": completed_payments,
                "total_spent": float(total_spent),
                "enabled_features": subscription.enabled_features if subscription else self._get_package_features(SubscriptionPlan.FREE),
                "usage_limits": subscription.usage_limits if subscription else self._get_package_limits(SubscriptionPlan.FREE),
                "package_features": package.features if package else []
            }

        except Exception as e:
            logger.error(f"Error getting payment summary: {str(e)}")
            return {
                "store_id": str(store_id),
                "current_package": SubscriptionPlan.FREE.value,
                "billing_period": "monthly",
                "is_active": True,
                "error": str(e)
            }

    def simulate_payment(self, reference: str) -> bool:
        """Simulate payment completion for testing"""
        try:
            transaction = self.db.query(PaymentTransaction).filter(
                PaymentTransaction.reference == reference
            ).first()

            if not transaction:
                return False

            # Update to completed
            transaction.status = PaymentStatus.COMPLETED
            transaction.completed_at = datetime.utcnow()

            # Activate subscription
            self._activate_subscription(transaction)

            self.db.commit()
            logger.info(f"Simulated payment completion for {reference}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error simulating payment: {str(e)}")
            return False

    def generate_receipt(self, reference: str) -> Optional[Dict[str, Any]]:
        """Generate receipt for a completed transaction"""
        try:
            transaction = self.db.query(PaymentTransaction).filter(
                PaymentTransaction.reference == reference
            ).first()

            if not transaction:
                return None

            # Get store info
            from modules.stores.models import Store
            store = self.db.query(Store).filter(Store.id == transaction.store_id).first()

            # Get package info
            package = self.db.query(PackagePricing).filter(
                PackagePricing.package_name == transaction.package_name
            ).first()

            return {
                "receipt_number": f"RCP-{transaction.reference}",
                "transaction_reference": transaction.reference,
                "paynow_reference": transaction.paynow_reference,
                "status": transaction.status.value,
                "amount": float(transaction.amount),
                "currency": transaction.currency,
                "payment_method": transaction.payment_method.value,
                "package_name": transaction.package_name.value,
                "package_description": package.description if package else None,
                "billing_period": transaction.billing_period,
                "store_name": store.store_name if store else None,
                "store_id": str(transaction.store_id),
                "initiated_at": transaction.initiated_at.isoformat() if transaction.initiated_at else None,
                "completed_at": transaction.completed_at.isoformat() if transaction.completed_at else None,
                "features": package.features if package else []
            }

        except Exception as e:
            logger.error(f"Error generating receipt: {str(e)}")
            return None

    def _send_receipt_email(self, transaction: PaymentTransaction):
        """Auto-send receipt email with PDF invoice attachment after payment completion"""
        print(f"[RECEIPT EMAIL] _send_receipt_email CALLED for {transaction.reference}")
        logger.info(f"[RECEIPT EMAIL] _send_receipt_email CALLED for {transaction.reference}")
        try:
            import smtplib
            import base64 as b64_mod
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.application import MIMEApplication
            from modules.stores.models import Store
            from modules.agency.models import Agency

            store = self.db.query(Store).filter(Store.id == transaction.store_id).first()
            if not store:
                logger.warning(f"No store found for receipt email: {transaction.store_id}")
                return

            # Get agency email first, fall back to store owner email, then store email
            recipient_email = None
            if store.agency_id:
                agency = self.db.query(Agency).filter(Agency.id == store.agency_id).first()
                if agency and agency.email:
                    recipient_email = agency.email

            if not recipient_email and store.store_email:
                recipient_email = store.store_email

            if not recipient_email and store.owner:
                recipient_email = store.owner.email

            if not recipient_email:
                recipient_email = "farairhato@gmail.com"

            receipt = self.generate_receipt(transaction.reference)
            if not receipt:
                return

            # Load logo as base64 for email embedding
            logo_b64 = ""
            try:
                logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "shopivell_logo.png")
                if os.path.exists(logo_path):
                    with open(logo_path, "rb") as f:
                        logo_b64 = b64_mod.b64encode(f.read()).decode()
            except Exception:
                pass

            logo_html = f'<img src="data:image/png;base64,{logo_b64}" alt="Shopivell" style="width: 80px; height: 80px; margin-bottom: 10px;" /><br />' if logo_b64 else ""

            body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="text-align: center; margin-bottom: 30px;">
                    {logo_html}
                    <h1 style="color: #111; margin-bottom: 5px;">Shopivell</h1>
                    <p style="color: #666;">Payment Receipt</p>
                </div>
                <div style="background: #f9f9f9; border-radius: 12px; padding: 24px; margin-bottom: 20px;">
                    <h2 style="color: #111; margin-top: 0;">Payment Successful</h2>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 8px 0; color: #666;">Receipt #</td><td style="padding: 8px 0; text-align: right; font-weight: 600;">{receipt['receipt_number']}</td></tr>
                        <tr><td style="padding: 8px 0; color: #666;">Store</td><td style="padding: 8px 0; text-align: right; font-weight: 600;">{receipt.get('store_name', '')}</td></tr>
                        <tr><td style="padding: 8px 0; color: #666;">Package</td><td style="padding: 8px 0; text-align: right; font-weight: 600;">{receipt['package_name'].capitalize()}</td></tr>
                        <tr><td style="padding: 8px 0; color: #666;">Billing</td><td style="padding: 8px 0; text-align: right;">{receipt.get('billing_period', 'monthly').capitalize()}</td></tr>
                        <tr><td style="padding: 8px 0; color: #666;">Method</td><td style="padding: 8px 0; text-align: right;">{receipt['payment_method'].upper()}</td></tr>
                        <tr><td style="padding: 8px 0; color: #666;">Date</td><td style="padding: 8px 0; text-align: right;">{receipt.get('completed_at', '')[:10] if receipt.get('completed_at') else ''}</td></tr>
                        <tr style="border-top: 2px solid #ddd;"><td style="padding: 12px 0; font-weight: 700; font-size: 18px;">Total</td><td style="padding: 12px 0; text-align: right; font-weight: 700; font-size: 18px;">${receipt['amount']:.2f} {receipt['currency']}</td></tr>
                    </table>
                </div>
                <p style="color: #666; font-size: 14px; text-align: center;">Thank you for your subscription! Your invoice is attached.</p>
            </body>
            </html>
            """

            # Generate PDF invoice
            pdf_bytes = None
            try:
                from utils.invoice_pdf import generate_invoice_pdf
                pdf_bytes = generate_invoice_pdf(receipt)
                logger.info(f"Generated PDF invoice for {receipt['receipt_number']} ({len(pdf_bytes)} bytes)")
            except Exception as e:
                logger.error(f"Failed to generate PDF invoice: {e}")

            # Send email with PDF attachment directly via SMTP
            from dotenv import load_dotenv
            load_dotenv()
            email_user = os.getenv("EMAIL_USERNAME")
            email_pass = os.getenv("EMAIL_PASSWORD")
            smtp_server = os.getenv("SMTP_SERVER", "mail.privateemail.com")
            smtp_port = int(os.getenv("SMTP_PORT", "465"))

            if not email_user or not email_pass:
                logger.warning("Email credentials not configured, simulating receipt email")
                logger.info(f"[SIMULATED] Receipt email to {recipient_email}")
                return

            subject = f"Shopivell Payment Receipt - {receipt['receipt_number']}"

            msg = MIMEMultipart()
            msg["From"] = email_user
            msg["To"] = recipient_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html", "utf-8"))

            # Attach PDF invoice
            if pdf_bytes:
                pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
                pdf_filename = f"Shopivell-Invoice-{receipt['receipt_number']}.pdf"
                pdf_attachment.add_header("Content-Disposition", "attachment", filename=pdf_filename)
                msg.attach(pdf_attachment)

            with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as s:
                s.login(email_user, email_pass)
                s.sendmail(email_user, recipient_email, msg.as_string())

            logger.info(f"Receipt email with invoice sent to {recipient_email} for {transaction.reference}")

        except Exception as e:
            print(f"[RECEIPT EMAIL] ERROR: {str(e)}")
            import traceback; traceback.print_exc()
            logger.error(f"Error sending receipt email: {str(e)}")

    def initiate_innbucks_payment(
        self,
        transaction: PaymentTransaction,
        mobile_number: str,
        email: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Initiate InnBucks payment via PayNow

        PayNow API Reference:
        - Create payment: paynow.create_payment(reference, email)
        - Add items: payment.add(name, amount)
        - Send to mobile: paynow.send_mobile(payment, phone, 'innbucks')
        - Response: response.success, response.poll_url, response.instructions
        """
        try:
            if not self.paynow:
                # Simulate PayNow response for testing
                logger.info("PayNow not configured, simulating InnBucks payment")
                return self._simulate_innbucks_payment(transaction, mobile_number)

            # Real PayNow integration for InnBucks
            description = f"Shopivell {transaction.package_name.value.capitalize()} - {transaction.reference}"
            payment = self.paynow.create_payment(description, email)

            # Add the subscription as a line item
            payment.add(
                f"{transaction.package_name.value.capitalize()} Subscription ({transaction.billing_period})",
                float(transaction.amount)
            )

            # Send mobile payment request to InnBucks
            response = self.paynow.send_mobile(payment, mobile_number, 'innbucks')

            # Log response for debugging
            logger.info(f"PayNow InnBucks response - success: {response.success}")
            if hasattr(response, 'poll_url'):
                logger.info(f"PayNow poll_url: {response.poll_url}")

            if response.success:
                # Extract poll_url (required for status checking)
                poll_url = getattr(response, 'poll_url', None)

                # Extract instructions for the user
                instructions = getattr(response, 'instructions', None) or \
                              getattr(response, 'instruction', None) or \
                              'Open your InnBucks app and approve the payment request.'

                # Generate or extract PayNow reference
                paynow_ref = self._extract_paynow_reference(response)

                # Update transaction with PayNow details
                transaction.poll_url = poll_url
                transaction.paynow_reference = paynow_ref
                transaction.mobile_number = mobile_number
                transaction.status = PaymentStatus.PROCESSING

                self.db.commit()

                return {
                    "poll_url": poll_url,
                    "paynow_reference": paynow_ref,
                    "instruction": instructions,
                    "reference": transaction.reference
                }, None
            else:
                # Extract error message from response
                error_msg = self._extract_error_message(response)
                transaction.status = PaymentStatus.FAILED
                transaction.error_message = error_msg
                self.db.commit()
                return None, error_msg

        except Exception as e:
            logger.error(f"Error initiating InnBucks payment: {str(e)}", exc_info=True)
            try:
                transaction.status = PaymentStatus.FAILED
                transaction.error_message = str(e)
                self.db.commit()
            except Exception:
                self.db.rollback()
            return None, str(e)

    def _simulate_innbucks_payment(
        self,
        transaction: PaymentTransaction,
        mobile_number: str
    ) -> Tuple[Dict[str, Any], None]:
        """Simulate InnBucks payment for testing"""
        paynow_ref = f"INB-SIM-{uuid.uuid4().hex[:8].upper()}"
        poll_url = f"https://demo.paynow.co.zw/poll/{paynow_ref}"

        transaction.poll_url = poll_url
        transaction.paynow_reference = paynow_ref
        transaction.mobile_number = mobile_number

        self.db.commit()

        return {
            "poll_url": poll_url,
            "paynow_reference": paynow_ref,
            "instruction": "Check your InnBucks app to complete payment (SIMULATED)",
            "reference": transaction.reference,
            "simulated": True
        }, None

    def cancel_subscription(self, store_id: uuid.UUID) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Cancel a store's subscription"""
        try:
            subscription = self.db.query(StoreSubscription).filter(
                StoreSubscription.store_id == store_id,
                StoreSubscription.is_active == True
            ).first()

            if not subscription:
                return None, "Active subscription not found"

            # Mark as cancelled
            subscription.is_active = False
            subscription.auto_renew = False
            subscription.cancelled_at = datetime.utcnow()

            # Downgrade to free
            subscription.enabled_features = self._get_package_features(SubscriptionPlan.FREE)
            subscription.usage_limits = self._get_package_limits(SubscriptionPlan.FREE)

            # Update store's enabled_features
            from modules.stores.models import Store
            store = self.db.query(Store).filter(Store.id == store_id).first()
            if store:
                store.enabled_features = subscription.enabled_features

            self.db.commit()

            return {
                "message": "Subscription cancelled successfully",
                "store_id": str(store_id),
                "cancelled_at": subscription.cancelled_at.isoformat(),
                "new_package": SubscriptionPlan.FREE.value
            }, None

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error cancelling subscription: {str(e)}")
            return None, str(e)

    # Stripe Payment Methods
    def create_stripe_payment_intent(
        self,
        transaction: PaymentTransaction
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Create a Stripe PaymentIntent for card payments"""
        try:
            if not STRIPE_SECRET_KEY:
                logger.warning("Stripe not configured, simulating payment intent")
                return self._simulate_stripe_payment(transaction)

            import stripe
            stripe.api_key = STRIPE_SECRET_KEY

            # Create PaymentIntent
            intent = stripe.PaymentIntent.create(
                amount=int(transaction.amount * 100),  # Stripe uses cents
                currency=transaction.currency.lower(),
                metadata={
                    "reference": transaction.reference,
                    "store_id": str(transaction.store_id),
                    "package_name": transaction.package_name.value,
                    "billing_period": transaction.billing_period
                },
                description=f"{transaction.package_name.value.capitalize()} Subscription - {transaction.billing_period}"
            )

            # Update transaction with Stripe reference
            transaction.paynow_reference = intent.id  # Store Stripe intent ID
            self.db.commit()

            return {
                "client_secret": intent.client_secret,
                "payment_intent_id": intent.id,
                "publishable_key": STRIPE_PUBLISHABLE_KEY,
                "reference": transaction.reference,
                "amount": transaction.amount,
                "currency": transaction.currency
            }, None

        except Exception as e:
            logger.error(f"Error creating Stripe PaymentIntent: {str(e)}")
            transaction.status = PaymentStatus.FAILED
            transaction.error_message = str(e)
            self.db.commit()
            return None, str(e)

    def _simulate_stripe_payment(
        self,
        transaction: PaymentTransaction
    ) -> Tuple[Dict[str, Any], None]:
        """Simulate Stripe payment for testing"""
        fake_intent_id = f"pi_sim_{uuid.uuid4().hex[:16]}"
        fake_client_secret = f"{fake_intent_id}_secret_{uuid.uuid4().hex[:16]}"

        transaction.paynow_reference = fake_intent_id
        self.db.commit()

        return {
            "client_secret": fake_client_secret,
            "payment_intent_id": fake_intent_id,
            "publishable_key": "pk_test_simulated",
            "reference": transaction.reference,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "simulated": True
        }, None

    def confirm_stripe_payment(
        self,
        payment_intent_id: str
    ) -> Tuple[Optional[PaymentTransaction], Optional[str]]:
        """Confirm Stripe payment and activate subscription"""
        try:
            # Find transaction by Stripe intent ID
            transaction = self.db.query(PaymentTransaction).filter(
                PaymentTransaction.paynow_reference == payment_intent_id
            ).first()

            if not transaction:
                return None, "Transaction not found"

            if not STRIPE_SECRET_KEY:
                # Simulate confirmation
                transaction.status = PaymentStatus.COMPLETED
                transaction.completed_at = datetime.utcnow()
                self._activate_subscription(transaction)
                self.db.commit()
                return transaction, None

            import stripe
            stripe.api_key = STRIPE_SECRET_KEY

            # Retrieve PaymentIntent
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)

            if intent.status == "succeeded":
                transaction.status = PaymentStatus.COMPLETED
                transaction.completed_at = datetime.utcnow()
                self._activate_subscription(transaction)
                self.db.commit()
                return transaction, None
            else:
                transaction.status = PaymentStatus.FAILED
                transaction.error_message = f"Payment not completed: {intent.status}"
                self.db.commit()
                return None, f"Payment status: {intent.status}"

        except Exception as e:
            logger.error(f"Error confirming Stripe payment: {str(e)}")
            return None, str(e)

    def handle_stripe_webhook(
        self,
        payload: bytes,
        sig_header: str,
        webhook_secret: str
    ) -> Tuple[Optional[PaymentTransaction], Optional[str]]:
        """Handle Stripe webhook events"""
        try:
            if not STRIPE_SECRET_KEY:
                logger.warning("Stripe not configured")
                return None, "Stripe not configured"

            import stripe
            stripe.api_key = STRIPE_SECRET_KEY

            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )

            # Handle payment_intent.succeeded
            if event.type == "payment_intent.succeeded":
                intent = event.data.object
                return self.confirm_stripe_payment(intent.id)

            # Handle payment_intent.payment_failed
            elif event.type == "payment_intent.payment_failed":
                intent = event.data.object
                transaction = self.db.query(PaymentTransaction).filter(
                    PaymentTransaction.paynow_reference == intent.id
                ).first()

                if transaction:
                    transaction.status = PaymentStatus.FAILED
                    transaction.error_message = intent.last_payment_error.message if intent.last_payment_error else "Payment failed"
                    self.db.commit()
                    return transaction, None

            return None, None

        except Exception as e:
            logger.error(f"Error handling Stripe webhook: {str(e)}")
            return None, str(e)

    # PayPal Payment Methods
    def create_paypal_order(
        self,
        transaction: PaymentTransaction
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Create a PayPal order"""
        try:
            if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
                logger.warning("PayPal not configured, simulating order")
                return self._simulate_paypal_order(transaction)

            import paypalrestsdk
            paypalrestsdk.configure({
                "mode": PAYPAL_MODE,
                "client_id": PAYPAL_CLIENT_ID,
                "client_secret": PAYPAL_CLIENT_SECRET
            })

            payment = paypalrestsdk.Payment({
                "intent": "sale",
                "payer": {
                    "payment_method": "paypal"
                },
                "transactions": [{
                    "amount": {
                        "total": str(transaction.amount),
                        "currency": transaction.currency
                    },
                    "description": f"{transaction.package_name.value.capitalize()} Subscription - {transaction.billing_period}",
                    "custom": transaction.reference
                }],
                "redirect_urls": {
                    "return_url": f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/payment/success?ref={transaction.reference}",
                    "cancel_url": f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/payment/cancel?ref={transaction.reference}"
                }
            })

            if payment.create():
                # Get approval URL
                approval_url = None
                for link in payment.links:
                    if link.rel == "approval_url":
                        approval_url = link.href
                        break

                # Update transaction with PayPal ID
                transaction.paynow_reference = payment.id
                self.db.commit()

                return {
                    "order_id": payment.id,
                    "approval_url": approval_url,
                    "reference": transaction.reference,
                    "amount": transaction.amount,
                    "currency": transaction.currency
                }, None
            else:
                error_msg = payment.error.get("message", "PayPal order creation failed")
                transaction.status = PaymentStatus.FAILED
                transaction.error_message = error_msg
                self.db.commit()
                return None, error_msg

        except Exception as e:
            logger.error(f"Error creating PayPal order: {str(e)}")
            transaction.status = PaymentStatus.FAILED
            transaction.error_message = str(e)
            self.db.commit()
            return None, str(e)

    def _simulate_paypal_order(
        self,
        transaction: PaymentTransaction
    ) -> Tuple[Dict[str, Any], None]:
        """Simulate PayPal order for testing"""
        fake_order_id = f"PAYPAL-SIM-{uuid.uuid4().hex[:12].upper()}"

        transaction.paynow_reference = fake_order_id
        self.db.commit()

        return {
            "order_id": fake_order_id,
            "approval_url": f"https://sandbox.paypal.com/checkoutnow?token={fake_order_id}",
            "reference": transaction.reference,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "simulated": True
        }, None

    def capture_paypal_payment(
        self,
        order_id: str,
        payer_id: str
    ) -> Tuple[Optional[PaymentTransaction], Optional[str]]:
        """Capture/Execute PayPal payment after user approval"""
        try:
            # Find transaction by PayPal order ID
            transaction = self.db.query(PaymentTransaction).filter(
                PaymentTransaction.paynow_reference == order_id
            ).first()

            if not transaction:
                return None, "Transaction not found"

            if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
                # Simulate capture
                transaction.status = PaymentStatus.COMPLETED
                transaction.completed_at = datetime.utcnow()
                self._activate_subscription(transaction)
                self.db.commit()
                return transaction, None

            import paypalrestsdk
            paypalrestsdk.configure({
                "mode": PAYPAL_MODE,
                "client_id": PAYPAL_CLIENT_ID,
                "client_secret": PAYPAL_CLIENT_SECRET
            })

            payment = paypalrestsdk.Payment.find(order_id)

            if payment.execute({"payer_id": payer_id}):
                transaction.status = PaymentStatus.COMPLETED
                transaction.completed_at = datetime.utcnow()
                self._activate_subscription(transaction)
                self.db.commit()
                return transaction, None
            else:
                error_msg = payment.error.get("message", "PayPal payment execution failed")
                transaction.status = PaymentStatus.FAILED
                transaction.error_message = error_msg
                self.db.commit()
                return None, error_msg

        except Exception as e:
            logger.error(f"Error capturing PayPal payment: {str(e)}")
            return None, str(e)

    def handle_paypal_webhook(
        self,
        payload: Dict[str, Any]
    ) -> Tuple[Optional[PaymentTransaction], Optional[str]]:
        """Handle PayPal webhook events"""
        try:
            event_type = payload.get("event_type")
            resource = payload.get("resource", {})

            if event_type == "PAYMENT.SALE.COMPLETED":
                # Get custom field (our reference)
                custom = None
                for transaction_data in resource.get("transactions", []):
                    custom = transaction_data.get("custom")
                    if custom:
                        break

                if custom:
                    transaction = self.db.query(PaymentTransaction).filter(
                        PaymentTransaction.reference == custom
                    ).first()

                    if transaction and transaction.status != PaymentStatus.COMPLETED:
                        transaction.status = PaymentStatus.COMPLETED
                        transaction.completed_at = datetime.utcnow()
                        self._activate_subscription(transaction)
                        self.db.commit()
                        return transaction, None

            elif event_type == "PAYMENT.SALE.DENIED":
                custom = None
                for transaction_data in resource.get("transactions", []):
                    custom = transaction_data.get("custom")
                    if custom:
                        break

                if custom:
                    transaction = self.db.query(PaymentTransaction).filter(
                        PaymentTransaction.reference == custom
                    ).first()

                    if transaction:
                        transaction.status = PaymentStatus.FAILED
                        transaction.error_message = "Payment denied"
                        self.db.commit()
                        return transaction, None

            return None, None

        except Exception as e:
            logger.error(f"Error handling PayPal webhook: {str(e)}")
            return None, str(e)