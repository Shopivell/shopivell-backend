from typing import List
from datetime import datetime, timezone

from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, status

from models import Offer, Order, RequestPost, User
from schemas.offer_schema import DetailedOfferRead, OfferAction, OfferCreate, OfferDetailResponse, OfferUpdate, OfferCancel, MessageResponse, OfferRead # Import OfferOut instead of OfferRead, 
from schemas.orders_schema import OrderCreateFromOffer # For the confirm_offer_and_create_order logic
from schemas.user_schema import SuccessMessage # Assuming SuccessMessage is here
from uuid import UUID
from sqlalchemy.orm import joinedload

offer_router = APIRouter(prefix="/offers", tags=["Offers"]) # Changed tag to plural

# Helper function to get current UTC time
def get_utcnow():
    return datetime.now(timezone.utc)

# 1. POST /offers/ - Supplier creates an initial offer for a request
@offer_router.post("/", response_model=OfferRead, status_code=status.HTTP_201_CREATED)
def create_offer(offer_in: OfferCreate, db: Session = Depends(get_db)):
    """
    Allows a supplier to make an initial offer on an open customer request.
    """
    request = db.query(RequestPost).filter(RequestPost.id == offer_in.request_id).first()
    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")

    if request.status != "open":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Request status is '{request.status}', cannot accept new offers.")

    supplier = db.query(User).filter(User.id == offer_in.supplier_id).first()
    if not supplier or supplier.role != "supplier":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only suppliers can make offers or supplier not found.")

    # Optional: Check if the supplier actually deals with the request category
    supplier_product_categories = {p.category for p in supplier.products}
    if request.category not in supplier_product_categories:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Supplier does not deal in the category '{request.category}'.")

    # Check if this supplier already has a pending offer for this request
    existing_offer = db.query(Offer).filter(
        Offer.request_id == offer_in.request_id,
        Offer.supplier_id == offer_in.supplier_id,
        Offer.status == "pending" # Only block if a pending offer already exists
    ).first()
    if existing_offer:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Supplier has already submitted a pending offer for this request.")

    new_offer = Offer(
        request_id=offer_in.request_id,
        supplier_id=offer_in.supplier_id,
        proposed_price=offer_in.proposed_price,
        message=offer_in.message,
        delivery_date=offer_in.delivery_date,
        status="pending", # All new offers start as pending
        created_at=get_utcnow()
    )

    try:
        db.add(new_offer)
        db.commit()
        db.refresh(new_offer)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create offer: {e}")

    return new_offer

# 2. GET /offers/{offer_id} - Get a specific offer
@offer_router.get("/{offer_id}", response_model=OfferRead)
def get_offer(offer_id: UUID, db: Session = Depends(get_db)):
    """
    Retrieves a single offer by its ID.
    """
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found.")
    return offer


# 3. GET /offers/by-request/{request_id} - List all offers for a specific request
@offer_router.get("/by-request/{request_id}", response_model=List[OfferDetailResponse])
def get_offers_for_request(request_id: UUID, db: Session = Depends(get_db)):
    """
    Retrieves all PENDING offers associated with a specific customer request.
    Returns detailed offer information including supplier and request details.
    """
    # Check if request exists
    request = db.query(RequestPost).filter(RequestPost.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Get pending offers with supplier info
    offers = (
        db.query(Offer)
        .join(User, Offer.supplier_id == User.id)
        .filter(
            Offer.request_id == request_id,
            Offer.status == "pending"
        )
        .all()
    )
    
    # Format response
    return [
        {
            "id": offer.id,
            "supplier_name": f"{offer.supplier.name} {offer.supplier.surname or ''}",
            "supplier_business_name": offer.supplier.business_name or "",
            "proposed_price": offer.proposed_price,
            "message": offer.message,
            "delivery_date": offer.delivery_date,
            "status": offer.status,
            "created_at": offer.created_at,
            "updated_at": offer.updated_at,
            "request_title": request.title,
            "request_description": request.description,
            "request_initial_price": request.offer_price,
            "request_quantity": request.quantity,
            "request_category": request.category
        }
        for offer in offers
    ]

# 4. GET /offers/by-supplier/{supplier_id} - List all offers made by a specific supplier
@offer_router.get("/by-supplier/{supplier_id}", response_model=List[DetailedOfferRead])
def get_offers_by_supplier(supplier_id: UUID, db: Session = Depends(get_db)):
    """
    Retrieves all offers made by a specific supplier with detailed information about:
    - The offer itself
    - The requested product (name, description, initial price)
    - Supplier details (name, profile pic)
    - Customer details (name, profile pic)
    """
    # Check if supplier exists and is authorized
    supplier = db.query(User).filter(User.id == supplier_id).first()
    if not supplier or supplier.role not in ["supplier", "both"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Supplier not found or not authorized."
        )
    
    # Query offers with all necessary relationships
    offers = (
        db.query(Offer)
        .join(Offer.request_post)
        .join(RequestPost.customer)
        .filter(Offer.supplier_id == supplier_id,Offer.status != "accepted" )
        .options(
            joinedload(Offer.request_post),
            joinedload(Offer.supplier),
            joinedload(Offer.request_post).joinedload(RequestPost.customer)
        )
        .all()
    )
    
    # Convert to list of dictionaries with all required fields
    result = []
    for offer in offers:
        result.append({
            "id": offer.id,
            "proposed_price": offer.proposed_price,
            "message": offer.message,
            "delivery_date": offer.delivery_date,
            "status": offer.status,
            "created_at": offer.created_at,
            "updated_at": offer.updated_at,
            
            # Request details
            "request_title": offer.request_post.title,
            "request_description": offer.request_post.description,
            "request_category": offer.request_post.category,
            "request_initial_price": offer.request_post.offer_price,
            "request_quantity": offer.request_post.quantity,
            
            # Supplier details
            "supplier_name": f"{supplier.name} {supplier.surname or ''}".strip(),
            "supplier_business_name": supplier.business_name,
            "supplier_profile_pic": supplier.personal_image_path,
            
            # Customer details
            "customer_name": f"{offer.request_post.customer.name} {offer.request_post.customer.surname or ''}".strip(),
            "customer_profile_pic": offer.request_post.customer.personal_image_path
        })
    
    return result

# 5. PATCH /offers/{offer_id}/action - Customer responds to an offer (accept, reject, counter)
@offer_router.patch("/{offer_id}/action", response_model=OfferRead) # Returns the updated offer
def respond_to_offer(action_in: OfferAction, db: Session = Depends(get_db)):
    """
    Allows a customer to accept, reject, or counter an offer.
    Allows a supplier to cancel their own offer.
    """
    offer = db.query(Offer).filter(Offer.id == action_in.offer_id).first()
    if not offer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found.")

    request = db.query(RequestPost).filter(RequestPost.id == offer.request_id).first()
    if not request: # Should not happen if foreign keys are enforced, but good for safety
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated request not found.")

    acting_user = db.query(User).filter(User.id == request.customer_id).first()
    if not acting_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acting user not found.")

    # Customer actions
    if action_in.role == "customer":
        # if request.customer_id != acting_user.id:
        #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to respond to this offer.")

        if offer.status not in ["pending", "countered"]: # Only pending or countered offers can be responded to
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Offer status is '{offer.status}', cannot be responded to.")

        if action_in.action == "accept":
            # 1. Update the accepted offer's status
            offer.status = "accepted"
            offer.updated_at = get_utcnow()

            # 2. Set request status to 'fulfilled'
            request.status = "fulfilled"
            request.updated_at = get_utcnow()

            # 3. Reject all other pending/countered offers for this request
            other_offers = db.query(Offer).filter(
                Offer.request_id == offer.request_id,
                Offer.id != offer.id,
                or_(Offer.status == "pending", Offer.status == "countered")
            ).all()
            for other_offer in other_offers:
                other_offer.status = "rejected"
                other_offer.updated_at = get_utcnow()
                db.add(other_offer) # Add to session for update

            try:
                db.add(offer)
                db.add(request)
                db.commit()
                db.refresh(offer)

                # IMPORTANT: Create the Order in the orders_router using the confirmed offer
                # This should ideally be a separate internal function call or message queue
                # For direct integration, let's call the logic from orders_router.
                # Assuming you have access to `confirm_offer_and_create_order` function from orders_router
                # If not, you'd need to import it or duplicate its logic here (less ideal)
                from routers.orders import confirm_offer_and_create_order # Assuming this is the path
                
                # Create a dummy Pydantic object for the order_data
                order_creation_payload = OrderCreateFromOffer(
                    customer_id=acting_user.id,
                    offer_id=offer.id,
                    supplier_id=offer.supplier_id,
                )
                
                # Call the order creation logic
                confirm_offer_and_create_order(order_creation_payload, db)

                # Return the updated offer. The order confirmation is a side effect.
                return offer

            except HTTPException as he: # Catch HTTPExceptions from confirm_offer_and_create_order
                db.rollback() # Rollback everything if order creation fails
                raise he
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to accept offer and create order: {e}")

        elif action_in.action == "reject":
            offer.status = "rejected"
            offer.updated_at = get_utcnow()
            try:
                db.add(offer)
                db.commit()
                db.refresh(offer)
                return offer
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to reject offer: {e}")

        elif action_in.action == "counter":
            # This logic assumes 'counter' simply changes the status.
            # A full counter-offer system would involve creating a NEW Offer object
            # (possibly by the customer, or by the supplier in response to a prompt).
            # For now, we'll just mark the existing offer as 'countered'.
            offer.status = "countered"
            offer.updated_at = get_utcnow()
            try:
                db.add(offer)
                db.commit()
                db.refresh(offer)
                return offer
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to counter offer: {e}")

        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid action for customer.")

    # Supplier actions
    elif action_in.role == "supplier":
        if offer.supplier_id != acting_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to perform this action on this offer.")

        if offer.status != "pending":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Offer status is '{offer.status}', cannot be cancelled by supplier.")

        if action_in.action == "cancel_by_supplier":
            offer.status = "cancelled_by_supplier"
            offer.updated_at = get_utcnow()
            try:
                db.add(offer)
                db.commit()
                db.refresh(offer)
                return offer
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to cancel offer: {e}")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid action for supplier.")

    else: # e.g., admin or other roles not allowed
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User role not permitted to perform this action.")


# 6. PUT /offers/{offer_id} - Supplier updates an offer (if still pending)
@offer_router.put("/{offer_id}", response_model=OfferRead)
def update_offer(offer_id: UUID, offer_update: OfferUpdate, db: Session = Depends(get_db)):
    """
    Allows a supplier to update their own pending offer.
    """
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found.")

    # Authorization: Ensure the user attempting to update is the original supplier
    if offer.supplier_id != offer_update.supplier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to update this offer.")
    
    # Only allow updates if the offer is still pending
    if offer.status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Offer status is '{offer.status}', cannot be updated.")
    
    # Apply updates from the Pydantic model to the SQLAlchemy model
    for key, value in offer_update.model_dump(exclude_unset=True).items():
        if key != "supplier_id": # supplier_id is for auth, not part of mutable offer data
            setattr(offer, key, value)
    
    offer.updated_at = get_utcnow()

    try:
        db.add(offer)
        db.commit()
        db.refresh(offer)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update offer: {e}")

    return offer

# 7. DELETE /offers/{offer_id} - Supplier cancels their offer
# This is redundant with PATCH /action endpoint for 'cancel_by_supplier'.
# If you want a dedicated DELETE, you can simplify the PATCH.
# Given your PATCH endpoint now handles this, I'd recommend removing this for consistency.
# If you keep it, ensure it only allows deletion of 'pending' or 'countered' offers.

# @offer_router.delete("/{offer_id}", status_code=status.HTTP_204_NO_CONTENT)
# def delete_offer(offer_id: UUID, db: Session = Depends(get_db)):
#     """
#     Allows a supplier to delete their own pending offer.
#     """
#     offer = db.query(Offer).filter(Offer.id == offer_id).first()
#     if not offer:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found.")

#     # TODO: Add authentication/authorization check here to ensure only the supplier can delete their offer
#     # and only if it's still in a cancellable state (e.g., "pending").

#     # Example: Check if current user is the supplier who made the offer
#     # current_user = Depends(get_current_user) # Assuming you have this auth dependency
#     # if offer.supplier_id != current_user.id:
#     #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to delete this offer.")

#     if offer.status not in ["pending", "countered"]:
#         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Offer status is '{offer.status}', cannot be deleted.")

#     try:
#         db.delete(offer)
#         db.commit()
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete offer: {e}")
    
#     return Response(status_code=status.HTTP_204_NO_CONTENT)