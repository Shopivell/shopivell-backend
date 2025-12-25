# modules/users/schemas.py
from pydantic import BaseModel, ConfigDict, EmailStr
from datetime import datetime
from typing import Optional
import uuid
from .models import UserRole

class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    email: EmailStr
    name: Optional[str] = None
    phone_number: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    marital_status: Optional[str] = None
    address: Optional[str] = None

class UserCreate(UserBase):
    role: UserRole = UserRole.OWNER

class UserUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    name: Optional[str] = None
    phone_number: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    marital_status: Optional[str] = None
    address: Optional[str] = None

class UserResponse(UserBase):
    id: uuid.UUID
    role: UserRole
    is_verified: bool
    is_active: bool
    google_id: Optional[str] = None
    profile_picture: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class LoginRequest(BaseModel):
    email: EmailStr

class LoginVerifyRequest(BaseModel):
    email: EmailStr
    code: str

class GoogleSignupRequest(BaseModel):
    access_token: str
    
class LoginResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserResponse
    store_id: Optional[uuid.UUID] = None
    agency_id: Optional[uuid.UUID] = None
    has_active_setup_session: bool = False
    setup_session_id: Optional[uuid.UUID] = None
    setup_progress: int = 0  # Changed to non-optional with default
    current_setup_step: Optional[str] = None
    has_store: bool = False
    user_status: str  # "no_store", "has_incomplete_setup", "has_store"
    redirect_to: str  # Explicit redirect path
    access_token: Optional[str] = None
    token_type: str = "bearer"

class UserListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    users: list[UserResponse]
    total: int
    page: int
    size: int

# Remove GoogleAuthRequest since it's duplicate, or keep only one
class GoogleAuthRequest(BaseModel):
    access_token: str