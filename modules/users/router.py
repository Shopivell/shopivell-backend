import os
from typing import Optional
from datetime import datetime, timedelta, timezone # Import timedelta and timezone
import string
import secrets
import uuid

import boto3
from dotenv import load_dotenv
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import UUID
from config import settings
import jwt
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
import bcrypt
from dependencies import oauth2_scheme # Import OAuth2 scheme for token handling

# Import models
from database import get_db
from models import DeviceToken, User, VerificationCode # Make sure VerificationCode is imported
# Import schemas
from schemas.auth_schema import (
    AuthBase, AuthLogin, AuthResponse, LoginResponse,
    PasswordChange, PasswordResetRequest, UploadImageResponse,
    VerifyResetCodeRequest, ResetPasswordConfirm,
    MessageResponse # Use for general messages
)
from schemas.user_schema import ImagePathResponse, UserCreate


# --- Utility Functions (no change needed here) ---
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies if a given password matches the stored hash."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def hash_password(password: str) -> str:
    """Hashes a password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_password.decode('utf-8')

def create_verification_code(length: int = 6) -> str: # Changed name for clarity and default length
    """Generates a random numerical verification code (PIN)."""
    digits = string.digits
    return ''.join(secrets.choice(digits) for _ in range(length))

def authenticate_user(db: Session, email: str, password: str) -> User:
    """Authenticates a user by email and password."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, # Use status.HTTP for consistency
            detail="User with this email not found."
        )
    if not user.password_hash or not verify_password(password, user.password_hash): # Check if password_hash exists
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # Use 401 for authentication failure
            detail="Incorrect email or password."
        )
    return user

# --- FastAPI Router ---
auth_router = APIRouter(prefix="/auth", tags=["Auth"])

# --- Endpoint to set initial password for a new user ---
@auth_router.post("/set-password", response_model=AuthResponse, status_code=status.HTTP_200_OK)
def set_initial_password(auth: AuthBase, db: Session = Depends(get_db)):
    """
    Allows a newly registered user (or a user with no password set) to set their initial password.
    User's status is set to 'active' upon successful password creation.
    """
    user = db.query(User).filter(User.id == auth.user_id).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if user.password_hash:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password already set for this user. Use /change-password instead.")

    user.password_hash = hash_password(auth.password)
    user.status = "active" # Mark user as active after password is set
    user.updated_at = datetime.now(timezone.utc) # Update timestamp

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to set password: {e}")

    return AuthResponse(
        user_id=user.id,
        status=user.status,
        role=user.role
    )


# # --- Endpoint for User Login ---
# @auth_router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
# async def login(form_data: AuthLogin, db: Session = Depends(get_db)):
#     """
#     Authenticates a user and returns their login details.
#     """
#     user = authenticate_user(db, form_data.email, form_data.password)

#     if user.status == "disabled":
#         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your account is disabled. Please contact support.")
#     if user.status == "pending":
#         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your account is pending verification. Please complete verification.")

#     return LoginResponse(
#         user_id=user.id,
#         status=user.status,
#         role=user.role,
#         name=user.name,
#         profile_image=user.personal_image_path,
#         email=user.email,
#         business_name=user.business_name,
#         business_description=user.business_description,
#         business_profile_image=user.business_image_path
#     )

# --- Endpoint for User Login ---
@auth_router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def login(
    form_data: AuthLogin,
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    Authenticates a user and returns their login details with a non-expiring token.
    WARNING: Lifetime tokens pose security risks - ensure you have proper revocation mechanisms.
    """
    # Authenticate user
    user = authenticate_user(db, form_data.email, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    # Check account status
    if user.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is disabled. Please contact support."
        )
    elif user.status == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is pending verification. Please complete verification."
        )

    # Generate or retrieve device ID from request headers
    device_id = request.headers.get("X-Device-Id", str(uuid.uuid4()))

    # Build token payload (no expiration)
    token_payload = {
        "sub": str(user.id),
        "device_id": device_id,
        # No 'exp' included for lifetime token
    }
    token = jwt.encode(token_payload, settings.SECRET_KEY, algorithm="HS256")

    # Remove existing token for this user-device combo before saving new one
    db.query(DeviceToken).filter(
        DeviceToken.user_id == user.id,
        DeviceToken.device_id == device_id
    ).delete(synchronize_session=False)

    # Save new device token
    device_token = DeviceToken(
        user_id=user.id,
        device_id=device_id,
        token=token,
        issued_at=datetime.utcnow(),
        last_used=datetime.utcnow(),
        expires_at=None  # Explicitly no expiration
    )
    db.add(device_token)

    # Optionally update user last login timestamp
    user.last_login = datetime.utcnow()
    db.commit()

    return LoginResponse(
        user_id=user.id,
        status=user.status,
        role=user.role,
        name=user.name,
        profile_image=user.personal_image_path,
        email=user.email,
        business_name=user.business_name,
        business_description=user.business_description,
        business_profile_image=user.business_image_path,
        token=token,
        device_id=device_id,
        token_expires_at=None  # Indicate token never expires
    )

# 1. Request Password Reset (Generates and "sends" code)
@auth_router.post("/forgot-password", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def forgot_password_request(request: PasswordResetRequest, db: Session = Depends(get_db)):
    """
    Initiates the password reset process by generating a verification code
    and associating it with the user's email.
    """
    user = db.query(User).filter(User.email == request.email).first()
    
    if user: # Only generate/send if user exists to prevent email enumeration
        verification_code_value = create_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15) # Code valid for 15 minutes

        # Invalidate any previous unused reset codes for this user
        db.query(VerificationCode).filter(
            VerificationCode.user_id == user.id,
            VerificationCode.type == "password_reset",
            VerificationCode.is_used == False,
            VerificationCode.expires_at > datetime.now(timezone.utc)
        ).update({"is_used": True}, synchronize_session=False) # Mark as used without loading objects

        new_code = VerificationCode(
            user_id=user.id,
            code=verification_code_value,
            type="password_reset",
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc)
        )
        
        try:
            db.add(new_code)
            db.commit()
            # TODO: Integrate with an email/SMS sending service here
            print(f"DEBUG: Password reset code for {user.email}: {verification_code_value}")
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to generate reset code: {e}")
            
    # Always return a generic success message to prevent user enumeration
    return MessageResponse(message="If an account with that email exists, a password reset code has been sent.")

# 2. Verify Password Reset Code
@auth_router.post("/verify-reset-code", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def verify_reset_code(request: VerifyResetCodeRequest, db: Session = Depends(get_db)):
    """
    Verifies if the provided reset code is valid for the given email.
    """
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    verification_code = db.query(VerificationCode).filter(
        VerificationCode.user_id == user.id,
        VerificationCode.code == request.code,
        VerificationCode.type == "password_reset",
        VerificationCode.is_used == False,
        VerificationCode.expires_at > datetime.now(timezone.utc)
    ).first()

    if not verification_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid, expired, or used verification code.")
    
    # Code is valid but not used yet. We don't mark it as used here, only on successful password change.
    return MessageResponse(message="Verification code is valid. You can now reset your password.")

# 3. Reset Password (After code verification)
@auth_router.post("/reset-password", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def reset_password_confirm(data: ResetPasswordConfirm, db: Session = Depends(get_db)):
    """
    Allows a user to reset their password using a valid verification code.
    """
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    verification_code = db.query(VerificationCode).filter(
        VerificationCode.user_id == user.id,
        VerificationCode.code == data.code,
        VerificationCode.type == "password_reset",
        VerificationCode.is_used == False,
        VerificationCode.expires_at > datetime.now(timezone.utc)
    ).first()

    if not verification_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid, expired, or used verification code.")

    # Update password and mark code as used
    user.password_hash = hash_password(data.new_password)
    user.updated_at = datetime.now(timezone.utc)
    verification_code.is_used = True
    verification_code.updated_at = datetime.now(timezone.utc) # Assuming updated_at on VerificationCode model

    try:
        db.add(user)
        db.add(verification_code)
        db.commit()
        db.refresh(user)
        db.refresh(verification_code)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to reset password: {e}")

    return MessageResponse(message="Password has been successfully reset.")

# --- Endpoint for Logged-in User to Change Password ---
@auth_router.post("/change-password", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def change_password(data: PasswordChange, db: Session = Depends(get_db)):
    """
    Allows a logged-in user to change their password, requiring their old password for verification.
    """
    user = db.query(User).filter(User.id == data.user_id).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if not user.password_hash or not verify_password(data.old_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, # Changed to 401 for incorrect old password
            detail="Incorrect old password."
        )
    
    if verify_password(data.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as the old password."
        )

    user.password_hash = hash_password(data.new_password)
    user.updated_at = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to change password: {e}")

    return MessageResponse(message="Password changed successfully.")

bearer_scheme = HTTPBearer()

@auth_router.get("/verify-token")
async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        print("Decoded JWT payload:", payload)  # debug
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing sub")

        # Convert string to UUID
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid user ID in token")

        user = db.query(User).filter(User.id == user_uuid).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return {
            "valid": True,
            "user": {
                "id": str(user.id),
                "name": user.name,
                "email": user.email
            }
        }

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- Dependency to check admin role ---
# This dependency is applied to the router itself, meaning all endpoints
# within this router will automatically require an authenticated admin user.
def require_admin(current_user: User = Depends(get_current_user)):
    """
    Dependency that checks if the current authenticated user has 'admin' role.
    Raises HTTPException(403 Forbidden) if not an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required."
        )
    return current_user

# --- Router for admin-only operations ---
admin_router = APIRouter(
    prefix="/admin",
    tags=["Admin Operations"], # Capitalized tag for consistency
    dependencies=[Depends(require_admin)] # Apply the admin dependency to the entire router
)

@admin_router.get("/users", response_model=List[UserOut], status_code=status.HTTP_200_OK)
def list_users(
    skip: int = Query(0, ge=0, description="Number of items to skip"), # Added Query descriptions and validation
    limit: int = Query(100, gt=0, le=1000, description="Maximum number of items to return"),
    role: Optional[str] = Query(None, description="Filter users by role (e.g., 'customer', 'supplier', 'admin')"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter users by status (e.g., 'active', 'disabled', 'pending')"), # Renamed 'status' to 'status_filter' to avoid conflict with Python's built-in status
    db: Session = Depends(get_db)
):
    """
    Retrieves a list of users, with optional filtering by role and status.
    Requires admin privileges.
    """
    query = db.query(User)

    if role:
        # Validate role to be one of the allowed enum values from your User model
        # You might want to import the Enum directly from models or define allowed roles
        allowed_roles = ["customer", "supplier", "admin"] # Assuming these are your defined roles
        if role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role provided. Allowed roles are: {', '.join(allowed_roles)}.")
        query = query.filter(User.role == role)
    
    if status_filter: # Use the renamed variable
        # Validate status to be one of the allowed enum values from your User model
        allowed_statuses = ["active", "disabled", "pending"] # Assuming these are your defined statuses
        if status_filter not in allowed_statuses:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status provided. Allowed statuses are: {', '.join(allowed_statuses)}.")
        query = query.filter(User.status == status_filter)
        
    users = query.offset(skip).limit(limit).all()
    return users

@admin_router.get("/users/{user_id}", response_model=UserOut, status_code=status.HTTP_200_OK)
def get_user(
    user_id: UUID, # Use UUID type for path parameter
    db: Session = Depends(get_db)
):
    """
    Retrieves a single user's details by ID.
    Requires admin privileges.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user

@admin_router.patch("/users/{user_id}", response_model=UserOut, status_code=status.HTTP_200_OK)
def update_user(
    user_id: UUID, # Use UUID type for path parameter
    data: UserUpdate,
    db: Session = Depends(get_db)
):
    """
    Updates specific fields of a user's profile, such as status or role.
    Requires admin privileges.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    
    # Update only the fields that are provided in the request
    update_data = data.model_dump(exclude_unset=True) # Use model_dump for Pydantic V2
    for field, value in update_data.items():
        # Optional: Add validation for role and status changes if needed,
        # ensuring they are valid enum values from your User model.
        if field == "role":
            allowed_roles = ["customer", "supplier", "admin"]
            if value not in allowed_roles:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid role value: '{value}'. Allowed roles are: {', '.join(allowed_roles)}.")
        if field == "status":
            allowed_statuses = ["active", "disabled", "pending"]
            if value not in allowed_statuses:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status value: '{value}'. Allowed statuses are: {', '.join(allowed_statuses)}.")
        
        setattr(user, field, value)
    
    # Update the 'updated_at' timestamp if your User model has one
    if hasattr(user, 'updated_at'):
        user.updated_at = datetime.now(timezone.utc)

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update user: {e}")

    return user

@admin_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID, # Use UUID type for path parameter
    db: Session = Depends(get_db)
):
    """
    Deletes a user permanently from the database.
    Requires admin privileges.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    
    try:
        db.delete(user)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete user: {e}")
    
    return Response(status_code=status.HTTP_204_NO_CONTENT) # Return an empty response for 204

@admin_router.get("/stats/users", response_model=StatsResponse, status_code=status.HTTP_200_OK)
def user_stats(
    period_days: int = Query(30, gt=0, description="Number of days back from the current date to calculate statistics."),
    db: Session = Depends(get_db)
) -> StatsResponse:
    """
    Returns user statistics including total, active, disabled, and new users
    within a specified period. Requires admin privileges.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=period_days)

    total = db.query(func.count(User.id)).scalar()
    active = db.query(func.count(User.id)).filter(User.status == 'active').scalar()
    disabled = db.query(func.count(User.id)).filter(User.status == 'disabled').scalar()
    pending = db.query(func.count(User.id)).filter(User.status == 'pending').scalar() # Added pending users stat
    new_users = db.query(func.count(User.id)).filter(User.created_at >= since).scalar()

    return StatsResponse(
        total_users=total,
        active_users=active,
        disabled_users=disabled,
        pending_users=pending, # Include in response
        new_users=new_users,
        period_days=period_days
    )


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



# Helper to check if a user is a store (can be used as a dependency later for auth)
def is_supplier(user: User):
    if user.role != "store" and user.role != "admin": # Admins can also manage store profiles
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied. User is not a store.")
    return True

store_router = APIRouter(prefix="/stores", tags=["stores"]) # Changed prefix to plural

@store_router.post("/register-business/{user_id}", response_model=StoreResponse, status_code=status.HTTP_201_CREATED)
def register_business_profile(user_id: UUID, business_data: StoreCreate, db: Session = Depends(get_db)):
    """
    Registers or updates a user's profile to be a store.
    This is typically for an existing user (customer) who wants to become a store.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Prevent re-registration if already a store with filled business info
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

    # Set the user's role to 'store' and status to 'pending' or 'active' based on your flow
    user.role = "both"  # Assuming you want to allow both customer and store roles
    # user.status = "pending" # Or "active" if no further verification is needed for stores
    # Set business_created_at if it's the first time
    db.commit()
    db.refresh(user)

    # Return the full store response
    return StoreResponse(
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


@store_router.put("/{user_id}/profile", response_model=StoreResponse)
def update_supplier_profile(user_id: UUID, business_data: StoreUpdate, db: Session = Depends(get_db)): # Add current_user: User = Depends(get_current_active_user)
    """
    Updates an existing store's business profile information.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Optional: Authorization check - ensure current_user can modify this profile
    # if current_user.id != user_id and current_user.role != "admin":
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this profile.")
    
    # Ensure the user has the 'store' role before updating business info
    if user.role != "store" and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only stores can update business profiles.")

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

    # Return the full updated store response
    return StoreResponse(
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


@store_router.delete("/{user_id}/profile", response_model=SuccessMessage)
def delete_supplier_profile(user_id: UUID, db: Session = Depends(get_db)): # Add current_user: User = Depends(get_current_active_user)
    """
    Deletes a store's business profile information.
    This will clear all business-related fields and optionally revert the user's role to 'customer'.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Optional: Authorization check
    # if current_user.id != user_id and current_user.role != "admin":
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this profile.")

    # Ensure the user actually has a 'store' role before attempting to delete their business profile
    if user.role != "store":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is not registered as a store.")

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

@store_router.post("/{user_id}/upload-business-image", response_model=SuccessMessage)
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
    if user.role not in ["store", "admin"]: # Only allow stores or admins to upload business images
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only stores can upload business images.")

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

@store_router.get("/{user_id}/profile", response_model=StoreResponse)
def get_supplier_profile(user_id: UUID, db: Session = Depends(get_db)):
    """
    Retrieves business profile information for a user.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Ensure the user has a store role to expose their business profile
    if user.role != "both":
        # You might choose to return a 404 or a message indicating not a store
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User is not a store or business profile not found.")

    # Return the full store response
    return StoreResponse(
        user_id=user.id,
        name=user.name,
        surname=user.surname,
        email=user.email,
        phone_number=user.phone_number,
        personal_image_path=user.personal_image_path,
        role=user.role,
        status=user.status,
        created_at=user.created_at, # This could be None if not a store
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

@store_router.get("/", response_model=List[StoreResponse])
def get_all_stores(db: Session = Depends(get_db)):
    """
    Retrieves a list of all users who have the 'store' role.
    """
    stores = db.query(User).filter(User.role == "store").all()
    # Pydantic will iterate through the list and convert each SQLAlchemy User object
    # into a StoreResponse.
    return [
        StoreResponse(
            user_id=store.id,
            name=store.name,
            surname=store.surname,
            email=store.email,
            phone_number=store.phone_number,
            personal_image_path=store.personal_image_path,
            role=store.role,
            status=store.status,
            created_at=store.created_at,
            business_name=store.business_name,
            business_category=store.business_category,
            business_description=store.business_description,
            business_type=store.business_type,
            business_email=store.business_email,
            business_phone_number=store.business_phone_number,
            latitude=store.latitude,
            longitude=store.longitude,
            business_image_path=store.business_image_path
        ) for store in stores
    ]