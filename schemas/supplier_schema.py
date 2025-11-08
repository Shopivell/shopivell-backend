# schemas/supplier_schema.py
from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID

class SupplierBase(BaseModel):
    # These are fields directly from the User model that pertain to a supplier's business profile
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

class SupplierCreate(BaseModel):
    business_name: Optional[str] = None
    business_category: Optional[str] = None
    business_description: Optional[str] = None
    business_type: Optional[str] = None
    business_email: Optional[EmailStr] = None
    business_phone_number: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class SupplierUpdate(SupplierBase):
    # All fields are optional as it's for partial updates
    pass

class SupplierResponse(SupplierBase):
    # This is what you return when you get a supplier's full profile
    user_id: UUID # The ID of the user who is the supplier
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