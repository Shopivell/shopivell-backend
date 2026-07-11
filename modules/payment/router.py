# modules/payments/api.py
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, status, Request
from fastapi.responses import JSONResponse
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


def _apply_store_discount(db: Session, store_id, amount: float, payment_method_label: str = "") -> float:
    """Check for an active store discount and reduce the amount accordingly.
    Returns the (possibly reduced) amount."""
    subscription = db.query(StoreSubscription).filter(
        StoreSubscription.store_id == store_id
    ).first()
    if subscription and subscription.usage_limits:
        discount_info = subscription.usage_limits.get("discount")
        if discount_info and discount_info.get("is_active"):
            discount_percent = float(discount_info["discount_percent"])
            original_amount = float(amount)
            amount = round(original_amount * (1 - discount_percent / 100), 2)
            if amount < 0:
                amount = 0.0
            logger.info(
                f"Store discount applied{' for ' + payment_method_label if payment_method_label else ''} "
                f"(store {store_id}): {discount_percent}% off, "
                f"${original_amount:.2f} -> ${amount:.2f} "
                f"(reason: {discount_info.get('reason', 'N/A')})"
            )
    return amount


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
            status_code=500,
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
            status_code=500,
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
            status_code=500,
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
            status_code=500,
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
            status_code=500,
            detail=f"Error updating package: {str(e)}"
        )

# Payment Endpoints
@payment_router.post("/initiate")
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
        
        # Determine amount based on billing period. `quantity` bills multiple units
        # (e.g. pages/stores on the per-page Custom plan) at the package's unit price.
        quantity = max(1, payment_request.quantity)
        if payment_request.billing_period == "annual" and package.annual_price:
            amount = package.annual_price * quantity
        else:
            amount = package.monthly_price * quantity

        # In TEST_MODE, override amount to $0.01 for testing
        import os
        test_mode = os.environ.get("TEST_MODE", "false").lower() == "true"
        if test_mode:
            logger.info(f"TEST_MODE enabled: overriding amount from ${amount} to $0.01 for package {payment_request.package_name}")
            amount = 0.01

        # Apply store discount if one exists
        amount = _apply_store_discount(db, payment_request.store_id, amount, "EcoCash/InnBucks")

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
            mobile_number=payment_request.mobile_number,
            tokens_to_redeem=payment_request.tokens_to_redeem,
            quantity=quantity
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
            
            # Manually serialize transaction to avoid Pydantic serialization issues
            tx_dict = {
                "id": str(transaction.id),
                "store_id": str(transaction.store_id),
                "user_id": str(transaction.user_id),
                "reference": transaction.reference,
                "amount": float(transaction.amount),
                "currency": transaction.currency,
                "payment_method": transaction.payment_method.value if hasattr(transaction.payment_method, 'value') else str(transaction.payment_method),
                "status": transaction.status.value if hasattr(transaction.status, 'value') else str(transaction.status),
                "poll_url": transaction.poll_url,
                "paynow_reference": transaction.paynow_reference,
                "mobile_number": transaction.mobile_number,
                "package_name": transaction.package_name.value if hasattr(transaction.package_name, 'value') else str(transaction.package_name),
                "billing_period": transaction.billing_period,
                "initiated_at": transaction.initiated_at.isoformat() if transaction.initiated_at else None,
                "completed_at": transaction.completed_at.isoformat() if transaction.completed_at else None
            }

            return JSONResponse(content={
                "message": "EcoCash payment initiated",
                "transaction": tx_dict,
                "payment_instructions": payment_response
            })
        
        elif payment_request.payment_method == PaymentMethod.INNBUCKS:
            if not payment_request.mobile_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Mobile number required for InnBucks payments"
                )

            email = "farairhato@gmail.com"

            # Initiate InnBucks payment
            payment_response, payment_error = payment_service.initiate_innbucks_payment(
                transaction=transaction,
                mobile_number=payment_request.mobile_number,
                email=email
            )

            if payment_error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to initiate InnBucks payment: {payment_error}"
                )

            # Manually serialize transaction
            tx_dict = {
                "id": str(transaction.id),
                "store_id": str(transaction.store_id),
                "user_id": str(transaction.user_id),
                "reference": transaction.reference,
                "amount": float(transaction.amount),
                "currency": transaction.currency,
                "payment_method": transaction.payment_method.value if hasattr(transaction.payment_method, 'value') else str(transaction.payment_method),
                "status": transaction.status.value if hasattr(transaction.status, 'value') else str(transaction.status),
                "poll_url": transaction.poll_url,
                "paynow_reference": transaction.paynow_reference,
                "mobile_number": transaction.mobile_number,
                "package_name": transaction.package_name.value if hasattr(transaction.package_name, 'value') else str(transaction.package_name),
                "billing_period": transaction.billing_period,
                "initiated_at": transaction.initiated_at.isoformat() if transaction.initiated_at else None,
                "completed_at": transaction.completed_at.isoformat() if transaction.completed_at else None
            }

            return JSONResponse(content={
                "message": "InnBucks payment initiated",
                "transaction": tx_dict,
                "payment_instructions": payment_response
            })
        
        elif payment_request.payment_method == PaymentMethod.BANK_TRANSFER:
            # Manually serialize transaction
            tx_dict = {
                "id": str(transaction.id),
                "store_id": str(transaction.store_id),
                "user_id": str(transaction.user_id),
                "reference": transaction.reference,
                "amount": float(transaction.amount),
                "currency": transaction.currency,
                "payment_method": transaction.payment_method.value if hasattr(transaction.payment_method, 'value') else str(transaction.payment_method),
                "status": transaction.status.value if hasattr(transaction.status, 'value') else str(transaction.status),
                "package_name": transaction.package_name.value if hasattr(transaction.package_name, 'value') else str(transaction.package_name),
                "billing_period": transaction.billing_period,
                "initiated_at": transaction.initiated_at.isoformat() if transaction.initiated_at else None
            }

            return JSONResponse(content={
                "message": "Bank transfer instructions",
                "transaction": tx_dict,
                "payment_instructions": {
                    "method": "bank_transfer",
                    "bank_name": "Your Bank Name",
                    "account_number": "1234567890",
                    "account_name": "Your Business Name",
                    "reference": transaction.reference,
                    "amount": float(amount),
                    "currency": "USD"
                }
            })
        
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
            status_code=500,
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
            status_code=500,
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
            status_code=500,
            detail=f"Error fetching transaction: {str(e)}"
        )

@payment_router.get("/receipt/{reference}", response_model=Dict[str, Any])
async def get_payment_receipt(
    reference: str,
    db: Session = Depends(get_db)
):
    """Get receipt for a completed payment"""
    try:
        payment_service = PaymentService(db)
        receipt = payment_service.generate_receipt(reference)

        if not receipt:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )

        return receipt

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating receipt: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating receipt: {str(e)}"
        )


@payment_router.post("/send-receipt", response_model=Dict[str, Any])
async def send_receipt_email(
    data: Dict[str, str],
    db: Session = Depends(get_db)
):
    """Send payment receipt via email"""
    try:
        reference = data.get("reference")
        email = data.get("email")

        if not reference or not email:
            raise HTTPException(status_code=400, detail="Reference and email are required")

        payment_service = PaymentService(db)
        receipt = payment_service.generate_receipt(reference)

        if not receipt:
            raise HTTPException(status_code=404, detail="Transaction not found")

        # Build email body
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #111; margin-bottom: 5px;">Shopivell</h1>
                <p style="color: #666;">Payment Receipt</p>
            </div>
            <div style="background: #f9f9f9; border-radius: 12px; padding: 24px; margin-bottom: 20px;">
                <h2 style="color: #111; margin-top: 0;">Payment Successful</h2>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 8px 0; color: #666;">Receipt #</td><td style="padding: 8px 0; text-align: right; font-weight: 600;">{receipt['receipt_number']}</td></tr>
                    <tr><td style="padding: 8px 0; color: #666;">Package</td><td style="padding: 8px 0; text-align: right; font-weight: 600;">{receipt['package_name'].capitalize()}</td></tr>
                    <tr><td style="padding: 8px 0; color: #666;">Billing</td><td style="padding: 8px 0; text-align: right;">{receipt.get('billing_period', 'monthly').capitalize()}</td></tr>
                    <tr><td style="padding: 8px 0; color: #666;">Method</td><td style="padding: 8px 0; text-align: right;">{receipt['payment_method'].upper()}</td></tr>
                    <tr><td style="padding: 8px 0; color: #666;">Date</td><td style="padding: 8px 0; text-align: right;">{receipt.get('completed_at', '')[:10] if receipt.get('completed_at') else ''}</td></tr>
                    <tr style="border-top: 2px solid #ddd;"><td style="padding: 12px 0; font-weight: 700; font-size: 18px;">Total</td><td style="padding: 12px 0; text-align: right; font-weight: 700; font-size: 18px;">${receipt['amount']:.2f} {receipt['currency']}</td></tr>
                </table>
            </div>
            <p style="color: #666; font-size: 14px; text-align: center;">Thank you for your subscription!</p>
        </body>
        </html>
        """

        from utils.Verification_Codes_Services import VerificationCodeService
        VerificationCodeService.initialize()
        success = VerificationCodeService.send_email(
            to_email=email,
            subject=f"Shopivell Payment Receipt - {receipt['receipt_number']}",
            body=body,
            content_type='html'
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to send email")

        return {"message": "Receipt sent successfully", "email": email}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending receipt: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error sending receipt: {str(e)}")


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
            status_code=500,
            detail=f"Error fetching transactions: {str(e)}"
        )

@payment_router.get("/store/{store_id}/summary", response_model=Dict[str, Any])
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
            status_code=500,
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
        
        payment_status = status_map.get(webhook_data.status.lower(), PaymentStatus.PENDING)

        # Update payment status
        transaction, error = payment_service.update_payment_status(
            reference=webhook_data.reference,
            status=payment_status,
            paynow_reference=webhook_data.paynow_reference
        )

        if error:
            logger.error(f"Error updating payment status: {error}")
            raise HTTPException(
                status_code=400,
                detail=error
            )
        
        return {"message": "Webhook processed successfully", "reference": webhook_data.reference}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing PayNow webhook: {str(e)}")
        raise HTTPException(
            status_code=500,
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
            status_code=500,
            detail=f"Error updating status: {str(e)}"
        )

@payment_router.get("/check-status/{reference}", response_model=Dict[str, Any])
async def check_payment_status(
    reference: str,
    db: Session = Depends(get_db)
):
    """
    Check payment status (polling endpoint for clients).

    For mobile money payments (EcoCash, InnBucks), this will poll PayNow
    to check if the payment has been completed and update the transaction accordingly.
    """
    try:
        transaction = db.query(PaymentTransaction).filter(
            PaymentTransaction.reference == reference
        ).first()

        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )

        # If transaction has poll_url and is still pending/processing, check with PayNow
        if transaction.status in [PaymentStatus.PENDING, PaymentStatus.PROCESSING] and transaction.poll_url:
            payment_service = PaymentService(db)

            # Use the improved poll_and_update method
            updated_transaction, poll_error = payment_service.poll_and_update_transaction(reference)

            if updated_transaction:
                transaction = updated_transaction

            if poll_error:
                logger.warning(f"Poll error for {reference}: {poll_error}")

        return {
            "reference": transaction.reference,
            "status": transaction.status.value if hasattr(transaction.status, 'value') else transaction.status,
            "amount": transaction.amount,
            "package_name": transaction.package_name.value if hasattr(transaction.package_name, 'value') else transaction.package_name,
            "payment_method": transaction.payment_method.value if hasattr(transaction.payment_method, 'value') else transaction.payment_method,
            "initiated_at": transaction.initiated_at.isoformat() if transaction.initiated_at else None,
            "completed_at": transaction.completed_at.isoformat() if transaction.completed_at else None,
            "paynow_reference": transaction.paynow_reference,
            "error_message": transaction.error_message
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking payment status: {str(e)}")
        raise HTTPException(
            status_code=500,
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

            # Create a real trial subscription in DB so it persists
            from datetime import timedelta
            trial_end = datetime.utcnow() + timedelta(days=30)
            subscription = StoreSubscription(
                store_id=store_id,
                package_name=SubscriptionPlan.FREE,
                billing_period="monthly",
                is_active=True,
                auto_renew=False,
                subscribed_at=datetime.utcnow(),
                current_period_start=datetime.utcnow(),
                current_period_end=trial_end,
                trial_ends_at=trial_end,
                enabled_features={
                    "max_products": 10,
                    "max_orders": 50,
                    "analytics": False,
                    "custom_domain": False,
                    "priority_support": False
                },
                usage_limits={
                    "api_calls_per_day": 100,
                    "storage_mb": 100
                }
            )
            db.add(subscription)
            db.commit()
            db.refresh(subscription)

        return subscription
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting subscription: {str(e)}")
        raise HTTPException(
            status_code=500,
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
            status_code=500,
            detail=f"Error simulating payment: {str(e)}"
        )

# Stripe Endpoints
@payment_router.post("/stripe/create-intent", response_model=Dict[str, Any])
async def create_stripe_payment_intent(
    payment_request: PaymentInitiateRequest,
    db: Session = Depends(get_db)
):
    """Create Stripe PaymentIntent for card payments"""
    try:
        # Verify store exists
        store = db.query(Store).filter(Store.id == payment_request.store_id).first()
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )

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

        # Determine amount (quantity bills multiple units at the unit price)
        quantity = max(1, payment_request.quantity)
        if payment_request.billing_period == "annual" and package.annual_price:
            amount = package.annual_price * quantity
        else:
            amount = package.monthly_price * quantity

        # Apply store discount if one exists
        amount = _apply_store_discount(db, payment_request.store_id, amount, "Stripe")

        payment_service = PaymentService(db)

        # Create transaction
        transaction, error = payment_service.create_payment_transaction(
            store_id=payment_request.store_id,
            user_id=store.owner_id,
            amount=amount,
            payment_method=PaymentMethod.STRIPE,
            package_name=payment_request.package_name,
            billing_period=payment_request.billing_period,
            quantity=quantity
        )

        if error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )

        # Create Stripe PaymentIntent
        intent_data, intent_error = payment_service.create_stripe_payment_intent(transaction)

        if intent_error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to create Stripe intent: {intent_error}"
            )

        return {
            "message": "Stripe PaymentIntent created",
            "transaction": PaymentTransactionResponse.model_validate(transaction),
            **intent_data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating Stripe intent: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating Stripe intent: {str(e)}"
        )


@payment_router.post("/stripe/confirm/{payment_intent_id}", response_model=Dict[str, Any])
async def confirm_stripe_payment(
    payment_intent_id: str,
    db: Session = Depends(get_db)
):
    """Confirm Stripe payment after client-side completion"""
    try:
        payment_service = PaymentService(db)
        transaction, error = payment_service.confirm_stripe_payment(payment_intent_id)

        if error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )

        return {
            "message": "Payment confirmed successfully",
            "transaction": PaymentTransactionResponse.model_validate(transaction),
            "status": transaction.status.value
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error confirming Stripe payment: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error confirming payment: {str(e)}"
        )


@payment_router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """Handle Stripe webhook events"""
    import os

    try:
        payload = await request.body()
        sig_header = request.headers.get("Stripe-Signature", "")
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

        payment_service = PaymentService(db)
        transaction, error = payment_service.handle_stripe_webhook(
            payload, sig_header, webhook_secret
        )

        if error and error != "Stripe not configured":
            logger.error(f"Stripe webhook error: {error}")

        return {"received": True}

    except Exception as e:
        logger.error(f"Error processing Stripe webhook: {str(e)}")
        return {"received": True, "error": str(e)}


# PayPal Endpoints
@payment_router.post("/paypal/create-order", response_model=Dict[str, Any])
async def create_paypal_order(
    payment_request: PaymentInitiateRequest,
    db: Session = Depends(get_db)
):
    """Create PayPal order"""
    try:
        # Verify store exists
        store = db.query(Store).filter(Store.id == payment_request.store_id).first()
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )

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

        # Determine amount (quantity bills multiple units at the unit price)
        quantity = max(1, payment_request.quantity)
        if payment_request.billing_period == "annual" and package.annual_price:
            amount = package.annual_price * quantity
        else:
            amount = package.monthly_price * quantity

        # Apply store discount if one exists
        amount = _apply_store_discount(db, payment_request.store_id, amount, "PayPal")

        payment_service = PaymentService(db)

        # Create transaction
        transaction, error = payment_service.create_payment_transaction(
            store_id=payment_request.store_id,
            user_id=store.owner_id,
            amount=amount,
            payment_method=PaymentMethod.PAYPAL,
            package_name=payment_request.package_name,
            billing_period=payment_request.billing_period,
            quantity=quantity
        )

        if error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )

        # Create PayPal order
        order_data, order_error = payment_service.create_paypal_order(transaction)

        if order_error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to create PayPal order: {order_error}"
            )

        return {
            "message": "PayPal order created",
            "transaction": PaymentTransactionResponse.model_validate(transaction),
            **order_data
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating PayPal order: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating PayPal order: {str(e)}"
        )


@payment_router.post("/paypal/capture/{order_id}", response_model=Dict[str, Any])
async def capture_paypal_payment(
    order_id: str,
    payer_id: str = Query(..., description="PayPal payer ID"),
    db: Session = Depends(get_db)
):
    """Capture PayPal payment after user approval"""
    try:
        payment_service = PaymentService(db)
        transaction, error = payment_service.capture_paypal_payment(order_id, payer_id)

        if error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )

        return {
            "message": "Payment captured successfully",
            "transaction": PaymentTransactionResponse.model_validate(transaction),
            "status": transaction.status.value
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error capturing PayPal payment: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error capturing payment: {str(e)}"
        )


@payment_router.post("/paypal/webhook", status_code=status.HTTP_200_OK)
async def paypal_webhook(
    webhook_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Handle PayPal webhook events"""
    try:
        payment_service = PaymentService(db)
        transaction, error = payment_service.handle_paypal_webhook(webhook_data)

        if error:
            logger.error(f"PayPal webhook error: {error}")

        return {"received": True}

    except Exception as e:
        logger.error(f"Error processing PayPal webhook: {str(e)}")
        return {"received": True, "error": str(e)}


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
        subscription.package_name = SubscriptionPlan.FREE

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
            status_code=500,
            detail=f"Error cancelling subscription: {str(e)}"
        )