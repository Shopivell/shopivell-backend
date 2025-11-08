import uuid
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from database import get_db
from models import User # Ensure your SQLAlchemy User model is imported
# Use the Pydantic schemas you just defined for input/output
from schemas.supplier_schema import SupplierResponse, SupplierUpdate, SupplierCreate # Import the new schemas
from schemas.user_schema import SuccessMessage # Assuming SuccessMessage is in user_schema
from uuid import UUID
from typing import Optional, List
import os
from dotenv import load_dotenv
import boto3
from botocore.exceptions import NoCredentialsError
from datetime import datetime, timezone

supplier_router = APIRouter(prefix="/suppliers", tags=["Suppliers"]) # Changed prefix to plural
# Load environment variables
load_dotenv()

# Configuration from environment variables
SPACES_REGION = os.getenv("SPACES_REGION")
SPACES_ENDPOINT = os.getenv("SPACES_ENDPOINT")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# --- Validate Configuration ---
required_vars = ["SPACES_REGION", "SPACES_ENDPOINT", "ACCESS_KEY", "SECRET_KEY", "BUCKET_NAME"]
for var in required_vars:
    if os.getenv(var) is None:
        raise ValueError(f"Environment variable {var} not set. Please check your .env file.")

# Initialize S3 client
s3_client = None
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
    # In a production app, you might raise an error or exit if S3 is critical.
    # For now, we'll handle `s3_client is None` in functions.


def upload_file_to_spaces(file_data: bytes, filename: str, content_type: str) -> Optional[str]:
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="S3 client not initialized. Cannot upload file.")
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Credentials not available for S3. Check ACCESS_KEY and SECRET_KEY.")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error uploading file to Spaces: {e}")



# Helper to check if a user is a supplier (can be used as a dependency later for auth)
def is_supplier(user: User):
    if user.role != "supplier" and user.role != "admin": # Admins can also manage supplier profiles
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied. User is not a supplier.")
    return True


@supplier_router.post("/register-business/{user_id}", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
def register_business_profile(user_id: UUID, business_data: SupplierCreate, db: Session = Depends(get_db)):
    """
    Registers or updates a user's profile to be a supplier.
    This is typically for an existing user (customer) who wants to become a supplier.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Prevent re-registration if already a supplier with filled business info
    if user.role == "both" and user.business_name:
        # You might want to allow this as an update operation instead of creating a new one
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business profile already registered for this user. Use PUT to update.")

    # Check for unique business email and phone number if provided
    if business_data.business_email and db.query(User).filter(User.business_email == business_data.business_email, User.id != user_id).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business email already in use by another account.")

    if business_data.business_phone_number and db.query(User).filter(User.business_phone_number == business_data.business_phone_number, User.id != user_id).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business phone number already in use by another account.")

    # Update user fields from business_data
    for field, value in business_data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    # Set the user's role to 'supplier' and status to 'pending' or 'active' based on your flow
    user.role = "both"  # Assuming you want to allow both customer and supplier roles
    # user.status = "pending" # Or "active" if no further verification is needed for suppliers
    # Set business_created_at if it's the first time
    db.commit()
    db.refresh(user)

    # Return the full supplier response
    return SupplierResponse(
        user_id=user.id,
        name=user.name,
        surname=user.surname,
        email=user.email,
        phone_number=user.phone_number,
        personal_image_path=user.personal_image_path,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        # Directly map business fields
        business_name=user.business_name,
        business_category=user.business_category,
        business_description=user.business_description,
        business_type=user.business_type,
        business_email=user.business_email,
        business_phone_number=user.business_phone_number,
        latitude=user.latitude,
        longitude=user.longitude,
        business_image_path=user.business_image_path
    )


@supplier_router.put("/{user_id}/profile", response_model=SupplierResponse)
def update_supplier_profile(user_id: UUID, business_data: SupplierUpdate, db: Session = Depends(get_db)): # Add current_user: User = Depends(get_current_active_user)
    """
    Updates an existing supplier's business profile information.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Optional: Authorization check - ensure current_user can modify this profile
    # if current_user.id != user_id and current_user.role != "admin":
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this profile.")
    
    # Ensure the user has the 'supplier' role before updating business info
    if user.role != "supplier" and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only suppliers can update business profiles.")

    # Check for unique business email and phone number if they are being updated
    if business_data.business_email is not None and user.business_email != business_data.business_email:
        if db.query(User).filter(User.business_email == business_data.business_email, User.id != user_id).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business email already in use by another account.")

    if business_data.business_phone_number is not None and user.business_phone_number != business_data.business_phone_number:
        if db.query(User).filter(User.business_phone_number == business_data.business_phone_number, User.id != user_id).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Business phone number already in use by another account.")

    # Apply updates from the Pydantic model to the SQLAlchemy model
    for field, value in business_data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)

    # Return the full updated supplier response
    return SupplierResponse(
        user_id=user.id,
        name=user.name,
        surname=user.surname,
        email=user.email,
        phone_number=user.phone_number,
        personal_image_path=user.personal_image_path,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        business_created_at=user.business_created_at,
        business_name=user.business_name,
        business_category=user.business_category,
        business_description=user.business_description,
        business_type=user.business_type,
        business_email=user.business_email,
        business_phone_number=user.business_phone_number,
        latitude=user.latitude,
        longitude=user.longitude,
        business_image_path=user.business_image_path
    )


@supplier_router.delete("/{user_id}/profile", response_model=SuccessMessage)
def delete_supplier_profile(user_id: UUID, db: Session = Depends(get_db)): # Add current_user: User = Depends(get_current_active_user)
    """
    Deletes a supplier's business profile information.
    This will clear all business-related fields and optionally revert the user's role to 'customer'.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Optional: Authorization check
    # if current_user.id != user_id and current_user.role != "admin":
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this profile.")

    # Ensure the user actually has a 'supplier' role before attempting to delete their business profile
    if user.role != "supplier":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not registered as a supplier.")

    # Clear business fields
    user.business_name = None
    user.business_category = None
    user.business_description = None
    user.business_type = None
    user.business_email = None
    user.business_phone_number = None
    user.latitude = None
    user.longitude = None
    user.business_image_path = None # Clear the stored image URL
    user.business_created_at = None # Optionally clear this as well

    # Revert role back to customer
    user.role = "customer"

    db.commit()
    return {"message": "Business profile deleted successfully. User role reverted to customer."}

@supplier_router.post("/{user_id}/upload-business-image", response_model=SuccessMessage)
async def upload_business_image(
    user_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db) # Add current_user: User = Depends(get_current_active_user)
):
    """
    Uploads or updates the business profile image for a user.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    
    # Optional: Authorization check and role check
    # if current_user.id != user_id and current_user.role != "admin":
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to upload image for this user.")
    if user.role not in ["supplier", "admin"]: # Only allow suppliers or admins to upload business images
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only suppliers can upload business images.")

    contents = await file.read()
    file_extension = file.filename.split(".")[-1] if "." in file.filename else "png"
    # Ensure unique filename, and structure in Spaces: users/<user_id>/business_image_<uuid>.<ext>
    spaces_filename = f"users/{user_id}/business_image_{uuid.uuid4()}.{file_extension}" 

    image_url_from_spaces = upload_file_to_spaces(contents, spaces_filename, file.content_type)

    user.business_image_path = image_url_from_spaces
    
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update business image path in database: {e}")

    return {"message": "Business profile image uploaded successfully", "image_url": image_url_from_spaces}


@supplier_router.get("/{user_id}/profile", response_model=SupplierResponse)
def get_supplier_profile(user_id: UUID, db: Session = Depends(get_db)):
    """
    Retrieves business profile information for a user.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Ensure the user has a supplier role to expose their business profile
    if user.role != "both":
        # You might choose to return a 404 or a message indicating not a supplier
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User is not a supplier or business profile not found.")

    # Return the full supplier response
    return SupplierResponse(
        user_id=user.id,
        name=user.name,
        surname=user.surname,
        email=user.email,
        phone_number=user.phone_number,
        personal_image_path=user.personal_image_path,
        role=user.role,
        status=user.status,
        created_at=user.created_at, # This could be None if not a supplier
        business_name=user.business_name,
        business_category=user.business_category,
        business_description=user.business_description,
        business_type=user.business_type,
        business_email=user.business_email,
        business_phone_number=user.business_phone_number,
        latitude=user.latitude,
        longitude=user.longitude,
        business_image_path=user.business_image_path
    )

@supplier_router.get("/", response_model=List[SupplierResponse])
def get_all_suppliers(db: Session = Depends(get_db)):
    """
    Retrieves a list of all users who have the 'supplier' role.
    """
    suppliers = db.query(User).filter(User.role == "supplier").all()
    # Pydantic will iterate through the list and convert each SQLAlchemy User object
    # into a SupplierResponse.
    return [
        SupplierResponse(
            user_id=supplier.id,
            name=supplier.name,
            surname=supplier.surname,
            email=supplier.email,
            phone_number=supplier.phone_number,
            personal_image_path=supplier.personal_image_path,
            role=supplier.role,
            status=supplier.status,
            created_at=supplier.created_at,
            business_name=supplier.business_name,
            business_category=supplier.business_category,
            business_description=supplier.business_description,
            business_type=supplier.business_type,
            business_email=supplier.business_email,
            business_phone_number=supplier.business_phone_number,
            latitude=supplier.latitude,
            longitude=supplier.longitude,
            business_image_path=supplier.business_image_path
        ) for supplier in suppliers
    ]