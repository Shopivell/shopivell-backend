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

order_router = APIRouter(prefix="/api/orders", tags=["orders"])


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
