# schemas/auth_schema.py
from datetime import date, datetime
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from uuid import UUID

# Existing schemas (ensure these match your current ones)
class AuthBase(BaseModel):
    user_id: UUID
    password: str = Field(..., min_length=8, max_length=128) # Added min/max length for password

class AuthLogin(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    user_id: UUID
    status: str
    role: str

class LoginResponse(BaseModel):
    user_id: UUID
    status: str
    role: str
    name: Optional[str] = None
    profile_image: Optional[str] = None
    email: str
    business_name: Optional[str] = None
    business_description: Optional[str] = None
    business_profile_image: Optional[str] = None
    token: Optional[str] = None
    device_id: Optional[str] = None
    token_expires_at: Optional[str] = None

class PasswordChange(BaseModel):
    user_id: UUID # User ID for the logged-in user changing their password
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=128)

class PasswordResetRequest(BaseModel):
    email: str

# --- NEW SCHEMAS FOR VERIFICATION CODE BASED RESET ---

class VerifyResetCodeRequest(BaseModel):
    email: str
    code: str = Field(..., min_length=6, max_length=6) # Assuming 6-digit code

class ResetPasswordConfirm(BaseModel):
    email: str
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8, max_length=128)

class UploadImageResponse(BaseModel):
    image_path: str

class MessageResponse(BaseModel):
    message: str

class StoreBase(BaseModel):
    # These are fields directly from the User model that pertain to a Store's business profile
    business_name: Optional[str] = None
    business_category: Optional[str] = None
    business_description: Optional[str] = None
    business_type: Optional[str] = None
    business_email: Optional[EmailStr] = None
    business_phone_number: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Assuming the image_path is directly stored as a URL
    business_image_path: Optional[str] = None # Direct URL to the business image

class StoreCreate(BaseModel):
    business_name: Optional[str] = None
    business_category: Optional[str] = None
    business_description: Optional[str] = None
    business_type: Optional[str] = None
    business_email: Optional[EmailStr] = None
    business_phone_number: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class StoreUpdate(StoreBase):
    # All fields are optional as it's for partial updates
    pass

class StoreResponse(StoreBase):
    # This is what you return when you get a Store's full profile
    user_id: UUID # The ID of the user who is the Store
    # Add other relevant user fields if needed in the response, e.g., personal name, etc.
    name: str
    surname: str
    email: EmailStr
    phone_number: Optional[str] = None
    personal_image_path: Optional[str] = None
    role: str
    status: str
    created_at: datetime

    class Config:
        orm_mode = True
        from_attributes = True # For Pydantic v2+

class MessageResponse(BaseModel):
    message: str

# --- Base Schema for User Information ---
# This will include all fields that are commonly shared across read/update operations.
class UserBase(BaseModel):
    email: EmailStr
    date_of_birth: Optional[date] = None
    name: str
    gender: Optional[str] = None
    surname: str
    phone_number: Optional[str] = None
    # Add business-related fields here as they are part of the user's full info
    business_phone_number: Optional[str] = None
    business_email: Optional[EmailStr] = None
    business_name: Optional[str] = None
    business_category: Optional[str] = None
    business_description: Optional[str] = None
    business_type: Optional[str] = None
    personal_image_path: Optional[str] = None # Direct URL to personal image
    business_image_path: Optional[str] = None # Direct URL to business image

# -
class UserResponse(BaseModel):
    id: UUID
    username: Optional[str] = None
    role: str
    status: str
    created_at: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    business_created_at: Optional[datetime] = None  # <-- make it optional

    class Config:
        orm_mode = True
# --- Schema for User Creation (Input) ---
# This should only include fields necessary for initial creation.
class UserCreate(BaseModel):
    email: EmailStr
    # password: str # You'll likely need a password field for user creation
    name: str
    surname: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    phone_number: Optional[str] = None
    # Role might be specified during creation, or default to 'customer'
    role: Optional[str] = "customer" # Default to customer, can be changed later or via admin, or both => customer and business

# --- Schema for User Updates (Input) ---
# This allows for partial updates.
class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    date_of_birth: Optional[date] = None
    name: Optional[str] = None
    gender: Optional[str] = None
    surname: Optional[str] = None
    phone_number: Optional[str] = None
    # Include business fields for updates
    business_phone_number: Optional[str] = None
    business_email: Optional[EmailStr] = None
    business_name: Optional[str] = None
    business_category: Optional[str] = None
    business_description: Optional[str] = None
    business_type: Optional[str] = None
    personal_image_path: Optional[str] = None
    business_image_path: Optional[str] = None
    status: Optional[str] = None # Allow updating status (e.g., admin changing to active)
    role: Optional[str] = None # Allow updating role (e.g., admin changing to Store)

class AuthResponse(BaseModel):
    user_id: UUID
    status: str
    role: str

class ImagePathResponse(BaseModel):
    image_path: str

# --- Success Message Schema ---
class SuccessMessage(BaseModel):
    message: str