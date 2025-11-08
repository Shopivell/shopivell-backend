# schemas/auth_schema.py
from pydantic import BaseModel, Field
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