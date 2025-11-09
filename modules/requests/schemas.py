# schemas/request_schema.py
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

class RequestBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    category: str = Field(..., max_length=50)
    offer_price: Optional[float] = Field(None, ge=0) # Customer's desired price
    quantity: float = Field(1.0, gt=0)
    image_path: Optional[str] = None

class RequestCreate(BaseModel):
    customer_id: UUID # Assumed from current_user in practice
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    offer_price: Optional[float] = None
    quantity: Optional[float] = None

class RequestUpdate(RequestBase):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    offer_price: Optional[float] = None
    quantity: Optional[float] = None
    image_path: Optional[str] = None
    status: Optional[str] = None # Allow updating status by admin or system

class RequestResponse(BaseModel):
    id: UUID
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    offer_price: Optional[float] = None
    quantity: Optional[float] = None
    image_path: Optional[str] = None

class RequestOut(RequestCreate):
    id: UUID
    status: str
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

# NEW: Schema for supplier's action on a request
class SupplierRequestAction(BaseModel):
    request_id: UUID
    supplier_id: UUID # The ID of the supplier performing the action
    action: str = Field(..., description="Action to perform: 'accept_request' or 'counter_offer'")
    # Fields for counter_offer
    proposed_price: Optional[float] = Field(None, ge=0, description="Required if action is 'counter_offer'")
    #message: Optional[str] = Field(None, description="Message for the customer (required for 'counter_offer')")
    #delivery_date: Optional[datetime] = Field(None, description="Proposed delivery date (required for 'counter_offer')")

class MessageResponse(BaseModel):
    message: str