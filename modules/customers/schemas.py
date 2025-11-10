from pydantic import BaseModel, ConfigDict, EmailStr
from typing import Optional, List
from datetime import date, datetime
from uuid import UUID

# Base schemas
class CustomerBase(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    customer_type: str = "regular"
    status: str = "active"
    profile_image: Optional[str] = None
    notes: Optional[str] = None

class CustomerSegmentBase(BaseModel):
    name: str
    description: Optional[str] = None
    criteria: Optional[str] = None
    percentage: str = "0%"
    type: str  # purchase_behavior, engagement, loyalty, cart_behavior, value, acquisition, retention, etc.
    is_active: bool = True
    created_by: str

class CustomerOrderBase(BaseModel):
    order_number: str
    total_amount: float
    status: str = "pending"

class CustomerRequestBase(BaseModel):
    title: str
    description: Optional[str] = None
    category: str
    status: str = "pending"
    priority: str = "medium"

# Response schemas
class CustomerResponse(CustomerBase):
    id: UUID
    loyalty_points: int
    created_at: datetime
    updated_at: datetime
    last_activity: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class CustomerSegmentResponse(CustomerSegmentBase):
    id: UUID
    customer_count: int
    created_at: datetime
    updated_at: datetime
    last_activity: datetime

    model_config = ConfigDict(from_attributes=True)

class CustomerOrderResponse(CustomerOrderBase):
    id: UUID
    customer_id: UUID
    order_date: datetime

    model_config = ConfigDict(from_attributes=True)

class CustomerRequestResponse(CustomerRequestBase):
    id: UUID
    customer_id: UUID
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# Create schemas
class CustomerCreate(CustomerBase):
    pass

class CustomerSegmentCreate(CustomerSegmentBase):
    pass

class CustomerOrderCreate(CustomerOrderBase):
    customer_id: UUID

class CustomerRequestCreate(CustomerRequestBase):
    customer_id: UUID

# Update schemas
class CustomerUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    customer_type: Optional[str] = None
    status: Optional[str] = None
    profile_image: Optional[str] = None
    notes: Optional[str] = None
    loyalty_points: Optional[int] = None

class CustomerSegmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    criteria: Optional[str] = None
    percentage: Optional[str] = None
    type: Optional[str] = None
    is_active: Optional[bool] = None
    customer_count: Optional[int] = None

# Bulk operations
class BulkCustomerCreate(BaseModel):
    customers: List[CustomerCreate]

class BulkCustomerResponse(BaseModel):
    created_count: int
    failed_count: int
    failed_customers: List[dict]
    created_customers: List[CustomerResponse]

# List responses
class CustomerListResponse(BaseModel):
    customers: List[CustomerResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int

class CustomerSegmentListResponse(BaseModel):
    segments: List[CustomerSegmentResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int

# Success message
class SuccessMessage(BaseModel):
    message: str

# Segment membership
class SegmentMembership(BaseModel):
    customer_id: UUID
    segment_id: UUID

class BulkSegmentMembership(BaseModel):
    memberships: List[SegmentMembership]