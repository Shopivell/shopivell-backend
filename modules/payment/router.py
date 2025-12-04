# modules/payments/api.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime
import logging

from database import get_db
from modules.stores.models import Store
from modules.users.models import User
from .models import (
    PaymentTransaction, PaymentStatus, PaymentMethod, 
    SubscriptionPlan, StoreSubscription, PackagePricing, PackageFeature
)
from .schemas import (
    PaymentTransactionCreate, PaymentTransactionResponse,
    PaymentInitiateRequest, PaymentWebhookData, PaymentStatusUpdate,
    StoreSubscriptionResponse, PaymentSummaryResponse,
    PackagePricingResponse, PackagePricingCreate, PackagePricingUpdate,
    PackageComparisonResponse, EcoCashPaymentRequest
)
from utils.payment_service import PaymentService

# Configure logging
logger = logging.getLogger(__name__)

payment_router = APIRouter(prefix="/api/payments", tags=["payments"])

# Package Pricing Endpoints
@payment_router.get("/packages", response_model=List[PackagePricingResponse])
async def get_all_packages(
    active_only: bool = Query(True, description="Only return active packages"),
    db: Session = Depends(get_db)
):
    """Get all package pricing"""
    try:
        query = db.query(PackagePricing)
        if active_only:
            query = query.filter(PackagePricing.is_active == True)
        
        packages = query.order_by(PackagePricing.monthly_price).all()
        return packages
        
    except Exception as e:
        logger.error(f"Error getting packages: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching packages: {str(e)}"
        )

@payment_router.get("/packages/compare", response_model=PackageComparisonResponse)
async def compare_packages(db: Session = Depends(get_db)):
    """Compare all packages"""
    try:
        packages = db.query(PackagePricing).filter(
            PackagePricing.is_active == True
        ).all()
        
        packages_dict = {p.package_name: p for p in packages}
        
        return PackageComparisonResponse(
            free=packages_dict.get(SubscriptionPlan.FREE),
            premium=packages_dict.get(SubscriptionPlan.PREMIUM),
            business=packages_dict.get(SubscriptionPlan.BUSINESS)
        )
        
    except Exception as e:
        logger.error(f"Error comparing packages: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error comparing packages: {str(e)}"
        )

@payment_router.get("/packages/{package_name}", response_model=PackagePricingResponse)
async def get_package(
    package_name: SubscriptionPlan,
    db: Session = Depends(get_db)
):
    """Get specific package details"""
    try:
        package = db.query(PackagePricing).filter(
            PackagePricing.package_name == package_name,
            PackagePricing.is_active == True
        ).first()
        
        if not package:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Package not found or inactive"
            )
        
        return package
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting package: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching package: {str(e)}"
        )

@payment_router.post("/packages", response_model=PackagePricingResponse)
async def create_package(
    package_data: PackagePricingCreate,
    db: Session = Depends(get_db)
):
    """Create new package pricing (admin only)"""
    try:
        # Check if package already exists
        existing = db.query(PackagePricing).filter(
            PackagePricing.package_name == package_data.package_name
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Package already exists"
            )
        
        package = PackagePricing(**package_data.model_dump())
        db.add(package)
        db.commit()
        db.refresh(package)
        
        return package
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating package: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating package: {str(e)}"
        )

@payment_router.patch("/packages/{package_name}", response_model=PackagePricingResponse)
async def update_package(
    package_name: SubscriptionPlan,
    package_data: PackagePricingUpdate,
    db: Session = Depends(get_db)
):
    """Update package pricing (admin only)"""
    try:
        package = db.query(PackagePricing).filter(
            PackagePricing.package_name == package_name
        ).first()
        
        if not package:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Package not found"
            )
        
        update_data = package_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(package, field, value)
        
        db.commit()
        db.refresh(package)
        return package
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating package: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating package: {str(e)}"
        )

# Payment Endpoints
@payment_router.post("/initiate", response_model=Dict[str, Any])
async def initiate_payment(
    payment_request: PaymentInitiateRequest,
    db: Session = Depends(get_db)
):
    """Initiate a payment for store subscription"""
    try:
        # Verify store exists
        store = db.query(Store).filter(Store.id == payment_request.store_id).first()
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )
        
        # Get user from store owner
        user_id = store.owner_id
        
        # Get package pricing
        package = db.query(PackagePricing).filter(
            PackagePricing.package_name == payment_request.package_name,
            PackagePricing.is_active == True
        ).first()
        
        if not package:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Package not found or inactive"
            )
        
        # Determine amount based on billing period
        if payment_request.billing_period == "annual" and package.annual_price:
            amount = package.annual_price
        else:
            amount = package.monthly_price
        
        # Initialize payment service
        payment_service = PaymentService(db)
        
        # Create payment transaction
        transaction, error = payment_service.create_payment_transaction(
            store_id=payment_request.store_id,
            user_id=user_id,
            amount=amount,
            payment_method=payment_request.payment_method,
            package_name=payment_request.package_name,
            billing_period=payment_request.billing_period,
            mobile_number=payment_request.mobile_number
        )
        
        if error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )
        
        # Handle different payment methods
        if payment_request.payment_method == PaymentMethod.ECOCASH:
            if not payment_request.mobile_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Mobile number required for EcoCash payments"
                )
            
            # Use store email or default
            email = f"farairhato@gmail.com"
            
            # Initiate EcoCash payment
            payment_response, payment_error = payment_service.initiate_ecocash_payment(
                transaction=transaction,
                mobile_number=payment_request.mobile_number,
                email=email
            )
            
            if payment_error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to initiate EcoCash payment: {payment_error}"
                )
            
            return {
                "message": "EcoCash payment initiated",
                "transaction": PaymentTransactionResponse.model_validate(transaction),
                "payment_instructions": payment_response
            }
        
        elif payment_request.payment_method == PaymentMethod.INNBUCKS:
            # TODO: Implement InnBucks integration
            return {
                "message": "InnBucks payment initiated (simulation)",
                "transaction": PaymentTransactionResponse.model_validate(transaction),
                "payment_instructions": {
                    "method": "innbucks",
                    "reference": transaction.reference,
                    "amount": amount,
                    "currency": "USD"
                }
            }
        
        elif payment_request.payment_method == PaymentMethod.BANK_TRANSFER:
            return {
                "message": "Bank transfer instructions",
                "transaction": PaymentTransactionResponse.model_validate(transaction),
                "payment_instructions": {
                    "method": "bank_transfer",
                    "bank_name": "Your Bank Name",
                    "account_number": "1234567890",
                    "account_name": "Your Business Name",
                    "reference": transaction.reference,
                    "amount": amount,
                    "currency": "USD"
                }
            }
        
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Payment method {payment_request.payment_method} not yet implemented"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initiating payment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error initiating payment: {str(e)}"
        )

@payment_router.post("/ecocash/initiate", response_model=Dict[str, Any])
async def initiate_ecocash_payment_direct(
    ecocash_request: EcoCashPaymentRequest,
    store_id: uuid.UUID,
    package_name: SubscriptionPlan = SubscriptionPlan.PREMIUM,
    billing_period: str = "monthly",
    db: Session = Depends(get_db)
):
    """Direct EcoCash payment initiation endpoint"""
    try:
        # Verify store exists
        store = db.query(Store).filter(Store.id == store_id).first()
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )
        
        # Create payment request
        payment_request = PaymentInitiateRequest(
            store_id=store_id,
            package_name=package_name,
            payment_method=PaymentMethod.ECOCASH,
            billing_period=billing_period,
            mobile_number=ecocash_request.mobile_number
        )
        
        return await initiate_payment(payment_request, db)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initiating direct EcoCash payment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error initiating payment: {str(e)}"
        )

@payment_router.get("/transactions/{reference}", response_model=PaymentTransactionResponse)
async def get_payment_transaction(
    reference: str,
    db: Session = Depends(get_db)
):
    """Get payment transaction by reference"""
    try:
        transaction = db.query(PaymentTransaction).filter(
            PaymentTransaction.reference == reference
        ).first()
        
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        
        return transaction
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting transaction: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching transaction: {str(e)}"
        )

@payment_router.get("/store/{store_id}/transactions", response_model=List[PaymentTransactionResponse])
async def get_store_transactions(
    store_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[PaymentStatus] = None,
    db: Session = Depends(get_db)
):
    """Get all transactions for a store"""
    try:
        query = db.query(PaymentTransaction).filter(
            PaymentTransaction.store_id == store_id
        )
        
        if status:
            query = query.filter(PaymentTransaction.status == status)
        
        transactions = query.order_by(
            PaymentTransaction.initiated_at.desc()
        ).offset(skip).limit(limit).all()
        
        return transactions
        
    except Exception as e:
        logger.error(f"Error getting store transactions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching transactions: {str(e)}"
        )

@payment_router.get("/store/{store_id}/summary", response_model=PaymentSummaryResponse)
async def get_payment_summary(
    store_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get payment summary for a store"""
    try:
        payment_service = PaymentService(db)
        summary = payment_service.get_payment_summary(store_id)
        return summary
        
    except Exception as e:
        logger.error(f"Error getting payment summary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching payment summary: {str(e)}"
        )

@payment_router.post("/webhook/paynow", status_code=status.HTTP_200_OK)
async def paynow_webhook(
    webhook_data: PaymentWebhookData,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Webhook endpoint for PayNow payment updates"""
    try:
        logger.info(f"Received PayNow webhook: {webhook_data.model_dump()}")
        
        payment_service = PaymentService(db)
        
        # Map PayNow status to our status
        status_map = {
            "paid": PaymentStatus.COMPLETED,
            "sent": PaymentStatus.PROCESSING,
            "cancelled": PaymentStatus.CANCELLED,
            "disputed": PaymentStatus.FAILED,
            "refunded": PaymentStatus.REFUNDED,
            "created": PaymentStatus.PENDING,
            "awaiting delivery": PaymentStatus.PENDING,
            "awaiting funds": PaymentStatus.PROCESSING
        }
        
        status = status_map.get(webhook_data.status.lower(), PaymentStatus.PENDING)
        
        # Update payment status
        transaction, error = payment_service.update_payment_status(
            reference=webhook_data.reference,
            status=status,
            paynow_reference=webhook_data.paynow_reference
        )
        
        if error:
            logger.error(f"Error updating payment status: {error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )
        
        return {"message": "Webhook processed successfully", "reference": webhook_data.reference}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing PayNow webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing webhook: {str(e)}"
        )

@payment_router.post("/status/update", response_model=PaymentTransactionResponse)
async def update_payment_status(
    status_update: PaymentStatusUpdate,
    reference: str,
    db: Session = Depends(get_db)
):
    """Manually update payment status (admin/testing)"""
    try:
        payment_service = PaymentService(db)
        
        transaction, error = payment_service.update_payment_status(
            reference=reference,
            status=status_update.status,
            paynow_reference=status_update.paynow_reference,
            error_message=status_update.error_message
        )
        
        if error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )
        
        return transaction
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating payment status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating status: {str(e)}"
        )

@payment_router.get("/check-status/{reference}", response_model=Dict[str, Any])
async def check_payment_status(
    reference: str,
    db: Session = Depends(get_db)
):
    """Check payment status (polling endpoint for clients)"""
    try:
        transaction = db.query(PaymentTransaction).filter(
            PaymentTransaction.reference == reference
        ).first()
        
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        
        # If transaction has poll_url and is still pending, check with PayNow
        if transaction.status == PaymentStatus.PENDING and transaction.poll_url:
            payment_service = PaymentService(db)
            paynow_status = payment_service.check_payment_status(transaction.poll_url)
            
            # Update if status changed
            if paynow_status.get("status") == "paid":
                transaction, _ = payment_service.update_payment_status(
                    reference=reference,
                    status=PaymentStatus.COMPLETED,
                    paynow_reference=paynow_status.get("paynow_reference")
                )
        
        return {
            "reference": transaction.reference,
            "status": transaction.status,
            "amount": transaction.amount,
            "package_name": transaction.package_name,
            "initiated_at": transaction.initiated_at,
            "completed_at": transaction.completed_at
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking payment status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error checking status: {str(e)}"
        )

# Subscription Endpoints
@payment_router.get("/store/{store_id}/subscription", response_model=StoreSubscriptionResponse)
async def get_store_subscription(
    store_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get store subscription details"""
    try:
        subscription = db.query(StoreSubscription).filter(
            StoreSubscription.store_id == store_id
        ).first()
        
        if not subscription:
            # Return default free subscription
            store = db.query(Store).filter(Store.id == store_id).first()
            if not store:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Store not found"
                )
            
            # Create default subscription response
            return StoreSubscriptionResponse(
                id=uuid.uuid4(),
                store_id=store_id,
                package_name=SubscriptionPlan.FREE,
                billing_period="monthly",
                is_active=True,
                auto_renew=False,
                enabled_features={},
                usage_limits={},
                subscribed_at=datetime.utcnow(),
                current_period_start=datetime.utcnow(),
                current_period_end=datetime.utcnow(),
                cancelled_at=None,
                trial_ends_at=None
            )
        
        return subscription
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching subscription: {str(e)}"
        )

@payment_router.post("/simulate/{reference}", response_model=Dict[str, Any])
async def simulate_payment_completion(
    reference: str,
    db: Session = Depends(get_db)
):
    """Simulate payment completion for testing"""
    try:
        payment_service = PaymentService(db)
        
        success = payment_service.simulate_payment(reference)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        
        return {
            "message": "Payment simulation completed successfully",
            "reference": reference,
            "status": "completed"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error simulating payment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error simulating payment: {str(e)}"
        )

@payment_router.post("/cancel-subscription/{store_id}", response_model=Dict[str, Any])
async def cancel_subscription(
    store_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Cancel store subscription"""
    try:
        subscription = db.query(StoreSubscription).filter(
            StoreSubscription.store_id == store_id,
            StoreSubscription.is_active == True
        ).first()
        
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active subscription not found"
            )
        
        subscription.is_active = False
        subscription.auto_renew = False
        subscription.cancelled_at = datetime.utcnow()
        
        # Downgrade to free package features
        payment_service = PaymentService(db)
        subscription.enabled_features = payment_service._get_package_features(SubscriptionPlan.FREE)
        subscription.usage_limits = payment_service._get_package_limits(SubscriptionPlan.FREE)
        
        # Update store's enabled_features
        store = subscription.store
        if store:
            store.enabled_features = subscription.enabled_features
        
        db.commit()
        
        return {
            "message": "Subscription cancelled successfully",
            "store_id": str(store_id),
            "cancelled_at": subscription.cancelled_at,
            "new_package": SubscriptionPlan.FREE.value
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error cancelling subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cancelling subscription: {str(e)}"
        )