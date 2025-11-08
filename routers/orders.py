from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_ # Import or_ for correct OR conditions
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Path, status
from models import Offer, Order, RequestPost, User # Ensure all models are imported
from uuid import UUID
from schemas.offer_schema import MessageResponse
from schemas.orders_schema import DetailedOrderOut, OrderAction, OrderOut, OrderCreateFromOffer, OrderStatusAction # Import new schema
from fastapi.responses import JSONResponse
from datetime import datetime, timezone # For timezone-aware datetimes

# Create a new router for orders
orders_router = APIRouter(prefix="/orders", tags=["Orders"]) # Changed tag to plural

def generate_order_number(order_id: UUID) -> str:
    """Generate a short order number from the UUID"""
    return str(order_id).split('-')[0].upper()


# --- New Endpoint: Create an Order from an Accepted Offer (Customer Confirms) ---
@orders_router.post("/confirm-offer", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def confirm_offer_and_create_order(
    order_data: OrderCreateFromOffer,
    db: Session = Depends(get_db)
):
    """
    Allows a customer to confirm an offer, which creates a new order.
    The associated request's status will be updated to 'fulfilled'.
    Only "pending" offers can be accepted.
    """
    print("--- Starting confirm_offer_and_create_order endpoint ---")
    print(f"Received order_data: {order_data.model_dump()}") # Use model_dump() for Pydantic v2+

    # 1. Check Customer Retrieval
    customer = db.query(User).filter(User.id == order_data.customer_id).first()
    if not customer:
        print(f"Error: Customer with ID {order_data.customer_id} not found.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")
    print(f"Customer found: {customer.id} (Role: {customer.role})")

    # If you uncommented this for testing, keep it here
    # if customer.role != "customer":
    #     print(f"Error: User {customer.id} is not a customer.")
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only customers can confirm offers.")


    # 2. Check Offer Retrieval
    offer = db.query(Offer).filter(Offer.id == order_data.offer_id).first()
    if not offer:
        print(f"Error: Offer with ID {order_data.offer_id} not found.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found.")
    print(f"Offer found: {offer.id} (Status: {offer.status}, Request ID: {offer.request_id})")


    # 3. Check Request Retrieval and Customer Match
    request = db.query(RequestPost).filter(RequestPost.id == offer.request_id).first()
    if not request:
        print(f"Error: RequestPost with ID {offer.request_id} not found (linked to offer {offer.id}).")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated request not found.")

    if request.customer_id != customer.id:
        print(f"Error: Offer's request (ID: {request.id}) customer ID ({request.customer_id}) does not match current customer ID ({customer.id}).")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This offer is not for your request.")
    print(f"Request found and customer matches: {request.id}")

    # 4. Check Offer Status
    # if offer.status != "pending":
    #     print(f"Error: Offer status is '{offer.status}', cannot be confirmed.")
    #     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Offer status is '{offer.status}', cannot be confirmed.")
    # print(f"Offer status is 'pending'.")

    # 5. Check for Existing Order
    existing_order = db.query(Order).filter(Order.offer_id == offer.id).first()
    if existing_order:
        print(f"Error: An order already exists for this offer ({offer.id}). Existing order ID: {existing_order.id}")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An order already exists for this offer.")
    print("No existing order found for this offer. Proceeding to create.")

    # --- THIS IS WHERE YOUR ORIGINAL PRINTS ARE ---
    # If execution reaches here, these prints *will* show up in your console/logs.
    print("\n--- Values before Order creation ---")
    print(f"Request ID to use: {request.id}")
    print(f"Offer ID to use: {offer.id}")
    print(f"Customer ID to use: {customer.id}")
    print(f"Supplier ID to use: {offer.supplier_id}")
    print(f"Total Price to use: {offer.proposed_price}")
    print(f"Quantity to use: {request.quantity}")
    current_utc_time = datetime.now(timezone.utc)
    print(f"Created At timestamp: {current_utc_time}")
    print("------------------------------------\n")

    # Create the new order
    new_order = Order(
        request_id=request.id,
        offer_id=offer.id,
        customer_id=customer.id,
        supplier_id=offer.supplier_id,
        total_price=float(offer.proposed_price),
        quantity=request.quantity,
        status="placed",
        created_at=current_utc_time # Use the stored current_utc_time
    )
    print(f"New Order object created in memory with ID (if default generated): {new_order.id}")


    # Update offer status to 'accepted'
    offer.status = "accepted"
    offer.updated_at = datetime.now(timezone.utc)
    print(f"Offer {offer.id} status set to 'accepted'.")

    # Update the associated request status to 'fulfilled'
    request.status = "fulfilled"
    request.updated_at = datetime.now(timezone.utc)
    print(f"Request {request.id} status set to 'fulfilled'.")

    try:
        db.add(new_order)
        db.add(offer) # Add offer to session for update
        db.add(request) # Add request to session for update
        db.commit()
        db.refresh(new_order) # Refresh to get auto-generated fields like id if not provided
        db.refresh(offer)
        db.refresh(request)
        print(f"Successfully committed changes to DB. New Order ID: {new_order.id}")
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc() # This will print the full traceback to your console/logs
        print(f"Failed to create order or update related entities: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create order: {e}")

    print("--- Endpoint finished successfully ---")
    return new_order

# Get all placed/active orders for a user (customer or supplier)
@orders_router.get("/active/{user_id}", response_model=List[OrderOut]) # More specific path
def get_all_active_orders_for_user(user_id: UUID, db: Session = Depends(get_db)):
    """
    Retrieves all currently 'placed' (active) orders for a given user,
    whether they are the customer or the supplier.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    orders = (
        db.query(Order)
        .filter(
            or_(
                Order.customer_id == user_id,
                Order.supplier_id == user_id
            ),
            Order.status == "placed" # Filter for "placed" orders (active, not completed or cancelled)
        )
        .all()
    )
    return orders

# Get a single order by ID
@orders_router.get("/{order_id}", response_model=OrderOut)
def get_single_order(order_id: UUID, db: Session = Depends(get_db)):
    """
    Retrieves a single order by its ID.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return order

# Mark order as delivered or as cancelled
@orders_router.patch("/{order_id}/status", response_model=MessageResponse) # Return the updated order
def update_order_status(
    action: OrderStatusAction,
    db: Session = Depends(get_db)
):
    """
    Allows a customer to cancel an order or a supplier to mark an order as delivered.
    """
    order = db.query(Order).filter(Order.id == action.order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    
    user = db.query(User).filter(User.id == action.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Only allow status changes if the order is currently "placed"
    if order.status != "placed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Order status is '{order.status}', cannot be updated. Only 'placed' orders can be modified.")

    if user.role == "customer" or user.role == "both" and action.action == "cancel" and action.role == "customer":
        if order.customer_id != user.id: # Ensure the customer owns this order
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to cancel this order.")
        
        order.status = "cancelled"
        
    elif user.role == "both" and action.action == "deliver" and action.role == "supplier":
        if order.supplier_id != user.id: # Ensure the supplier owns this order
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to mark this order as delivered.")
        
        order.status = "delivered"
    else:
        # If the user role is incorrect for the action, or the action itself is invalid
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, # Changed to 400 because it's a bad request for this state
            detail=f"Invalid action '{action.action}' for user role '{user.role}' or current order status."
        )
    
    order.updated_at = datetime.now(timezone.utc) # Update timestamp
    try:
        db.commit()
        db.refresh(order)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update order status: {e}")

    # Return the updated order object
    return {"message": f"Order status updated to '{order.status}' successfully."}

# Get all completed (delivered or cancelled) orders for a user (history)
@orders_router.get("/history/{user_id}", response_model=List[OrderOut])
def get_user_order_history(user_id: UUID, db: Session = Depends(get_db)): # Renamed function for clarity
    """
    Retrieves all historical orders (delivered or cancelled) for a given user,
    whether they are the customer or the supplier.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    orders = (
        db.query(Order)
        .filter(
            or_(
                Order.customer_id == user_id,
                Order.supplier_id == user_id
            ),
            or_(
                Order.status == "delivered",
                Order.status == "cancelled"
            )
        )
        .all()
    )
    return orders

# Get all orders by a specific supplier (view from supplier's perspective)

@orders_router.get("/supplier-orders/{user_id}", response_model=List[DetailedOrderOut])
def get_orders_by_supplier(
    user_id: UUID = Path(..., description="The user ID to fetch supplier orders for"),
    db: Session = Depends(get_db)
):
    """
    Retrieves all orders where the specified user is the supplier.
    Returns: List of orders with order number, request description, price, date, image, and status.
    """
    # Verify user exists
    if not db.query(User).filter(User.id == user_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Query orders where user is the supplier
    orders = (
        db.query(Order)
        .filter(Order.supplier_id == user_id)
        .join(Order.request_post)
        .join(Order.offer)
        .all()
    )

    # Format the response
    response = []
    for order in orders:
        response.append({
            "order_id": order.id,
            "order_number": generate_order_number(order.id),
            "request_description": order.request_post.description,
            "agreed_price": order.total_price,
            "quantity": order.quantity,
            "date_ordered": order.created_at,
            "image_path": order.request_post.image_path,
            "status": order.status,
            "customer_name": f"{order.customer.name}",
            "customer_profile_pic_path": order.customer.personal_image_path,
            "customer_phone_number": order.customer.phone_number,
            "delivery_date": order.offer.delivery_date,
            "delivery_address": order.delivery_address
        })
    
    return response

@orders_router.get("/customer-orders/{user_id}", response_model=List[DetailedOrderOut])
def get_orders_by_customer(
    user_id: UUID = Path(..., description="The user ID to fetch customer orders for"),
    db: Session = Depends(get_db)
):
    """
    Retrieves all orders made by the specified user as customer.
    Returns: List of orders with order number, request description, price, date, image, status,
    customer name, supplier name, supplier phone number, supplier rating, supplier profile picture path,
    delivery date, and delivery address.
    """
    # Verify user exists
    if not db.query(User).filter(User.id == user_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Query orders where user is the customer
    orders = (
        db.query(Order)
        .filter(Order.customer_id == user_id)
        .join(Order.request_post)
        .join(Order.offer)
        .all()
    )

    # Format the response
    response = []
    for order in orders:
        response.append({
            "order_id": order.id,
            "order_number": generate_order_number(order.id),
            "request_description": order.request_post.description,
            "agreed_price": order.total_price,
            "quantity": order.quantity,
            "date_ordered": order.created_at,
            "image_path": order.request_post.image_path,
            "status": order.status,
            "customer_name": f"{order.customer.name}",
            "supplier_name": f"{order.supplier.name}",
            "supplier_phone_number": order.supplier.phone_number,
            "supplier_rating": getattr(order.supplier, "rating", None),  # Assuming rating field exists
            "supplier_profile_pic_path": order.supplier.personal_image_path,
            "delivery_date": order.offer.delivery_date,
            "delivery_address": order.delivery_address
        })
    return response


@orders_router.get("/delete-order/{user_id}", response_model=MessageResponse)
def delete_order_by(order_id: UUID, db: Session = Depends(get_db)):
    """
    Deletes an order by its ID.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    
    try:
        db.delete(order)
        db.commit()
        db.refresh(order)  # Refresh to ensure the order is fully deleted from the session
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete order: {e}")

    return {"message": "Order deleted successfully."}