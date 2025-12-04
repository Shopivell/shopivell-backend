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
import os

logger = logging.getLogger(__name__)

class PaymentService:
    def __init__(self, db: Session):
        self.db = db
        self.paynow = None
        self._init_paynow()
    
    def _init_paynow(self):
        """Initialize PayNow integration"""
        try:
            from paynow import Paynow
            
            integration_id = os.getenv("PAYNOW_INTEGRATION_ID", "INTEGRATION_ID")
            integration_key = os.getenv("PAYNOW_INTEGRATION_KEY", "INTEGRATION_KEY")
            return_url = os.getenv("PAYNOW_RETURN_URL", "")
            result_url = os.getenv("PAYNOW_RESULT_URL", "")
            
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
        mobile_number: Optional[str] = None
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
            
            # Create transaction
            transaction = PaymentTransaction(
                store_id=store_id,
                user_id=user_id,
                reference=reference,
                amount=amount,
                currency="USD",
                payment_method=payment_method,
                package_name=package_name,
                billing_period=billing_period,
                mobile_number=mobile_number,
                status=PaymentStatus.PENDING,
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
        """Initiate EcoCash payment via PayNow"""
        try:
            if not self.paynow:
                # Simulate PayNow response for testing
                logger.info("PayNow not configured, simulating payment")
                return self._simulate_paynow_payment(transaction, mobile_number)
            
            # Real PayNow integration
            description = f"{transaction.package_name.value.capitalize()} Subscription"
            payment = self.paynow.create_payment(description, email)
            
            payment.add(f"Store Subscription", float(transaction.amount))
            
            # FIXED: Handle PayNow response safely
            response = self.paynow.send_mobile(payment, mobile_number, 'ecocash')
            
            # Debug log to see what response looks like
            logger.info(f"PayNow response type: {type(response)}")
            logger.info(f"PayNow response attributes: {dir(response)}")
            
            if response.success:
                # Safely extract PayNow reference
                paynow_ref = self._extract_paynow_reference(response)
                
                # Update transaction
                transaction.poll_url = getattr(response, 'poll_url', None)
                transaction.paynow_reference = paynow_ref
                transaction.mobile_number = mobile_number
                
                self.db.commit()
                
                return {
                    "poll_url": transaction.poll_url,
                    "paynow_reference": paynow_ref,
                    "instruction": getattr(response, 'instruction', 'Check your phone for payment prompt'),
                    "reference": transaction.reference
                }, None
            else:
                # FIXED: Safely extract error message
                error_msg = self._extract_error_message(response)
                
                transaction.status = PaymentStatus.FAILED
                transaction.error_message = error_msg
                self.db.commit()
                return None, error_msg
                
        except Exception as e:
            logger.error(f"Error initiating EcoCash payment: {str(e)}")
            
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
        """Check payment status from PayNow"""
        try:
            if not self.paynow:
                return {"status": "pending", "message": "PayNow not configured - simulation mode"}
            
            status = self.paynow.check_transaction_status(poll_url)
            
            result = {
                "status": "unknown",
                "amount": None,
                "reference": None,
                "paynow_reference": None
            }
            
            # Safely extract attributes
            if hasattr(status, 'status'):
                result["status"] = str(status.status).lower()
            if hasattr(status, 'amount'):
                result["amount"] = status.amount
            if hasattr(status, 'reference'):
                result["reference"] = str(status.reference)
            
            # Extract PayNow reference
            result["paynow_reference"] = self._extract_paynow_reference(status)
            
            return result
            
        except Exception as e:
            logger.error(f"Error checking payment status: {str(e)}")
            return {"status": "error", "message": str(e)}
    
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
                "support_response_time": "48h"
            },
            SubscriptionPlan.PREMIUM: {
                "monthly_bandwidth": "10GB",
                "storage": "1GB",
                "api_calls": 10000,
                "support_response_time": "24h"
            },
            SubscriptionPlan.BUSINESS: {
                "monthly_bandwidth": "100GB",
                "storage": "10GB",
                "api_calls": 100000,
                "support_response_time": "4h"
            }
        }
        
        return limits_map.get(package_name, limits_map[SubscriptionPlan.FREE])
    
    def _update_subscription_features(self, subscription: StoreSubscription):
        """Update subscription features based on package"""
        subscription.enabled_features = self._get_package_features(subscription.package_name)
        subscription.usage_limits = self._get_package_limits(subscription.package_name)