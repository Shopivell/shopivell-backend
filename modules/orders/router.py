from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from database import get_db
from dependencies import get_current_user, CurrentUser
from modules.orders.models import CustomerOrder
from modules.orders.schemas import (
    CustomerOrderCreate,
    CustomerOrderListResponse,
    CustomerOrderResponse,
    CustomerOrderUpdate
)
from modules.stores.models import Store

from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

order_router = APIRouter(prefix="/api/orders", tags=["orders"])


def _auto_create_delivery(db: Session, order: CustomerOrder, delivery_address: str, delivery_city: str = None):
    """Auto-create a Delivery record linked to an order."""
    try:
        from modules.delivery.models import Delivery, DeliveryTracking

        # Build full address
        full_address = delivery_address
        if delivery_city:
            full_address = f"{delivery_address}, {delivery_city}"

        # Get store info for pickup address
        store = db.query(Store).filter(Store.id == order.store_id).first()
        pickup_addr = None
        if store:
            parts = [p for p in [store.store_address, store.store_city, store.store_country] if p]
            pickup_addr = ", ".join(parts) if parts else None

        delivery = Delivery(
            store_id=order.store_id,
            order_id=order.id,
            customer_name=order.customer_name,
            customer_phone=order.phone,
            delivery_address=full_address,
            pickup_address=pickup_addr or "Store pickup",
            package_description=order.product_name,
            status="pending",
        )
        db.add(delivery)
        db.flush()  # get the ID and tracking_number

        # Create initial tracking event
        tracking_event = DeliveryTracking(
            delivery_id=delivery.id,
            status="pending",
            location="Order placed",
            notes=f"Order {order.order_number} - delivery created automatically",
        )
        db.add(tracking_event)
        db.commit()
        db.refresh(delivery)

        # Update order with tracking number
        order.tracking_info = f"Tracking: {delivery.tracking_number}"
        db.commit()

        logger.info(f"Auto-created delivery {delivery.tracking_number} for order {order.order_number}")
        return delivery

    except Exception as e:
        logger.warning(f"Auto-delivery creation failed (non-critical): {e}")
        # Don't fail the order if delivery creation fails
        return None


# ============ Public Schemas ============

class PublicOrderItem(BaseModel):
    product_id: uuid.UUID
    product_name: str
    quantity: int = Field(ge=1)
    price: float = Field(ge=0)
    image: Optional[str] = None

class PublicOrderCreate(BaseModel):
    store_id: uuid.UUID
    customer_name: str
    phone: str
    email: Optional[str] = None
    items: list[PublicOrderItem]
    delivery_method: str = "delivery"  # "delivery" or "pickup"
    delivery_address: Optional[str] = None
    delivery_city: Optional[str] = None
    delivery_fee: float = 0
    discount_code: Optional[str] = None
    discount_amount: float = 0
    special_request: Optional[str] = None


def generate_order_number(db: Session, store_id: uuid.UUID) -> str:
    """Generate a unique order number for the store"""
    import random
    import string

    while True:
        # Format: ORD-XXXXX (5 random alphanumeric)
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        order_number = f"ORD-{suffix}"

        # Check if exists for this store
        existing = db.query(CustomerOrder).filter(
            CustomerOrder.store_id == store_id,
            CustomerOrder.order_number == order_number
        ).first()

        if not existing:
            return order_number


# GET all orders for the authenticated user's store
@order_router.get("/", response_model=CustomerOrderListResponse)
async def get_orders(
    store_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    payment_status: Optional[str] = None,
    delivery_status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    try:
        # Build query with store filter
        query = db.query(CustomerOrder).filter(CustomerOrder.store_id == store_id)

        if status:
            query = query.filter(CustomerOrder.status == status)
        if customer_id:
            query = query.filter(CustomerOrder.customer_id == customer_id)
        if payment_status:
            query = query.filter(CustomerOrder.payment_status == payment_status)
        if delivery_status:
            query = query.filter(CustomerOrder.delivery_status == delivery_status)

        # Order by newest first
        query = query.order_by(CustomerOrder.order_date.desc())

        # Get total count
        total = query.count()

        # Apply pagination
        orders = query.offset(skip).limit(limit).all()

        return CustomerOrderListResponse(
            orders=orders,
            total=total,
            page=skip // limit + 1 if limit > 0 else 1,
            size=len(orders)
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching orders: {str(e)}"
        )


class SendInvoiceRequest(BaseModel):
    email: str


# SEND invoice via email
@order_router.post("/{order_id}/send-invoice")
async def send_invoice_email(
    order_id: uuid.UUID,
    payload: SendInvoiceRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    store = db.query(Store).filter(Store.id == order.store_id).first()
    store_name = store.store_name if store else "Shopivell"
    store_email = store.store_email if store else ""
    store_phone = store.store_phone if store else ""
    store_address_parts = []
    if store:
        for p in [store.store_address, store.store_city, store.store_country]:
            if p:
                store_address_parts.append(p)
    store_address = ", ".join(store_address_parts) or ""
    currency = getattr(store, 'currency', 'USD') or 'USD'

    qty = order.quantity or 1
    unit_price = order.total_amount / qty if qty else order.total_amount
    product = order.product_name or "Product"
    order_num = order.order_number or str(order.id)[:8]
    order_date = order.order_date.strftime("%B %d, %Y") if order.order_date else ""
    payment_method = (order.payment_method or "").replace("_", " ").title()

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;">
      <div style="background:#f8f9fa;padding:24px 32px;border-bottom:1px solid #e0e0e0;">
        <h2 style="margin:0;color:#333;">{store_name}</h2>
        <p style="margin:4px 0 0;color:#888;font-size:13px;">{store_address}</p>
        <p style="margin:2px 0 0;color:#888;font-size:13px;">{store_email}{'  |  ' + store_phone if store_phone else ''}</p>
      </div>
      <div style="padding:24px 32px;">
        <h1 style="font-size:22px;color:#333;margin:0 0 4px;">INVOICE</h1>
        <p style="color:#888;font-size:13px;margin:0;">Invoice #: {order_num} &nbsp;&bull;&nbsp; Date: {order_date}</p>
        <div style="margin:20px 0;padding:16px;background:#f8f9fa;border-radius:6px;">
          <p style="margin:0;font-size:12px;color:#888;text-transform:uppercase;">Bill To</p>
          <p style="margin:4px 0 0;font-size:15px;color:#333;font-weight:600;">{order.customer_name}</p>
          {'<p style="margin:2px 0 0;color:#666;font-size:13px;">' + order.phone + '</p>' if order.phone else ''}
        </div>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;">
          <thead>
            <tr style="background:#f0f0f0;">
              <th style="text-align:left;padding:10px;font-size:12px;color:#666;text-transform:uppercase;">Item</th>
              <th style="text-align:center;padding:10px;font-size:12px;color:#666;text-transform:uppercase;">Qty</th>
              <th style="text-align:right;padding:10px;font-size:12px;color:#666;text-transform:uppercase;">Price</th>
              <th style="text-align:right;padding:10px;font-size:12px;color:#666;text-transform:uppercase;">Total</th>
            </tr>
          </thead>
          <tbody>
            <tr style="border-bottom:1px solid #eee;">
              <td style="padding:12px 10px;font-size:14px;color:#333;">{product}</td>
              <td style="padding:12px 10px;text-align:center;font-size:14px;color:#333;">{qty}</td>
              <td style="padding:12px 10px;text-align:right;font-size:14px;color:#333;">${unit_price:.2f}</td>
              <td style="padding:12px 10px;text-align:right;font-size:14px;color:#333;">${order.total_amount:.2f}</td>
            </tr>
          </tbody>
        </table>
        <div style="text-align:right;margin:8px 0 16px;">
          <p style="margin:0;font-size:14px;color:#666;">Subtotal: <strong>${order.total_amount:.2f}</strong></p>
          <p style="margin:4px 0 0;font-size:18px;color:#333;font-weight:700;">Total: ${order.total_amount:.2f}</p>
        </div>
        <div style="border-top:1px solid #e0e0e0;padding-top:16px;display:flex;justify-content:space-between;align-items:center;">
          <p style="margin:0;font-size:13px;color:#666;">Payment: {payment_method}</p>
          <span style="background:#22c55e;color:white;padding:4px 14px;border-radius:4px;font-weight:700;font-size:13px;">PAID</span>
        </div>
      </div>
      <div style="background:#f8f9fa;padding:16px 32px;text-align:center;border-top:1px solid #e0e0e0;">
        <p style="margin:0;color:#888;font-size:13px;font-style:italic;">Thank you for your business!</p>
        <p style="margin:4px 0 0;color:#aaa;font-size:12px;">{store_name}</p>
      </div>
    </div>
    """

    try:
        from utils.Verification_Codes_Services import VerificationCodeService
        sent = VerificationCodeService.send_email(
            to_email=payload.email,
            subject=f"Invoice #{order_num} from {store_name}",
            body=html,
            content_type='html'
        )
        if not sent:
            raise HTTPException(status_code=500, detail="Failed to send email")
        return {"message": f"Invoice sent to {payload.email}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email error: {str(e)}")


# GET single order by ID
@order_router.get("/{order_id}", response_model=CustomerOrderResponse)
async def get_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    return order


# GET order by order number
@order_router.get("/number/{order_number}", response_model=CustomerOrderResponse)
async def get_order_by_number(
    order_number: str,
    store_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    order = db.query(CustomerOrder).filter(
        CustomerOrder.store_id == store_id,
        CustomerOrder.order_number == order_number
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    return order


# CREATE order
@order_router.post("/", response_model=CustomerOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: CustomerOrderCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    try:
        # Convert to dict
        order_dict = order_data.model_dump()

        # Extract delivery fields and append to customer_profile notes
        delivery_address = order_dict.pop('delivery_address', None)
        delivery_city = order_dict.pop('delivery_city', None)
        if delivery_address or delivery_city:
            notes_parts = []
            if order_dict.get('customer_profile'):
                notes_parts.append(order_dict['customer_profile'])
            if delivery_address:
                notes_parts.append(f"Address: {delivery_address}")
            if delivery_city:
                notes_parts.append(f"City: {delivery_city}")
            order_dict['customer_profile'] = "\n".join(notes_parts)

        # Generate order number if not provided
        if not order_dict.get('order_number'):
            order_dict['order_number'] = generate_order_number(db, order_data.store_id)
        else:
            # Check if order number already exists for this store
            existing = db.query(CustomerOrder).filter(
                CustomerOrder.store_id == order_data.store_id,
                CustomerOrder.order_number == order_data.order_number
            ).first()

            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Order number already exists for this store"
                )

        # Set default status if not provided
        if not order_dict.get('status'):
            order_dict['status'] = 'pending'

        if not order_dict.get('payment_status'):
            order_dict['payment_status'] = 'unpaid'

        if not order_dict.get('delivery_status'):
            order_dict['delivery_status'] = 'pending'

        # Create order
        db_order = CustomerOrder(**order_dict)
        db.add(db_order)
        db.commit()
        db.refresh(db_order)

        # Auto-create delivery if address was provided
        if delivery_address and db_order.delivery_status != "pickup":
            _auto_create_delivery(db, db_order, delivery_address, delivery_city)
            db.refresh(db_order)

        return db_order

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating order: {str(e)}"
        )


# UPDATE order
@order_router.put("/{order_id}", response_model=CustomerOrderResponse)
async def update_order(
    order_id: uuid.UUID,
    order_data: CustomerOrderUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    db_order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()

    if not db_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    # Update fields
    update_data = order_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_order, field, value)

    db.commit()
    db.refresh(db_order)

    return db_order


# UPDATE order status (quick status update)
@order_router.patch("/{order_id}/status", response_model=CustomerOrderResponse)
async def update_order_status(
    order_id: uuid.UUID,
    status_update: dict,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    db_order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()

    if not db_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    # Update status fields
    if 'status' in status_update:
        db_order.status = status_update['status']
    if 'payment_status' in status_update:
        db_order.payment_status = status_update['payment_status']
    if 'delivery_status' in status_update:
        db_order.delivery_status = status_update['delivery_status']
    if 'tracking_info' in status_update:
        db_order.tracking_info = status_update['tracking_info']

    db.commit()
    db.refresh(db_order)

    return db_order


# DELETE order
@order_router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    db_order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()

    if not db_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    db.delete(db_order)
    db.commit()

    return None


# ============ Public Endpoints (no auth) ============

@order_router.get("/public/list", response_model=CustomerOrderListResponse)
async def get_public_orders(
    store_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    """List orders for a store (public, no auth required)."""
    try:
        query = db.query(CustomerOrder).filter(CustomerOrder.store_id == store_id)
        if status_filter:
            query = query.filter(CustomerOrder.status == status_filter)
        total = query.count()
        orders = query.order_by(CustomerOrder.created_at.desc()).offset(skip).limit(limit).all()
        return {"orders": orders, "total": total, "page": skip // limit + 1, "size": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@order_router.get("/public/{order_id}", response_model=CustomerOrderResponse)
async def get_public_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Get a single order by ID (public, no auth required)."""
    order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@order_router.post("/public", response_model=CustomerOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_public_order(
    order_data: PublicOrderCreate,
    db: Session = Depends(get_db),
):
    """Create an order from the public order form (no auth required)."""
    try:
        # Build concatenated product name and total
        product_names = ", ".join(
            f"{item.product_name} x{item.quantity}" for item in order_data.items
        )
        items_total = sum(item.price * item.quantity for item in order_data.items)
        total_amount = items_total + order_data.delivery_fee - order_data.discount_amount

        order_number = generate_order_number(db, order_data.store_id)

        # Build notes from special request + delivery info
        notes_parts = []
        if order_data.delivery_method == "pickup":
            notes_parts.append("Delivery: Pickup")
        else:
            notes_parts.append("Delivery: Flat fee delivery")
            if order_data.delivery_address:
                notes_parts.append(f"Address: {order_data.delivery_address}")
            if order_data.delivery_city:
                notes_parts.append(f"City: {order_data.delivery_city}")
        if order_data.email:
            notes_parts.append(f"Email: {order_data.email}")
        if order_data.discount_code:
            notes_parts.append(f"Discount code: {order_data.discount_code} (-{order_data.discount_amount})")
        if order_data.special_request:
            notes_parts.append(f"Special request: {order_data.special_request}")

        db_order = CustomerOrder(
            store_id=order_data.store_id,
            order_number=order_number,
            customer_name=order_data.customer_name,
            phone=order_data.phone,
            product_name=product_names,
            quantity=sum(item.quantity for item in order_data.items),
            total_amount=total_amount,
            status="pending",
            payment_status="unpaid",
            delivery_status="pending" if order_data.delivery_method == "delivery" else "pickup",
            customer_profile="\n".join(notes_parts),
        )

        db.add(db_order)
        db.commit()
        db.refresh(db_order)

        # Auto-create delivery if delivery method is "delivery" and address provided
        if order_data.delivery_method == "delivery" and order_data.delivery_address:
            _auto_create_delivery(db, db_order, order_data.delivery_address, order_data.delivery_city)
            db.refresh(db_order)

        return db_order

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating order: {str(e)}"
        )
