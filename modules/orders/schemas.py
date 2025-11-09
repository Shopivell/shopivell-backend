# schemas/orders_schema.py
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

class OrderBase(BaseModel):
    # Common fields for an order
    offer_id: UUID
    request_id: UUID
    customer_id: UUID
    supplier_id: UUID
    agreed_price: float # The price customer agreed to from the offer
    quantity: int # Quantity from the request/offer

    model_config = ConfigDict(from_attributes=True)

class OrderCreateFromOffer(BaseModel):
    # This schema is used when a customer accepts an offer to create an order
    customer_id: UUID # The customer confirming the order
    offer_id: UUID # The offer being accepted

class OrderAction(BaseModel):
    # For updating order status (delivered/cancelled)
    user_id: UUID # User performing the action (customer or supplier)
    action: str # "delivered" or "cancelled"

class OrderOut(OrderBase):
    # Full representation of an order for output
    id: UUID
    status: str # e.g., "placed", "delivered", "cancelled"
    created_at: datetime
    updated_at: Optional[datetime] = None # Assuming you add this field to your model

    model_config = ConfigDict(from_attributes=True)

class OrderStatusAction(BaseModel):
    # Full representation of an order for output
    order_id: UUID
    user_id: UUID
    role: str # Role of the user performing the action (e.g., "customer", "supplier")
    action: str # e.g., "deliver", "cancel"

# You might also want schemas for Offer, if they don't exist:
# schemas/offer_schema.py (Example)
# from pydantic import BaseModel, ConfigDict
# from typing import Optional
# from uuid import UUID
# from datetime import datetime

# class OfferBase(BaseModel):
#     request_id: UUID
#     supplier_id: UUID
#     price: float
#     delivery_date: Optional[datetime] = None
#     message: Optional[str] = None
#     model_config = ConfigDict(from_attributes=True)

# class OfferCreate(OfferBase):
#     pass

# class OfferResponse(OfferBase):
#     id: UUID
#     status: str # e.g., "pending", "accepted", "rejected"
#     created_at: datetime
#     updated_at: Optional[datetime] = None
#     model_config = ConfigDict(from_attributes=True)

class MessageResponse(BaseModel):
    message: str

class DetailedOrderOut(BaseModel):
    """Simplified order schema for listing endpoints"""
    order_id: UUID = Field(..., description="Unique identifier for the order")
    order_number: str = Field(..., description="Short order number derived from order ID")
    request_description: str = Field(..., description="Description from the original request")
    agreed_price: float = Field(..., description="Final agreed price for the order")
    quantity: int = Field(..., description="Quantity of items ordered")
    date_ordered: datetime = Field(..., description="When the order was placed")
    image_path: Optional[str] = Field(None, description="Image associated with the request")
    status: str = Field(..., description="Current status of the order")
    customer_name: str = Field(..., description="Name of the customer")
    customer_profile_pic_path: Optional[str] = None
    customer_phone_number: Optional[str] = None
    supplier_name: Optional[str] = None
    supplier_phone_number: Optional[str] = None
    supplier_rating: Optional[str] = None
    supplier_profile_pic_path: Optional[str] = None
    delivery_date: Optional[datetime] = Field(description="Expected delivery date")
    delivery_address: Optional[str] = Field(description="Delivery address")

    class Config:
        json_encoders = {
            Decimal: lambda v: float(v),
            UUID: lambda v: str(v)
        }