# modules/pos/router.py
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from uuid import UUID
from datetime import datetime
import logging

from database import get_db
from dependencies import get_current_user, CurrentUser
from modules.stores.models import Store
from modules.products.models import Product
from modules.users.models import User
from .models import (
    POSRegister, POSSession, POSTransaction, ExternalPOSIntegration,
    POSSessionStatus, POSTransactionStatus, POSPaymentMethod, ExternalPOSProvider,
    POSRegisterStatus
)
from .schemas import (
    POSRegisterCreate, POSRegisterUpdate, POSRegisterResponse,
    POSSessionCreate, POSSessionClose, POSSessionResponse,
    POSTransactionCreate, POSTransactionResponse, ReceiptResponse,
    ProductLookupResponse, CartItemWithTotal,
    ExternalPOSIntegrationCreate, ExternalPOSIntegrationUpdate, ExternalPOSIntegrationResponse
)

logger = logging.getLogger(__name__)

pos_router = APIRouter(prefix="/api/pos", tags=["pos"])


# ============== REGISTER ENDPOINTS ==============

@pos_router.get("/registers/store/{store_id}", response_model=List[POSRegisterResponse])
async def get_store_registers(
    store_id: UUID,
    status: Optional[POSRegisterStatus] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get all registers for a store"""
    try:
        query = db.query(POSRegister).filter(POSRegister.store_id == store_id)
        if status:
            query = query.filter(POSRegister.status == status)
        return query.order_by(POSRegister.created_at.desc()).all()
    except Exception as e:
        logger.error(f"Error fetching registers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pos_router.get("/registers/{register_id}", response_model=POSRegisterResponse)
async def get_register(
    register_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get a specific register"""
    register = db.query(POSRegister).filter(POSRegister.id == register_id).first()
    if not register:
        raise HTTPException(status_code=404, detail="Register not found")
    return register


@pos_router.post("/registers", response_model=POSRegisterResponse, status_code=status.HTTP_201_CREATED)
async def create_register(
    register_data: POSRegisterCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create a new POS register"""
    # Verify store exists
    store = db.query(Store).filter(Store.id == register_data.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    try:
        register = POSRegister(**register_data.model_dump())
        db.add(register)
        db.commit()
        db.refresh(register)
        return register
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating register: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create register: {str(e)}")


@pos_router.patch("/registers/{register_id}", response_model=POSRegisterResponse)
async def update_register(
    register_id: UUID,
    register_data: POSRegisterUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Update a POS register"""
    register = db.query(POSRegister).filter(POSRegister.id == register_id).first()
    if not register:
        raise HTTPException(status_code=404, detail="Register not found")

    try:
        for field, value in register_data.model_dump(exclude_unset=True).items():
            setattr(register, field, value)

        db.commit()
        db.refresh(register)
        return register
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating register: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pos_router.delete("/registers/{register_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_register(
    register_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Delete a POS register"""
    register = db.query(POSRegister).filter(POSRegister.id == register_id).first()
    if not register:
        raise HTTPException(status_code=404, detail="Register not found")

    try:
        db.delete(register)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting register: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== SESSION ENDPOINTS ==============

@pos_router.post("/sessions/open", response_model=POSSessionResponse, status_code=status.HTTP_201_CREATED)
async def open_session(
    session_data: POSSessionCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Open a new POS session"""
    register = db.query(POSRegister).filter(POSRegister.id == session_data.register_id).first()
    if not register:
        raise HTTPException(status_code=404, detail="Register not found")

    existing = db.query(POSSession).filter(
        POSSession.register_id == session_data.register_id,
        POSSession.status == POSSessionStatus.OPEN
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Register already has an open session")

    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        count = db.query(POSSession).filter(
            POSSession.store_id == session_data.store_id,
            POSSession.session_number.like(f"POS-{today}%")
        ).count()
        session_number = f"POS-{today}-{count + 1:03d}"

        session = POSSession(
            store_id=session_data.store_id,
            register_id=session_data.register_id,
            user_id=current_user.id,
            session_number=session_number,
            opening_balance=session_data.opening_balance,
            notes=session_data.notes
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session
    except Exception as e:
        db.rollback()
        logger.error(f"Error opening session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pos_router.get("/sessions/active/{store_id}", response_model=List[POSSessionResponse])
async def get_active_sessions(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get all open sessions for a store"""
    return db.query(POSSession).filter(
        POSSession.store_id == store_id,
        POSSession.status == POSSessionStatus.OPEN
    ).all()


@pos_router.get("/sessions/store/{store_id}", response_model=List[POSSessionResponse])
async def get_store_sessions(
    store_id: UUID,
    status: Optional[POSSessionStatus] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get all sessions for a store with optional filtering"""
    query = db.query(POSSession).filter(POSSession.store_id == store_id)
    if status:
        query = query.filter(POSSession.status == status)
    return query.order_by(POSSession.opened_at.desc()).offset(skip).limit(limit).all()


@pos_router.get("/sessions/{session_id}", response_model=POSSessionResponse)
async def get_session(
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get session details"""
    session = db.query(POSSession).filter(POSSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@pos_router.post("/sessions/{session_id}/close", response_model=POSSessionResponse)
async def close_session(
    session_id: UUID,
    close_data: POSSessionClose,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Close a POS session"""
    session = db.query(POSSession).filter(POSSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != POSSessionStatus.OPEN:
        raise HTTPException(status_code=400, detail="Session is not open")

    try:
        transactions = db.query(POSTransaction).filter(
            POSTransaction.session_id == session_id,
            POSTransaction.status == POSTransactionStatus.COMPLETED
        ).all()

        total_sales = sum(float(t.total_amount) for t in transactions)
        total_refunds = sum(float(t.total_amount) for t in transactions if t.status == POSTransactionStatus.REFUNDED)
        cash_total = sum(float(t.total_amount) for t in transactions if t.payment_method == POSPaymentMethod.CASH)
        card_total = sum(float(t.total_amount) for t in transactions if t.payment_method == POSPaymentMethod.STRIPE)
        mobile_total = sum(float(t.total_amount) for t in transactions if t.payment_method in [POSPaymentMethod.ECOCASH, POSPaymentMethod.INNBUCKS])

        expected_balance = float(session.opening_balance) + cash_total
        cash_difference = close_data.closing_balance - expected_balance

        session.status = POSSessionStatus.CLOSED
        session.closing_balance = close_data.closing_balance
        session.expected_balance = expected_balance
        session.cash_difference = cash_difference
        session.total_sales = total_sales
        session.total_refunds = total_refunds
        session.total_transactions = len(transactions)
        session.cash_total = cash_total
        session.card_total = card_total
        session.mobile_money_total = mobile_total
        session.closed_at = datetime.utcnow()
        session.notes = close_data.notes or session.notes

        db.commit()
        db.refresh(session)
        return session
    except Exception as e:
        db.rollback()
        logger.error(f"Error closing session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== PRODUCT LOOKUP ENDPOINTS ==============

@pos_router.get("/products/lookup/{store_id}", response_model=List[ProductLookupResponse])
async def lookup_products(
    store_id: UUID,
    query: str = Query(..., min_length=1, description="SKU, barcode, or product name"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Search products by SKU, barcode, or name for POS"""
    products = db.query(Product).filter(
        Product.store_id == store_id,
        Product.status == "Active",
        or_(
            Product.sku.ilike(f"%{query}%"),
            Product.barcode.ilike(f"%{query}%") if hasattr(Product, 'barcode') else False,
            Product.title.ilike(f"%{query}%")
        )
    ).limit(limit).all()

    return [ProductLookupResponse(
        id=p.id,
        title=p.title,
        sku=p.sku,
        barcode=getattr(p, 'barcode', None),
        price=p.price,
        available=p.available if p.available else 0,
        image_url=p.image_url
    ) for p in products]


@pos_router.get("/products/scan/{store_id}/{code}", response_model=ProductLookupResponse)
async def scan_product(
    store_id: UUID,
    code: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get product by exact SKU or barcode (for scanner)"""
    product = db.query(Product).filter(
        Product.store_id == store_id,
        or_(
            Product.sku == code,
            Product.barcode == code if hasattr(Product, 'barcode') else False
        )
    ).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return ProductLookupResponse(
        id=product.id,
        title=product.title,
        sku=product.sku,
        barcode=getattr(product, 'barcode', None),
        price=product.price,
        available=product.available if product.available else 0,
        image_url=product.image_url
    )


# ============== TRANSACTION ENDPOINTS ==============

@pos_router.post("/transactions", response_model=POSTransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    transaction_data: POSTransactionCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create a new POS transaction (sale)"""
    session = db.query(POSSession).filter(POSSession.id == transaction_data.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != POSSessionStatus.OPEN:
        raise HTTPException(status_code=400, detail="Session is not open")

    try:
        items_with_totals = []
        subtotal = 0
        for item in transaction_data.items:
            item_total = (item.price - item.discount) * item.quantity
            subtotal += item_total
            items_with_totals.append({
                "product_id": str(item.product_id),
                "sku": item.sku,
                "name": item.name,
                "quantity": item.quantity,
                "price": float(item.price),
                "discount": float(item.discount),
                "total": float(item_total)
            })

        store = db.query(Store).filter(Store.id == session.store_id).first()
        tax_rate = 0
        if store and store.payment_methods:
            tax_rate = store.payment_methods.get("tax_rate", 0)
        tax_amount = subtotal * (tax_rate / 100)
        total_amount = subtotal + tax_amount - transaction_data.discount_amount

        change_given = None
        if transaction_data.payment_method == POSPaymentMethod.CASH and transaction_data.amount_tendered:
            if transaction_data.amount_tendered < total_amount:
                raise HTTPException(status_code=400, detail="Amount tendered is less than total")
            change_given = transaction_data.amount_tendered - total_amount

        count = db.query(POSTransaction).filter(
            POSTransaction.session_id == session.id
        ).count()
        transaction_number = f"{session.session_number}-{count + 1:04d}"

        transaction = POSTransaction(
            store_id=session.store_id,
            session_id=session.id,
            transaction_number=transaction_number,
            status=POSTransactionStatus.PENDING,
            customer_id=transaction_data.customer_id,
            customer_name=transaction_data.customer_name,
            customer_phone=transaction_data.customer_phone,
            subtotal=subtotal,
            tax_amount=tax_amount,
            discount_amount=transaction_data.discount_amount,
            total_amount=total_amount,
            payment_method=transaction_data.payment_method,
            amount_tendered=transaction_data.amount_tendered,
            change_given=change_given,
            items=items_with_totals,
            notes=transaction_data.notes
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        return transaction
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating transaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pos_router.get("/transactions/session/{session_id}", response_model=List[POSTransactionResponse])
async def get_session_transactions(
    session_id: UUID,
    status: Optional[POSTransactionStatus] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get all transactions for a session"""
    query = db.query(POSTransaction).filter(POSTransaction.session_id == session_id)
    if status:
        query = query.filter(POSTransaction.status == status)
    return query.order_by(POSTransaction.created_at.desc()).all()


@pos_router.get("/transactions/{transaction_id}", response_model=POSTransactionResponse)
async def get_transaction(
    transaction_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get transaction details"""
    transaction = db.query(POSTransaction).filter(POSTransaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction


@pos_router.post("/transactions/{transaction_id}/complete", response_model=POSTransactionResponse)
async def complete_transaction(
    transaction_id: UUID,
    payment_reference: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Complete a transaction after payment confirmation"""
    transaction = db.query(POSTransaction).filter(POSTransaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.status != POSTransactionStatus.PENDING:
        raise HTTPException(status_code=400, detail="Transaction is not pending")

    try:
        for item in transaction.items:
            product = db.query(Product).filter(Product.id == item["product_id"]).first()
            if product:
                if product.available:
                    product.available = max(0, product.available - item["quantity"])
                if product.on_hand:
                    product.on_hand = max(0, product.on_hand - item["quantity"])

        transaction.status = POSTransactionStatus.COMPLETED
        transaction.payment_reference = payment_reference
        transaction.completed_at = datetime.utcnow()

        db.commit()
        db.refresh(transaction)
        return transaction
    except Exception as e:
        db.rollback()
        logger.error(f"Error completing transaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pos_router.post("/transactions/{transaction_id}/void", response_model=POSTransactionResponse)
async def void_transaction(
    transaction_id: UUID,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Void a transaction"""
    transaction = db.query(POSTransaction).filter(POSTransaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    try:
        if transaction.status == POSTransactionStatus.COMPLETED:
            for item in transaction.items:
                product = db.query(Product).filter(Product.id == item["product_id"]).first()
                if product:
                    if product.available is not None:
                        product.available += item["quantity"]
                    if product.on_hand is not None:
                        product.on_hand += item["quantity"]

        transaction.status = POSTransactionStatus.VOIDED
        transaction.voided_at = datetime.utcnow()
        if reason:
            transaction.notes = f"{transaction.notes or ''}\nVoided: {reason}".strip()

        db.commit()
        db.refresh(transaction)
        return transaction
    except Exception as e:
        db.rollback()
        logger.error(f"Error voiding transaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pos_router.get("/transactions/{transaction_id}/receipt", response_model=ReceiptResponse)
async def get_receipt(
    transaction_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get receipt data for printing"""
    transaction = db.query(POSTransaction).filter(POSTransaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    session = db.query(POSSession).filter(POSSession.id == transaction.session_id).first()
    store = db.query(Store).filter(Store.id == transaction.store_id).first()
    register = db.query(POSRegister).filter(POSRegister.id == session.register_id).first() if session else None
    cashier = db.query(User).filter(User.id == session.user_id).first() if session else None

    items = [CartItemWithTotal(
        product_id=item["product_id"],
        sku=item["sku"],
        name=item["name"],
        quantity=item["quantity"],
        price=item["price"],
        discount=item.get("discount", 0),
        total=item["total"]
    ) for item in transaction.items]

    return ReceiptResponse(
        transaction_number=transaction.transaction_number,
        store_name=store.store_name if store else "Store",
        store_address=store.store_address if store else None,
        store_phone=store.store_phone if store else None,
        cashier_name=cashier.name if cashier else "Cashier",
        date=transaction.created_at,
        items=items,
        subtotal=float(transaction.subtotal),
        tax_amount=float(transaction.tax_amount),
        discount_amount=float(transaction.discount_amount),
        total_amount=float(transaction.total_amount),
        payment_method=transaction.payment_method.value,
        amount_tendered=float(transaction.amount_tendered) if transaction.amount_tendered else None,
        change_given=float(transaction.change_given) if transaction.change_given else None,
        receipt_header=register.receipt_header if register else None,
        receipt_footer=register.receipt_footer if register else None
    )


# ============== EXTERNAL POS WEBHOOKS ==============

@pos_router.post("/webhooks/square")
async def square_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Handle Square POS webhooks"""
    try:
        payload = await request.json()
        logger.info(f"Square webhook received: {payload.get('type')}")

        merchant_id = payload.get("merchant_id")
        if merchant_id:
            integration = db.query(ExternalPOSIntegration).filter(
                ExternalPOSIntegration.merchant_id == merchant_id,
                ExternalPOSIntegration.provider == ExternalPOSProvider.SQUARE
            ).first()

            if integration and integration.auto_sync_orders:
                event_type = payload.get("type")
                if event_type in ["payment.completed", "order.created", "order.updated"]:
                    background_tasks.add_task(sync_square_event, payload, integration.store_id, db)

        return {"status": "received"}
    except Exception as e:
        logger.error(f"Square webhook error: {e}")
        return {"status": "error", "message": str(e)}


@pos_router.post("/webhooks/clover")
async def clover_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Handle Clover POS webhooks"""
    try:
        payload = await request.json()
        logger.info(f"Clover webhook received: {payload}")

        merchants = payload.get("merchants", {})
        for merchant_id, events in merchants.items():
            integration = db.query(ExternalPOSIntegration).filter(
                ExternalPOSIntegration.merchant_id == merchant_id,
                ExternalPOSIntegration.provider == ExternalPOSProvider.CLOVER
            ).first()

            if integration and integration.auto_sync_orders:
                for event in events:
                    if "O:" in event:
                        background_tasks.add_task(sync_clover_event, merchant_id, event, integration.store_id, db)

        return {"status": "received"}
    except Exception as e:
        logger.error(f"Clover webhook error: {e}")
        return {"status": "error", "message": str(e)}


# ============== EXTERNAL POS INTEGRATION ENDPOINTS ==============

@pos_router.get("/integrations/{store_id}", response_model=List[ExternalPOSIntegrationResponse])
async def get_integrations(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get external POS integrations for a store"""
    return db.query(ExternalPOSIntegration).filter(
        ExternalPOSIntegration.store_id == store_id
    ).all()


@pos_router.post("/integrations", response_model=ExternalPOSIntegrationResponse, status_code=status.HTTP_201_CREATED)
async def create_integration(
    integration_data: ExternalPOSIntegrationCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create an external POS integration"""
    existing = db.query(ExternalPOSIntegration).filter(
        ExternalPOSIntegration.store_id == integration_data.store_id,
        ExternalPOSIntegration.provider == integration_data.provider
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"{integration_data.provider.value} integration already exists")

    try:
        integration = ExternalPOSIntegration(**integration_data.model_dump())
        db.add(integration)
        db.commit()
        db.refresh(integration)
        return integration
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating integration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pos_router.patch("/integrations/{integration_id}", response_model=ExternalPOSIntegrationResponse)
async def update_integration(
    integration_id: UUID,
    integration_data: ExternalPOSIntegrationUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Update an external POS integration"""
    integration = db.query(ExternalPOSIntegration).filter(
        ExternalPOSIntegration.id == integration_id
    ).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    try:
        for field, value in integration_data.model_dump(exclude_unset=True).items():
            setattr(integration, field, value)

        db.commit()
        db.refresh(integration)
        return integration
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating integration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@pos_router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    integration_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Delete an external POS integration"""
    integration = db.query(ExternalPOSIntegration).filter(
        ExternalPOSIntegration.id == integration_id
    ).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    try:
        db.delete(integration)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting integration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== BACKGROUND TASKS ==============

async def sync_square_event(payload: dict, store_id: UUID, db: Session):
    """Sync Square event to Shopivell"""
    logger.info(f"Processing Square event for store {store_id}: {payload.get('type')}")
    # Implementation would fetch order details from Square API and create/update local records


async def sync_clover_event(merchant_id: str, event: str, store_id: UUID, db: Session):
    """Sync Clover event to Shopivell"""
    logger.info(f"Processing Clover event for store {store_id}: {event}")
    # Implementation would fetch order details from Clover API and create/update local records
