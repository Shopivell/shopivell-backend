from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from database import get_db
from modules.orders.models import CustomerOrder
from modules.orders.schemas import CustomerOrderCreate, CustomerOrderListResponse, CustomerOrderResponse, CustomerOrderUpdate

order_router = APIRouter(prefix="/api/orders", tags=["orders"])

# GET all orders with pagination and filtering
@order_router.get("/", response_model=CustomerOrderListResponse)
async def get_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    customer_id: Optional[uuid.UUID] = None,
    payment_status: Optional[str] = None,
    delivery_status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        # Build query with filters
        query = db.query(CustomerOrder)
        
        if status:
            query = query.filter(CustomerOrder.status == status)
        if customer_id:
            query = query.filter(CustomerOrder.customer_id == customer_id)
        if payment_status:
            query = query.filter(CustomerOrder.payment_status == payment_status)
        if delivery_status:
            query = query.filter(CustomerOrder.delivery_status == delivery_status)
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        orders = query.offset(skip).limit(limit).all()
        
        return CustomerOrderListResponse(
            orders=orders,
            total=total,
            page=skip // limit + 1,
            size=len(orders)
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching orders: {str(e)}"
        )

# GET single order by ID
@order_router.get("/{order_id}", response_model=CustomerOrderResponse)
async def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
        
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
            
        return order
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching order: {str(e)}"
        )

# GET orders by order number
@order_router.get("/number/{order_number}", response_model=CustomerOrderResponse)
async def get_order_by_number(order_number: str, db: Session = Depends(get_db)):
    try:
        order = db.query(CustomerOrder).filter(CustomerOrder.order_number == order_number).first()
        
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
            
        return order
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching order: {str(e)}"
        )

@order_router.post("/", response_model=CustomerOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(order_data: CustomerOrderCreate, db: Session = Depends(get_db)):
    try:
        # Check if order number already exists
        existing_order = db.query(CustomerOrder).filter(
            CustomerOrder.order_number == order_data.order_number
        ).first()
        
        if existing_order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order number already exists"
            )
        
        # Debug: Print the data we're receiving
        print("Received order data:", order_data.model_dump())
        
        # Convert Pydantic model to dict and prepare for SQLAlchemy
        order_dict = order_data.model_dump()
        
        # Debug: Print CustomerOrder class attributes
        print("CustomerOrder attributes:", [attr for attr in dir(CustomerOrder) if not attr.startswith('_')])
        
        # Create new order - explicitly pass only valid fields
        valid_fields = {
            'customer_id', 'order_number', 'total_amount', 'status', 
            'customer_name', 'phone', 'offered_price', 'quantity',
            'customer_profile', 'profile_image', 'product_name', 
            'product_image', 'payment_status', 'delivery_status',
            'payment_method', 'transaction_id'
        }
        
        filtered_data = {k: v for k, v in order_dict.items() if k in valid_fields}
        print("Filtered data for creation:", filtered_data)
        
        db_order = CustomerOrder(**filtered_data)
        db.add(db_order)
        db.commit()
        db.refresh(db_order)
        
        return db_order
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        # More detailed error information
        import traceback
        error_details = traceback.format_exc()
        print(f"Detailed error: {error_details}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating order: {str(e)}"
        )

# UPDATE order
@order_router.put("/{order_id}", response_model=CustomerOrderResponse)
async def update_order(
    order_id: uuid.UUID, 
    order_data: CustomerOrderUpdate, 
    db: Session = Depends(get_db)
):
    try:
        # Get existing order
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
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating order: {str(e)}"
        )

# DELETE order
@order_router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        # Get existing order
        db_order = db.query(CustomerOrder).filter(CustomerOrder.id == order_id).first()
        
        if not db_order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        db.delete(db_order)
        db.commit()
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting order: {str(e)}"
        )