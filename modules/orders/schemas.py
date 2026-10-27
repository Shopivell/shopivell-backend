from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional
import uuid

# Base schema
class CustomerOrderBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: uuid.UUID
    customer_id: Optional[uuid.UUID] = None
    order_number: Optional[str] = None
    total_amount: float
    status: Optional[str] = None
    customer_name: str
    phone: Optional[str] = None
    offered_price: Optional[float] = None
    quantity: Optional[int] = None
    customer_profile: Optional[str] = None
    profile_image: Optional[str] = None
    product_name: Optional[str] = None
    product_image: Optional[str] = None
    payment_status: Optional[str] = None
    delivery_status: Optional[str] = None
    payment_method: Optional[str] = None
    transaction_id: Optional[str] = None
    tracking_info: Optional[str] = None

# Create schema
class CustomerOrderCreate(CustomerOrderBase):
    delivery_address: Optional[str] = None
    delivery_city: Optional[str] = None
    # Explicit customer consent to receive WhatsApp marketing messages
    # (collected via unchecked-by-default checkbox at checkout)
    whatsapp_marketing_opt_in: Optional[bool] = False

# Update schema
class CustomerOrderUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    total_amount: Optional[float] = None
    status: Optional[str] = None
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    offered_price: Optional[float] = None
    quantity: Optional[int] = None
    customer_profile: Optional[str] = None
    profile_image: Optional[str] = None
    product_name: Optional[str] = None
    product_image: Optional[str] = None
    payment_status: Optional[str] = None
    delivery_status: Optional[str] = None
    payment_method: Optional[str] = None
    transaction_id: Optional[str] = None

# Response schema
class CustomerOrderResponse(CustomerOrderBase):
    id: uuid.UUID
    order_date: datetime

# List response schema
class CustomerOrderListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    orders: list[CustomerOrderResponse]
    total: int
    page: int
    size: int