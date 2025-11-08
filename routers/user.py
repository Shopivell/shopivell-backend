from io import BytesIO
import uuid
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse, StreamingResponse
from database import get_db
from models import User # Ensure your SQLAlchemy User model is imported correctly
from schemas.auth_schema import AuthResponse, UploadImageResponse
from schemas.user_schema import ImagePathResponse, SuccessMessage, UserBase, UserCreate, UserResponse, UserUpdate # Import updated schemas
from uuid import UUID
from typing import List, Optional
import os
from dotenv import load_dotenv
import boto3
from botocore.exceptions import NoCredentialsError

user_router = APIRouter(prefix="/users", tags=["Users"])
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
        # It's better to raise an exception at startup than to have silent failures later
        raise ValueError(f"Environment variable {var} not set. Please check your .env file.")

# Initialize S3 client (DigitalOcean Spaces is S3-compatible)
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
    # In a real application, you might want to log this error and potentially exit if S3 is critical

# --- Helper Functions ---
def upload_file_to_spaces(file_data: bytes, filename: str, content_type: str):
    """Uploads a file to DigitalOcean Spaces and returns its public URL."""
    if s3_client is None:
        raise HTTPException(status_code=500, detail="S3 client not initialized. Cannot upload file.")
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=filename,
            Body=file_data,
            ACL='public-read',  # Makes the file publicly accessible
            ContentType=content_type
        )
        return f"{SPACES_ENDPOINT}/{BUCKET_NAME}/{filename}"
    except NoCredentialsError:
        raise HTTPException(status_code=500, detail="Credentials not available for S3. Check ACCESS_KEY and SECRET_KEY.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading file to Spaces: {e}")

def create_username(name: str, surname: str) -> str:
    """Generates a username from first name and surname."""
    return f"{name.lower()}.{surname.lower()}"

@user_router.post("/{user_id}/upload-personal-image", response_model=UploadImageResponse)
async def upload_personal_image(
    user_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Uploads a personal profile image for a user and updates the user's personal_image_path.
    This also handles editing (overwriting) the existing image.
    """
    print(f"User ID: {user_id}")
    print(f"Filename: {file.filename}")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    contents = await file.read()
    file_extension = file.filename.split(".")[-1] if "." in file.filename else "png"
    # Create a unique filename for the image, tied to the user ID for easy management
    spaces_filename = f"users/{user_id}/personal_image_{uuid.uuid4()}.{file_extension}"

    image_url_from_spaces = upload_file_to_spaces(contents, spaces_filename, file.content_type)

    user.personal_image_path = image_url_from_spaces

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update user's personal image path in database: {e}")

    return UploadImageResponse(
            image_path=image_url_from_spaces
        )

@user_router.get("/{user_id}/personal-image", response_model=ImagePathResponse)
def get_personal_image_path(
    user_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Retrieves the personal image path (URL) for the given user.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if not user.personal_image_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Personal image not found.")

    return ImagePathResponse(image_path=user.personal_image_path)



@user_router.post("/", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    Creates a new user. Checks for existing email and phone number.
    By default, new users are assigned the 'customer' role and 'pending' status.
    """
    if db.query(User).filter(User.email == user_in.email).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    if user_in.phone_number and db.query(User).filter(User.phone_number == user_in.phone_number).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone number already registered")

    username = create_username(user_in.name, user_in.surname)

    new_user = User(
        username=username,
        email=user_in.email,
        date_of_birth=user_in.date_of_birth,
        name=user_in.name,
        gender=user_in.gender,
        surname=user_in.surname,
        status="pending",
        phone_number=user_in.phone_number,
        role=user_in.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    if not new_user.id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user in database")
    
    return AuthResponse(
        user_id=new_user.id,
        status=new_user.status,
        role=new_user.role
    )


@user_router.get("/", response_model=List[UserResponse])
def get_all_users(db: Session = Depends(get_db)):
    """
    Retrieves all users from the database.
    Returns detailed user information, including optional fields like username, location, and timestamps.
    """
    users = db.query(User).all()
    return users

@user_router.delete("/{user_id}", response_model=SuccessMessage, status_code=status.HTTP_200_OK)
def delete_user(user_id: UUID, db: Session = Depends(get_db)):
    """
    Deletes a user by their ID.
    If the user does not exist, returns 404.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    try:
        db.delete(user)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user: {e}"
        )

    return SuccessMessage(message=f"User {user_id} deleted successfully")

