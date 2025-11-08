# routers/requests.py
from datetime import datetime, timedelta, timezone
import os
from typing import List, Optional, Set
from uuid import UUID
import uuid

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status, Query
from openai import OpenAI
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
import boto3
from botocore.exceptions import NoCredentialsError
from database import get_db
from models import Product, RequestPost, User, Offer, Order # Import Offer and Order
from schemas.request_schema import RequestCreate, RequestOut, RequestResponse, RequestUpdate, SupplierRequestAction, MessageResponse # Import new schemas
from schemas.offer_schema import OfferCreate # For creating counter-offer
from schemas.orders_schema import OrderOut # Assuming you have this schema for order creation response
# Load environment variables

request_router = APIRouter(prefix="/requests", tags=["Requests"])

load_dotenv()

# Configuration from environment variables
SPACES_REGION = os.getenv("SPACES_REGION")
SPACES_ENDPOINT = os.getenv("SPACES_ENDPOINT")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# --- Validate Configuration (Optional but Recommended) ---
required_vars = ["SPACES_REGION", "SPACES_ENDPOINT", "ACCESS_KEY", "SECRET_KEY", "BUCKET_NAME"]
for var in required_vars:
    if os.getenv(var) is None:
        raise ValueError(f"Environment variable {var} not set. Please check your .env file.")

# Initialize S3 client globally. This should ideally be handled with FastAPI's dependency injection
# or application startup events for more robust error handling and resource management.
try:
    session = boto3.session.Session()
    s3_client = session.client(
        's3',
        region_name=SPACES_REGION,
        endpoint_url=SPACES_ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY
    )
except Exception as e:
    print(f"Error initializing S3 client: {e}")
    s3_client = None # Set to None if initialization fails, and handle this in functions


def upload_file_to_spaces(file_data: bytes, filename: str, content_type: str):
    """
    Uploads a file to DigitalOcean Spaces.

    Args:
        file_data (bytes): The content of the file to upload.
        filename (str): The desired filename in Spaces.
        content_type (str): The MIME type of the file (e.g., "image/jpeg").

    Returns:
        str: The public URL of the uploaded file, or None if an error occurs.
    """
    if s3_client is None:
        print("S3 client not initialized. Cannot upload file.")
        return None
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=filename,
            Body=file_data,
            ACL='public-read',  # Makes the file publicly accessible
            ContentType=content_type
        )
        # Construct the public URL for the uploaded file
        return f"{SPACES_ENDPOINT}/{BUCKET_NAME}/{filename}"
    
    except NoCredentialsError:
        print("Credentials not available. Check ACCESS_KEY and SECRET_KEY in .env.")
        return None
    except Exception as e:
        print(f"Error uploading file to Spaces: {e}")
        return None

def delete_file_from_spaces(filename: str):
    """
    Deletes a file from DigitalOcean Spaces.

    Args:
        filename (str): The filename (Key) of the file to delete in Spaces.

    Returns:
        bool: True if deletion was successful, False otherwise.
    """
    if s3_client is None:
        print("S3 client not initialized. Cannot delete file.")
        return False
    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=filename)
        return True
    except Exception as e:
        print(f"Error deleting file from Spaces: {e}")
        return False
    
# from auth import get_current_user # To get the authenticated user - COMMENTED OUT

OPENAI_APK_KEY = os.getenv("OPENAI_API_KEY")
openai_client =  OpenAI(api_key=OPENAI_APK_KEY)

def get_user(user_id: UUID, db: Session = Depends(get_db)):
    """
    TEMPORARY: Returns a real user from DB if ID is provided.
    Use this ONLY for development when skipping authentication.
    In a real app, this would be `get_current_user` from `auth.py`.
    """
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            return user
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User ID not found.")
    
# Dependency to check if user is a supplier (for making offers or accepting requests)

def require_supplier(user_id: UUID, db: Session = Depends(get_db)):
    user = get_user(user_id=user_id, db=db)
    if user.role != "supplier" and user.role != "both":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only suppliers can perform this action.")
    return user

# Dependency to check if user is the customer who created the request
def require_customer_of_request(request_id: UUID, db: Session = Depends(get_db)):
    # TEMPORARY: For request-specific actions, we might need a specific customer ID.
    # For now, this will return the mock customer.
    current_user = get_user(role="customer", db=db) 

    request_post = db.query(RequestPost).filter(RequestPost.id == request_id).first()
    if not request_post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    
    # You will need to ensure the customer_id in your request object matches the mock user's ID
    # OR you fetch a real user for this specific test case.
    if str(request_post.customer_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to perform this action on this request.")
    return request_post

@request_router.post("/", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_request(
    title: str = Form(...),
    category: str = Form(...),
    quantity: int = Form(...),
    description: str = Form(None),
    offer_price: float = Form(...),
    customer_id: str = Form(...),
    image: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    # Convert customer_id string to UUID
    try:
        customer_uuid = uuid.UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format for customer ID.")

    # Verify customer exists
    customer = db.query(User).filter(User.id == customer_uuid).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # # Check if image is valid
    # if not image.content_type or not image.content_type.startswith("image/"):
    
    image_url = None

    if image is not None:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"File '{image.filename}' is not a valid image.")

        contents = await image.read()
        image_uuid = uuid.uuid4()
        spaces_filename = f"requests/images/{image_uuid}"

        image_url = upload_file_to_spaces(contents, spaces_filename, image.content_type)


    # contents = await image.read()
    # image_uuid = uuid.uuid4()
    # spaces_filename = f"requests/images/{image_uuid}"

    # image_url = upload_file_to_spaces(contents, spaces_filename, image.content_type)
    # if image_url is None:
    #     raise HTTPException(status_code=500, detail=f"Failed to upload image '{image.filename}'.")

    db_request = RequestPost(
        title=title,
        category=category,
        description=description,
        quantity=quantity,
        offer_price=offer_price,
        customer_id=customer_uuid,
        image_path=image_url,
    )

    try:
        db.add(db_request)
        db.commit()
        db.refresh(db_request)
    except Exception as e:
        db.rollback()
        delete_file_from_spaces(spaces_filename)
        raise HTTPException(status_code=500, detail=f"Failed to create request: {e}")

    return MessageResponse(message="Request created successfully")

@request_router.get("/", response_model=List[RequestOut], status_code=status.HTTP_200_OK)
def list_request_posts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, gt=0, le=1000),
    customer_id: UUID = Query(..., description="Filter by customer ID"),
    db: Session = Depends(get_db),
):
    """
    Retrieve all requests for a specific customer where status is either 'open' or 'counter_offered'.
    """
    valid_statuses = ["open", "counter_offered"]

    query = (
        db.query(RequestPost)
        .filter(
            RequestPost.customer_id == customer_id,
            RequestPost.status.in_(valid_statuses)
        )
        .offset(skip)
        .limit(limit)
    )

    return query.all()


@request_router.get("/{request_id}", response_model=RequestOut, status_code=status.HTTP_200_OK)
def get_request_post(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user) # Using mock user
):
    """
    Retrieve a single request post by ID.
    Customers can only see their own requests. Suppliers can see open requests.
    """
    request_post = db.query(RequestPost).filter(RequestPost.id == request_id).first()
    if not request_post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")

    # Authorization check
    if current_user.role == "customer" and str(request_post.customer_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this request.")
    
    # Updated supplier check: Suppliers can view open requests OR requests they have an offer on
    if current_user.role == "supplier":
        has_offer = db.query(Offer).filter(
            Offer.request_id == request_id,
            Offer.supplier_id == current_user.id
        ).first()
        if request_post.status != "open" and not has_offer:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this request.")

    return request_post

@request_router.put("/{request_id}", response_model=RequestOut, status_code=status.HTTP_200_OK)
def update_request_post(
    request_id: UUID,
    request_update: RequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user) # Using mock user
):
    """
    Update an existing request post. Only the customer who created it can update,
    and only if the status is 'open'.
    """
    request_post = require_customer_of_request(request_id, db) # No need to pass current_user here, mock handles it
    
    if request_post.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot update request in '{request_post.status}' status. Only 'open' requests can be updated."
        )

    update_data = request_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(request_post, field, value)
    
    request_post.updated_at = datetime.now(timezone.utc)

    try:
        db.add(request_post)
        db.commit()
        db.refresh(request_post)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update request: {e}")
    
    return request_post

@request_router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_request_post(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_user) # Using mock user
):
    """
    Delete a request post. Only the customer who created it can delete,
    and only if the status is 'open'.
    """
    request_post = require_customer_of_request(request_id, db) # No need to pass current_user here, mock handles it

    if request_post.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete request in '{request_post.status}' status. Only 'open' requests can be deleted."
        )

    try:
        db.delete(request_post)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete request: {e}")
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- NEW ENDPOINTS FOR SUPPLIER INTERACTION WITH REQUESTS ---

@request_router.post("/{request_id}/supplier-action", response_model=MessageResponse, status_code=status.HTTP_200_OK)
def supplier_action_on_request(
    action_data: SupplierRequestAction,
    db: Session = Depends(get_db),
):
    """
    Allows a supplier to directly accept a customer's request (if offer_price exists)
    or make a counter-offer.
    """
    current_supplier = require_supplier(user_id=action_data.supplier_id, db=db)
    request_post = db.query(RequestPost).filter(RequestPost.id == action_data.request_id).first()

    if not request_post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    
    if request_post.status not in ["open", "counter_offered", "supplier_accepted", "supplier_rejected"]: # Allow actions on 'open' or 'counter_offered' or 'supplier_accepted' if a supplier needs to re-evaluate
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot act on request in '{request_post.status}' status. Only 'open', 'counter_offered', or 'supplier_accepted' or 'supplier_rejected' requests can be acted upon."
        )

    if str(action_data.supplier_id) != str(current_supplier.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only perform actions for your own supplier ID.")

    # Check if this supplier has already acted on this request (accepted or counter-offered)
    # This prevents multiple pending offers from the same supplier for the same request
    existing_pending_offer = db.query(Offer).filter(
        Offer.request_id == action_data.request_id,
        Offer.supplier_id == current_supplier.id,
        Offer.status == "pending"
    ).first()

    if existing_pending_offer and action_data.action == "counter_offer":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending counter-offer for this request. Please wait for the customer's response or cancel your existing offer."
        )
    # If a supplier has already accepted it, we should probably prevent another 'accept'
    if request_post.status == "supplier_accepted" and str(request_post.offers[0].supplier_id) == str(current_supplier.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already accepted this request. It's awaiting customer's order placement."
        )


    if action_data.action == "accept_request":
        if request_post.offer_price is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot 'accept_request' directly if the customer has not set an 'offer_price'."
            )
        
        # Supplier accepts the customer's proposed price, create an order directly
        try:
            # Create a "system" offer representing the direct acceptance
            direct_accept_offer = Offer(
                request_id=action_data.request_id,
                supplier_id=current_supplier.id,
                proposed_price=request_post.offer_price,
                message="Supplier accepted customer's requested price directly.",
                # Use current time + a reasonable default for delivery
                delivery_date=datetime.now(timezone.utc) + timedelta(days=7),
                status="accepted", # This offer is immediately accepted
                created_at=datetime.now(timezone.utc)
            )
            db.add(direct_accept_offer)
            db.flush() # Flush to get the offer_id before creating order

            new_order = Order(
                request_id=request_post.id,
                offer_id=direct_accept_offer.id, # Link to the system-generated offer
                customer_id=request_post.customer_id,
                supplier_id=current_supplier.id,
                total_price=request_post.offer_price,
                quantity=request_post.quantity,
                status="placed",
                created_at=datetime.now(timezone.utc)
            )
            db.add(new_order)

            request_post.status = "fulfilled" # Mark request as fulfilled
            request_post.updated_at = datetime.now(timezone.utc)

            # Reject any other existing pending offers for this request if any
            db.query(Offer).filter(
                Offer.request_id ==  action_data.request_id,
                Offer.status == "pending",
                Offer.id != direct_accept_offer.id # Exclude the one we just created
            ).update({"status": "rejected", "updated_at": datetime.now(timezone.utc)}, synchronize_session=False)

            db.commit()
            db.refresh(request_post)
            db.refresh(new_order) # Refresh to get ID and other generated fields
            db.refresh(direct_accept_offer)

            return MessageResponse(message=f"Request accepted directly. Order # {new_order.id} placed.")

        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to accept request directly and create order: {e}")

    elif action_data.action == "counter_offer":
        if action_data.proposed_price is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="For 'counter_offer', proposed_price, message, and delivery_date are required."
            )
        
        # Create a new offer as a counter-offer
        new_offer = Offer(
            request_id=action_data.request_id,
            supplier_id=current_supplier.id,
            proposed_price=action_data.proposed_price,
            status="pending", # Customer needs to accept this
            created_at=datetime.now(timezone.utc)
        )
        
        try:
            db.add(new_offer)
            request_post.status = "counter_offered" # Update request status
            request_post.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(new_offer)
            db.refresh(request_post)

            return MessageResponse(message=f"Counter-offer (Offer ID: {new_offer.id}) sent successfully. Customer needs to respond.")
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create counter-offer: {e}")
        
def matches_supplier_business(
    request_name: str,
    request_description: Optional[str],
    supplier_category: str,
    supplier_description: Optional[str]
) -> bool:
    """
    Uses OpenAI to determine if a customer's request matches a supplier's business category/description.
    Returns True if it's a match, False otherwise.
    """
    try:
        client = openai_client
    except NameError:
        print("OpenAI client not initialized.")
        return False

    if not client:
        print("OpenAI client is None.")
        return False

    user_message = (
        f"Customer Request Title: '{request_name}'\n"
        f"Customer Request Description: '{request_description or ''}'\n"
        f"Supplier Category: '{supplier_category}'\n"
        f"Supplier Description: '{supplier_description or ''}'\n"
        "Does this request match what the supplier offers? Reply only with 'Yes' or 'No'."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that determines if a customer's request is reasonably related to what the supplier offers. \
                        If there's a good chance the supplier can handle the request—even if it's not a perfect match—reply 'Yes'. Otherwise, reply 'No'. \
                        Only reply with 'Yes' or 'No'."

                    ),
                },
                {"role": "user", "content": user_message}
            ],
            max_tokens=10,
            temperature=0.2,
        )

        result = response.choices[0].message.content.strip().lower()
        return result == "yes"

    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        return False



@request_router.get("/matching_supplier_requests/{supplier_id}", response_model=List[RequestResponse])
def get_matching_supplier_requests(supplier_id: UUID, db: Session = Depends(get_db)):
    """
    Retrieves customer requests that match the supplier's business description and category.
    """
    supplier = db.query(User).filter(User.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")

    if supplier.role != "both":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a supplier.")

    if not supplier.business_category:
        return []

    open_requests = db.query(RequestPost).filter(RequestPost.status == "open").all()
    matched_requests = []

    for request in open_requests:
        if matches_supplier_business(
            request_name=request.title,
            request_description=request.description,
            supplier_category=supplier.business_category,
            supplier_description=supplier.business_description
        ):
            matched_requests.append(request)

    return matched_requests
