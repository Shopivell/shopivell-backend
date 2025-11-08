from pydantic import BaseModel, ConfigDict, EmailStr
from typing import Optional, List
from datetime import date, datetime
from uuid import UUID

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
    role: Optional[str] = None # Allow updating role (e.g., admin changing to supplier)

class AuthResponse(BaseModel):
    user_id: UUID
    status: str
    role: str

class ImagePathResponse(BaseModel):
    image_path: str

# --- Success Message Schema ---
class SuccessMessage(BaseModel):
    message: str