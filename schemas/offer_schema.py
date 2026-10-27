# schemas/offer_schema.py

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

# Base schema for shared fields
class OfferBase(BaseModel):
    request_id: UUID
    supplier_id: UUID
    proposed_price: float = Field(..., ge=0)
    message: Optional[str] = None
    delivery_date: Optional[datetime] = None

# Schema for creating an offer (input)
class OfferCreate(OfferBase):
    pass

# Schema for updating an offer (input for PATCH/PUT)
class OfferUpdate(BaseModel):
    proposed_price: Optional[float] = Field(None, ge=0)
    message: Optional[str] = None
    delivery_date: Optional[datetime] = None
    status: Optional[str] = None

# Schema for cancelling an offer (input)
class OfferCancel(BaseModel):
    reason: Optional[str] = None

# Existing OfferRead - your current "read" schema
class OfferRead(OfferBase):
    id: UUID
    status: str
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

# NEW: OfferOut - Now explicitly created, identical to OfferRead
class OfferOut(OfferBase):
    id: UUID
    status: str
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# Schema for customer's action on an offer (e.g., accept/reject)
class CustomerOfferAction(BaseModel):
    user_id: UUID
    action: str = Field(..., description="Action to perform: 'accept' or 'reject'")
    reason: Optional[str] = None

# Generic message response (e.g., for success/error messages)
class MessageResponse(BaseModel):
    message: str

# OfferAction - if you still intend to use this and it's distinct from CustomerOfferAction
class OfferAction(BaseModel):
    offer_id: UUID
    action: str = Field(..., description="The action to perform (e.g., 'accept', 'reject', 'cancel')")
    #: Optional[str] = Field(None, description="Optional message related to the action.")
    role: str

class DetailedOfferRead(BaseModel):
    id: UUID
    proposed_price: float
    message: Optional[str] = None
    delivery_date: Optional[datetime] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    # Request details
    request_title: str
    request_description: Optional[str] = None
    request_category: str
    request_initial_price: Optional[float] = None
    request_quantity: int
    
    # Supplier details
    supplier_name: str
    supplier_business_name: Optional[str] = None
    supplier_profile_pic: Optional[str] = None
    
    # Customer details
    customer_name: str
    customer_profile_pic: Optional[str] = None
    
    class Config:
        from_attributes = True  # Enables ORM mode

class OfferDetailResponse(BaseModel):
    id: UUID
    supplier_name: str
    supplier_business_name: str
    proposed_price: float
    message: str | None
    delivery_date: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime | None
    request_title: str
    request_description: str | None
    request_initial_price: float | None
    request_quantity: int
    request_category: str